"""Makes the prebuilt server package for players: xi-forever-offline-server-<version>-win64.zip + SHA256SUMS.txt
(Windows), or xi-forever-offline-server-<version>-linux-x64.tar.gz + SHA256SUMS-linux.txt (Linux; built by the
GitHub workflow .github/workflows/linux-release.yml in the server repo).

Run on the dev PC after building the server (Rebuild server.bat):
    python package_server.py v0.1.0              writes dist\\ in this kit folder
    python package_server.py v0.1.0 --list       only shows what would go in, and the size

What goes in: the five server programs and the DLLs they load, settings\\default, and the files git tracks in scripts,
sql, modules, data, res and ximeshes (read from disk), plus the navmeshes submodule. What never goes in: anything git
does not track (backups, logs, crash dumps, settings\\network.lua and the other settings written on this PC, the
launcher's generated configs), the login/profile .cert and .key files (the server makes its own on first start), the
debug libzmq-d_64.dll, .pdb files and the build folder. Upload both files to a GitHub release of
xi-forever-offline-server; the launcher's first-run setup downloads the zip from there and checks it against SHA256SUMS.txt.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = ["xi_connect.exe", "xi_world.exe", "xi_search.exe", "xi_profile.exe", "xi_map.exe"]
DLLS = ["libcrypto-3-x64.dll", "libluajit_64.dll", "libmariadb64.dll", "libssl-3-x64.dll", "libzmq_64.dll"]
LINUX_PROGRAMS = [p[:-4] for p in PROGRAMS]
SUMS = {"windows": "SHA256SUMS.txt", "linux": "SHA256SUMS-linux.txt"}
# Linux: libraries every system has (glibc and the compiler's runtime). Everything else the programs load is copied
# into lib/ beside them (they look there first: built with -DXI_PORTABLE_LINUX=ON, RPATH $ORIGIN/lib).
SYSTEM_LIBS = ("linux-vdso", "ld-linux", "libc.so", "libm.so", "libdl.so", "libpthread.so", "librt.so", "libresolv.so",
               "libutil.so", "libgcc_s.so", "libstdc++.so", "libz.so")


def needed_libs(program):
    """{name: path} of the shared libraries a Linux program loads (ldd), without the system's own."""
    out = subprocess.run(["ldd", program], capture_output=True, text=True).stdout
    found = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\S+)\s+=>\s+(\S+)", line)
        if m and m.group(2).startswith("/") and not m.group(1).startswith(SYSTEM_LIBS):
            found[m.group(1)] = m.group(2)
        elif "not found" in line:
            raise RuntimeError(f"{os.path.basename(program)} needs {line.split()[0]}, which isn't installed here.")
    return found


def bundle_libs(server, lib):
    """Linux: copies the libraries the five programs need into the folder `lib` (it becomes lib/ in the package; each
    under the name the programs ask for) and lets each one find the others there (patchelf, when installed). The
    server folder itself is not changed. Returns the names."""
    os.makedirs(lib, exist_ok=True)
    wanted = {}
    for name in LINUX_PROGRAMS:
        wanted.update(needed_libs(os.path.join(server, name)))
    for name, path in sorted(wanted.items()):
        target = os.path.join(lib, name)
        if os.path.realpath(path) != os.path.realpath(target):
            shutil.copyfile(path, target)                # the file itself, never a link
            os.chmod(target, 0o755)
        if shutil.which("patchelf"):
            subprocess.run(["patchelf", "--set-rpath", "$ORIGIN", target], check=True)
    return sorted(wanted)
GENERATED_DIRS = ["scripts/enum"]   # build output the map server needs (see file_list)
TRACKED = ["scripts", "sql", "modules", "data", "res", "ximeshes", "tools/migrations", "tools/dbtool.py"]   # the last two: database updates for players
ROOT_FILES = ["LICENSE", "README.md"]
NEVER = (".before-", ".bak", ".retired", ".pdb", ".cert", ".key")


def git(server, *args):
    out = subprocess.run(["git", "-C", server] + list(args), capture_output=True, text=True, encoding="utf-8",
                         env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    if out.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + ": " + out.stderr.strip())
    return out.stdout


def walk(server, folder):
    """Every file in a submodule folder, without its git files or backups."""
    out = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(names):
            if name.startswith(".git") or any(mark in name for mark in NEVER):
                continue
            path = os.path.join(root, name)
            out.append((path, os.path.relpath(path, server).replace("\\", "/")))
    return out


