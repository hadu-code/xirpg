#!/usr/bin/env python3
"""Checks the Phoenix repository for new versions and updates your server safely.

  python server_update.py check            what is new (changes nothing except downloading the list)
  python server_update.py update           back up, merge the new version in, apply database changes, rebuild
  python server_update.py undo [--restore-db]   go back to the version before the last update

How the update stays safe:
  * Your edits to the server's own files (our squad patches, the Goblin Tailor quest, init.txt ...) are saved as ONE local commit
    first, then Phoenix's new version is merged in. If anything clashes, the merge is cancelled and your files are put back exactly
    as they were, so a failed update changes nothing.
  * Before anything changes, the database is saved (backups\\db-before-update-*.sql) and the current version is written to
    update-state.json, which "undo" uses.
  * Files that are not tracked by git (everything in modules\\custom, backups, settings you made) are never touched by a merge.
  * The database tool (tools\\dbtool.py update) and the rebuild only run when the new version needs them.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "update-state.json")
BACKUPS = os.path.join(HERE, "backups")
IDENT = ["-c", "user.name=XIRPG", "-c", "user.email=xiforever@localhost"]
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def say(text=""):
    print(text, flush=True)


def load_config():
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8-sig") as f:
        return json.load(f)


class Git:
    def __init__(self, root):
        self.root = root

    def run(self, *args, ident=False):
        cmd = ["git", "-C", self.root] + (IDENT if ident else []) + list(args)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()

    def out(self, *args):
        rc, out, _ = self.run(*args)
        return out if rc == 0 else ""

    def lines(self, *args):
        return [line for line in self.out(*args).splitlines() if line.strip()]


# ---------- what the update needs, worked out from the files that changed ----------
def needs_rebuild(files):
    return any(re.search(r"\.(cpp|h|hpp|c)$", f) or f.endswith("CMakeLists.txt") or f.endswith(".cmake") or f.startswith("ext/") for f in files)


def needs_reconfigure(name_status_lines):
    """New or removed source files, or changed build files, need cmake to run again."""
    for line in name_status_lines:
        parts = line.split("\t")
        status, paths = parts[0], parts[1:]
        if status[0] in "ADR" and any(re.search(r"\.(cpp|c)$", p) for p in paths):
            return True
        if any(p.endswith("CMakeLists.txt") or p.endswith(".cmake") for p in paths):
            return True
    return False


def needs_database(files):
    return any(f.startswith("sql/") or f.startswith("migrations/") for f in files)


def analyse(g, upstream):
    """What is new upstream, what we changed, and where the two meet."""
    base = g.out("merge-base", "HEAD", upstream)
    theirs = g.lines("diff", "--name-only", base, upstream) if base else []
    ours = sorted(set(g.lines("diff", "--name-only", base, "HEAD") if base else []) | set(g.lines("diff", "--name-only", "HEAD")))
    return {"base": base, "theirs": theirs, "ours": ours, "overlap": [f for f in ours if f in set(theirs)]}


def upstream_ref(g):
    branch = g.out("rev-parse", "--abbrev-ref", "HEAD")
    return branch, f"origin/{branch}"


# ---------- steps that talk to other programs (replaceable, so the logic can be tested) ----------
def default_servers_running():
    if os.name != "nt":
        return False
    out = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.lower()
    return any(name in out for name in ("xi_map.exe", "xi_world.exe", "xi_connect.exe", "xi_search.exe"))



def db_tool(cfg, name):
    """mysqldump / mysql: from the portable MariaDB in the kit when there is one, else from PATH. Port only when set."""
    exe = os.path.join(cfg["mariadb_dir"], "bin", name + ".exe") if cfg.get("mariadb_dir") else name
    return [exe] + ([f"-P{cfg['db_port']}"] if cfg.get("db_port") else [])

def default_backup_db(cfg, path):
    cmd = db_tool(cfg, "mysqldump") + [f"-h{cfg.get('db_host', '127.0.0.1')}", f"-u{cfg['db_user']}", f"-p{cfg['db_pass']}", cfg["db_name"], f"--result-file={path}"]
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW).returncode == 0


def default_restore_db(cfg, path):
    cmd = db_tool(cfg, "mysql") + [f"-h{cfg.get('db_host', '127.0.0.1')}", f"-u{cfg['db_user']}", f"-p{cfg['db_pass']}", cfg["db_name"]]
    with open(path, "rb") as f:
        return subprocess.run(cmd, stdin=f, capture_output=True, creationflags=NO_WINDOW).returncode == 0


def stream(cmd, cwd):
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=NO_WINDOW)
    for line in p.stdout:
        say("    " + line.rstrip())
    return p.wait()


def default_dbtool_update(cfg):
    return stream([sys.executable, os.path.join(cfg["server_dir"], "tools", "dbtool.py"), "update"], cfg["server_dir"]) == 0


def default_rebuild(cfg, reconfigure):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HERE, "rebuild.ps1")]
    if reconfigure:
        cmd.append("-Reconfigure")
    return stream(cmd, HERE) == 0


def default_submodules(cfg):
    return Git(cfg["server_dir"]).run("submodule", "update", "--init", "--recursive")[0] == 0


HOOKS = {
    "servers_running": default_servers_running,
    "backup_db": default_backup_db,
    "restore_db": default_restore_db,
    "dbtool_update": default_dbtool_update,
    "rebuild": default_rebuild,
    "submodules": default_submodules,
}


# ---------- modes ----------
def short(sha):
    return (sha or "")[:9]


def check(cfg, fetch=True):
    g = Git(cfg["server_dir"])
    if not os.path.exists(os.path.join(cfg["server_dir"], ".git")):
        say("The server folder is not a git checkout, so there is nothing to compare with.")
        return None
    branch, upstream = upstream_ref(g)
    say(f"Server folder: {cfg['server_dir']}")
    say("Remote: " + (g.out("remote", "get-url", "origin") or "none"))
    say(f"Branch: {branch}   Your version: {short(g.out('rev-parse', 'HEAD'))}   {g.out('log', '-1', '--date=short', '--pretty=format:%ad  %s')}")
    if fetch:
        say("Checking for new commits (needs the internet)...")
        rc, _, err = g.run("fetch", "origin", "--quiet")
        if rc != 0:
            say("The check failed: no internet, or the remote can not be reached. " + err[:200])
            return None
    if g.run("rev-parse", "--verify", "--quiet", upstream)[0] != 0:
        say(f"There is no {upstream} on the remote.")
        return None
    behind = int(g.out("rev-list", "--count", f"HEAD..{upstream}") or 0)
    info = analyse(g, upstream)
    info.update({"behind": behind, "branch": branch, "upstream": upstream})
    say()
    if behind == 0:
        say("You are up to date. Nothing to update.")
        return info
    say(f"{behind} new commit(s) from Phoenix. The newest:")
    for line in g.lines("log", f"HEAD..{upstream}", "--date=short", "--pretty=format:%ad  %s", "-n", "25"):
        say("  " + line)
    areas = {}
    for f in info["theirs"]:
        parts = f.split("/")
        key = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        areas[key] = areas.get(key, 0) + 1
    say()
    say(f"{len(info['theirs'])} file(s) change. Where:")
    for key, count in sorted(areas.items(), key=lambda kv: -kv[1])[:12]:
        say(f"  {count:>5}  {key}")
    say()
    say("This update will " + ("" if needs_rebuild(info["theirs"]) else "NOT ") + "need a rebuild of the server (a few minutes to half an hour).")
    say("This update will " + ("" if needs_database(info["theirs"]) else "NOT ") + "change the database.")
    say()
    say(f"Server files you (or our patches) changed: {len(info['ours'])}")
    if info["overlap"]:
        say("!! Phoenix ALSO changed these, so the update may clash (it would be cancelled and nothing would change):")
        for f in info["overlap"]:
            say("   " + f)
    else:
        say("None of those were touched by Phoenix, so the update should merge cleanly.")
    return info


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=2)


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def put_back(g, before, ours_commit):
    """Cancel a merge that did not work and restore the files exactly as they were before the update started."""
    g.run("merge", "--abort")
    if ours_commit:
        g.run("reset", "--mixed", before)          # our edits go back to being uncommitted changes
    else:
        g.run("reset", "--hard", before)


def update(cfg, hooks=None, force_running=False):
    hooks = {**HOOKS, **(hooks or {})}
    root = cfg["server_dir"]
    g = Git(root)
    if not os.path.exists(os.path.join(root, ".git")):
        say("The server folder is not a git checkout.")
        return 1
    if not force_running and hooks["servers_running"]():
        say("The server is running. Close the game first, then try again.")
        return 1
    if g.run("rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0:
        say("A merge is already in progress in the server folder. Nothing was changed. Tell Claude.")
        return 1

    branch, upstream = upstream_ref(g)
    say("Checking what is new...")
    rc, _, err = g.run("fetch", "origin", "--quiet")
    if rc != 0:
        say("Could not reach the Phoenix repository: " + err[:200])
        return 1
    behind = int(g.out("rev-list", "--count", f"HEAD..{upstream}") or 0)
    if behind == 0:
        say("You are up to date. Nothing to do.")
        return 2

    before = g.out("rev-parse", "HEAD")
    info = analyse(g, upstream)
    theirs = info["theirs"]
    name_status = g.lines("diff", "--name-status", info["base"], upstream) if info["base"] else []
    rebuild, reconfigure, database = needs_rebuild(theirs), needs_reconfigure(name_status), needs_database(theirs)
    say(f"{behind} new commit(s). Rebuild needed: {'yes' if rebuild else 'no'}. Database changes: {'yes' if database else 'no'}.")

    # 1. backups
    os.makedirs(BACKUPS, exist_ok=True)
    tag = stamp()
    db_backup = os.path.join(BACKUPS, f"db-before-update-{tag}.sql")
    say("Saving the database...")
    if not hooks["backup_db"](cfg, db_backup):
        say("The database backup FAILED, so nothing was changed. Is the database running?")
        return 1
    for name in ("custom",):
        src = os.path.join(root, "modules", name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(BACKUPS, f"modules-{name}-before-update-{tag}"), dirs_exist_ok=True)
    g.run("diff", "HEAD", f"--output={os.path.join(BACKUPS, f'server-edits-before-update-{tag}.patch')}")
    state = {"time": tag, "branch": branch, "before": before, "ours_commit": None, "db_backup": db_backup, "stage": "started"}
    save_state(state)

    # 2. our edits become one local commit, so the merge can be cancelled cleanly
    ours_commit = None
    if g.run("diff", "--quiet", "HEAD")[0] != 0:
        say("Saving your server edits as a local commit...")
        g.run("add", "-u")
        rc, _, err = g.run("commit", "-m", f"XIRPG: local server edits before update {tag}", ident=True)
        if rc != 0:
            say("Could not save your edits (" + err[:200] + "). Nothing was changed.")
            g.run("reset", "--mixed", before)
            return 1
        ours_commit = g.out("rev-parse", "HEAD")
    state["ours_commit"] = ours_commit
    save_state(state)

    # 3. merge the new version in
    say("Merging the new version...")
    rc, _, err = g.run("merge", "--no-edit", upstream, ident=True)
    if rc != 0:
        conflicts = g.lines("diff", "--name-only", "--diff-filter=U")
        put_back(g, before, ours_commit)
        state["stage"] = "cancelled"
        save_state(state)
        say()
        say("The update was CANCELLED and your server is exactly as it was.")
        if conflicts:
            say("These files clash with your changes (Phoenix and we both edited the same lines):")
            for f in conflicts:
                say("   " + f)
        else:
            say("Reason: " + (err or "the merge could not be done")[:300])
        say("Tell Claude and paste this; the patches will be reworked and then the update can be tried again.")
        return 1
    state["stage"] = "merged"
    state["after"] = g.out("rev-parse", "HEAD")
    state["rebuild"], state["database"] = rebuild, database
    save_state(state)
    say("Merged.")
    hooks["submodules"](cfg)

    # 4. database
    if database:
        say("Applying the database changes (the project's own tool)...")
        if not hooks["dbtool_update"](cfg):
            say("!! The database tool reported a problem (see above). The code is updated but the database may not be.")
            say("   You can go back with the Undo button (it can also restore the database saved at the start).")
            state["stage"] = "database-failed"
            save_state(state)
            return 1

    # 5. rebuild
    if rebuild:
        say("Rebuilding the server (this can take a while)...")
        if not hooks["rebuild"](cfg, reconfigure):
            say("!! The build FAILED (see above). Use the Undo button to go back to the version that worked.")
            state["stage"] = "build-failed"
            save_state(state)
            return 1

    # 6. our own modules are still switched on?
    init = os.path.join(root, "modules", "init.txt")
    missing = []
    if os.path.exists(init):
        text = open(init, "r", encoding="utf-8-sig", errors="replace").read()
        for line in re.findall(r"^custom/lua/\S+", text, re.M):
            if not os.path.exists(os.path.join(root, "modules", line)):
                missing.append(line)
    if missing:
        say("Note: init.txt lists modules whose files are missing: " + ", ".join(missing))
    state["stage"] = "done"
    save_state(state)
    say()
    say("UPDATE DONE. Start the game from the launcher. If something looks wrong, use Undo.")
    return 0


def undo(cfg, hooks=None, restore_db=False, force_running=False):
    hooks = {**HOOKS, **(hooks or {})}
    state = load_state()
    if not state or not state.get("before"):
        say("There is no earlier update to undo.")
        return 1
    if not force_running and hooks["servers_running"]():
        say("The server is running. Close the game first.")
        return 1
    g = Git(cfg["server_dir"])
    if state.get("stage") == "undone":
        say("The last update was already undone.")
        return 1
    if g.run("rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0:
        g.run("merge", "--abort")
    say(f"Going back to version {short(state['before'])}...")
    if state.get("ours_commit"):
        g.run("reset", "--hard", state["ours_commit"])
        g.run("reset", "--mixed", state["before"])      # our edits are uncommitted changes again, as before the update
    else:
        g.run("reset", "--hard", state["before"])
    hooks["submodules"](cfg)
    if restore_db and state.get("db_backup") and os.path.exists(state["db_backup"]):
        say("Putting the saved database back (anything you did since the update is lost)...")
        if not hooks["restore_db"](cfg, state["db_backup"]):
            say("!! The database could not be restored. The file is " + state["db_backup"])
    if state.get("rebuild"):
        say("The code changed back, so the server is being rebuilt...")
        if not hooks["rebuild"](cfg, True):
            say("!! The rebuild failed. Run rebuild.ps1 -Reconfigure yourself and send Claude the last lines.")
            return 1
    state["stage"] = "undone"
    save_state(state)
    say("DONE. The server is back on the version from before the update.")
    return 0


def main(argv):
    mode = argv[1] if len(argv) > 1 else "check"
    cfg = load_config()
    if mode == "check":
        check(cfg)
        return 0
    if mode == "update":
        return update(cfg)
    if mode == "undo":
        return undo(cfg, restore_db="--restore-db" in argv)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