def file_list(server, platform="windows", lib=None):
    """[(path on disk, path in the zip)] and a list of warnings. Linux: `lib` is the folder bundle_libs filled."""
    files, warnings = [], []
    programs, libs = (PROGRAMS, DLLS) if platform == "windows" else (LINUX_PROGRAMS, [])
    for name in programs + libs + ROOT_FILES:
        path = os.path.join(server, name)
        if os.path.isfile(path):
            files.append((path, name))
        elif name in programs + libs:
            raise RuntimeError(f"{name} is missing: build the server first.")
    if platform == "linux":
        lib = lib or os.path.join(server, "lib")
        names = sorted(os.listdir(lib)) if os.path.isdir(lib) else []
        if not names:
            raise RuntimeError("No libraries to bundle (lib/ is empty).")
        files += [(os.path.join(lib, n), "lib/" + n) for n in names if os.path.isfile(os.path.join(lib, n))]
    default = os.path.join(server, "settings", "default")
    for name in sorted(os.listdir(default)):
        if name.endswith(".lua"):
            files.append((os.path.join(default, name), "settings/default/" + name))
    tracked = git(server, "ls-files", "-z", "--", *TRACKED).split("\0")
    for rel in sorted(r for r in tracked if r):
        if any(mark in rel for mark in NEVER):
            continue
        path = os.path.join(server, *rel.split("/"))
        if os.path.isfile(path):
            files.append((path, rel))
        elif os.path.isdir(path):                      # a submodule (ximeshes, modules/phoenix_ac): everything in it
            files += walk(server, path)
        else:
            warnings.append("tracked but missing on disk: " + rel)
    files += walk(server, os.path.join(server, "navmeshes"))
    # Files the build generates (git-ignored, so ls-files misses them) that the servers load at run time:
    # scripts/enum/*.codegen.lua holds xi.zone, xi.job, xi.element, xi.effect... Without them the map server's Lua breaks.
    generated = []
    for folder in GENERATED_DIRS:
        root = os.path.join(server, *folder.split("/"))
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                if name.endswith(".codegen.lua"):
                    generated.append((os.path.join(root, name), folder + "/" + name))
    if not generated:
        raise RuntimeError("No scripts/enum/*.codegen.lua files: build the server first (the build generates them).")
    known = {rel for _p, rel in files}
    files += [g for g in generated if g[1] not in known]
    changed = [line for line in git(server, "status", "--porcelain", "--untracked-files=no", "--", *TRACKED).splitlines()]
    if changed:
        warnings.append(f"{len(changed)} tracked file(s) have changes that are not committed; they are packaged as they are "
                        "on disk (commit them so the release matches the repo): " + ", ".join(c[3:] for c in changed[:5]))
    return files, warnings


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the release tag, for example v0.1.0")
    parser.add_argument("--server", help="the server folder (default: server_dir in config.json)")
    parser.add_argument("--out", default=os.path.join(HERE, "dist"))
    parser.add_argument("--list", action="store_true", help="only show what would be packaged")
    parser.add_argument("--platform", choices=("windows", "linux"), default="windows" if os.name == "nt" else "linux")
    parser.add_argument("--bundle-libs", action="store_true", help="(Linux always bundles the libraries; kept for old scripts)")
    args = parser.parse_args(argv)
    server = args.server
    if not server:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as handle:
            server = json.load(handle)["server_dir"]
    lib = None
    if args.platform == "linux":
        import tempfile
        lib = os.path.join(tempfile.mkdtemp(prefix="xifo-libs-"), "lib")
        print("Bundled libraries: " + ", ".join(bundle_libs(server, lib)))
    files, warnings = file_list(server, args.platform, lib)
    size = sum(os.path.getsize(p) for p, _ in files)
    for warning in warnings:
        print("WARNING:", warning)
    top = {}
    for _path, rel in files:
        key = rel.split("/")[0] if "/" in rel else "(top level)"
        top[key] = top.get(key, 0) + 1
    print(f"{len(files)} files, {size / 1e6:.0f} MB before compression: " + ", ".join(f"{k} {v}" for k, v in sorted(top.items())))
    if args.list:
        return 0
    commit = git(server, "rev-parse", "HEAD").strip()
    os.makedirs(args.out, exist_ok=True)
    folder = f"xi-forever-offline-server-{args.version}/"
    version_text = f"XIRPG server {args.version}\ncommit {commit}\n"
    if args.platform == "linux":
        name = f"xi-forever-offline-server-{args.version}-linux-x64.tar.gz"
        target = os.path.join(args.out, name)
        write_tar(target, files, folder, version_text)
    else:
        name = f"xi-forever-offline-server-{args.version}-win64.zip"
        target = os.path.join(args.out, name)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for index, (path, rel) in enumerate(files, 1):
                archive.write(path, folder + rel)
                if index % 2000 == 0:
                    print(f"  {index}/{len(files)}")
            archive.writestr(folder + "VERSION.txt", version_text)
    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    sums = SUMS[args.platform]
    with open(os.path.join(args.out, sums), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{digest.hexdigest()}  {name}\n")
    print(f"Wrote {target} ({os.path.getsize(target) / 1e6:.0f} MB) and {sums} (server commit {commit[:10]}).")
    return 0


def write_tar(target, files, folder, version_text):
    """A .tar.gz with one top folder. Programs and libraries keep their run permission; owner names are left out."""
    import io
    import time

    def clean(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(target, "w:gz", compresslevel=6) as archive:
        for index, (path, rel) in enumerate(files, 1):
            archive.add(path, folder + rel, recursive=False, filter=clean)
            if index % 2000 == 0:
                print(f"  {index}/{len(files)}")
        data = version_text.encode()
        info = tarfile.TarInfo(folder + "VERSION.txt")
        info.size, info.mtime, info.mode = len(data), int(time.time()), 0o644
        archive.addfile(info, io.BytesIO(data))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
