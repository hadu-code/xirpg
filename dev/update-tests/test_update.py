"""Stand-in tests for launcher_update.py (player updates): no network, no MariaDB. Run: python test_update.py [server folder]"""
import hashlib, io, json, os, shutil, sys, tempfile, unittest, zipfile
KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KIT)
import launcher_update as up
import launcher_thirdparty as tp
up.KIT_REPO = up.KIT_REPO or "example/xirpg"      # the fork ships with kit updates off; the tests still cover them


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


class Done:
    def __init__(self, out=""):
        self.returncode, self.stdout, self.stderr = 0, out, ""


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kit = os.path.join(self.tmp, "kit"); os.makedirs(self.kit)
        self.server = os.path.join(self.tmp, "server")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def releases(self, repo_assets):
        """A stand-in GitHub: {repo: [(tag, prerelease, {asset: bytes})]}"""
        urls = {}
        def fetch(url, timeout=60):
            for repo, rels in repo_assets.items():
                if url == tp.API + repo + "/releases?per_page=30":
                    out = []
                    for tag, pre, assets in rels:
                        items = []
                        for name, data in assets.items():
                            urls[f"u/{repo}/{tag}/{name}"] = data
                            items.append({"name": name, "browser_download_url": f"u/{repo}/{tag}/{name}"})
                        out.append({"tag_name": tag, "prerelease": pre, "draft": False, "body": "notes " + tag, "assets": items})
                    return json.dumps(out).encode()
            return urls[url]
        return fetch

    def test_versions_sort_as_numbers(self):
        self.assertGreater(up.version_key("v0.1.10"), up.version_key("v0.1.9"))

    def test_check_respects_test_builds(self):
        open(os.path.join(self.kit, "VERSION.txt"), "w").write("XIRPG v0.1.0\n")
        fetch = self.releases({up.KIT_REPO: [("v0.1.0", True, {}), ("v0.2.0", True, {}), ("v0.1.1", False, {})],
                               up.SERVER_REPO: [("v0.1.0", True, {})]})
        r = up.check(self.kit, None, False, fetch)
        self.assertEqual((r["kit"]["newest"], r["kit"]["newer"]), ("v0.1.1", True))
        self.assertIsNone(r["server"]["newest"])
        self.assertEqual(up.check(self.kit, None, True, fetch)["kit"]["newest"], "v0.2.0")

    def test_kit_update_keeps_personal_files_and_checks_sum(self):
        for name, data in (("config.json", "mine"), ("launcher_core.py", "old"), ("rates.json", "my rates")):
            open(os.path.join(self.kit, name), "w").write(data)
        data = zip_bytes({"XIRPG/launcher_core.py": "new", "XIRPG/VERSION.txt": "XIRPG v0.1.1\n"})
        name = "xi-forever-offline-v0.1.1-win64.zip"
        good = self.releases({up.KIT_REPO: [("v0.1.1", False, {name: data, "SHA256SUMS.txt": (hashlib.sha256(data).hexdigest() + "  " + name).encode()})]})
        rel = up.newest_release(up.KIT_REPO, False, good)
        up.update_kit(self.kit, rel, good, log=lambda m: None)
        read = lambda n: open(os.path.join(self.kit, n)).read()
        self.assertEqual((read("launcher_core.py"), read("config.json"), read("rates.json")), ("new", "mine", "my rates"))
        self.assertEqual(up.installed_version(self.kit), "v0.1.1")
        bad = self.releases({up.KIT_REPO: [("v0.1.2", False, {name: data + b"x", "SHA256SUMS.txt": (hashlib.sha256(data).hexdigest() + "  " + name).encode()})]})
        with self.assertRaises(RuntimeError):
            up.update_kit(self.kit, up.newest_release(up.KIT_REPO, False, bad), bad, log=lambda m: None)

    def test_running_exe_is_moved_aside(self):
        exe = os.path.join(self.kit, "XIRPG.exe"); open(exe, "w").write("old exe")
        zpath = os.path.join(self.tmp, "k.zip"); open(zpath, "wb").write(zip_bytes({"top/XIRPG.exe": "new exe"}))
        up._unpack(zpath, self.kit, log=lambda m: None, running_exe=exe)
        self.assertEqual(open(exe).read(), "new exe")
        self.assertEqual(open(os.path.join(self.kit, "XIRPG.old.exe")).read(), "old exe")

    def test_database_update_keeps_player_tables_and_runs_migrations(self):
        os.makedirs(os.path.join(self.server, "sql")); os.makedirs(os.path.join(self.server, "tools", "migrations"))
        for f in ("accounts.sql", "chars.sql", "item_basic.sql", "triggers.sql"):
            open(os.path.join(self.server, "sql", f), "w").write("--")
        open(os.path.join(self.server, "tools", "migrations", "001_x.py"), "w").write(
            "def migration_name(): return 'x'\ndef check_preconditions(cur): pass\n"
            "def needs_to_run(cur): return True\ndef migrate(cur, db): cur.execute('ALTER x')\n")
        calls, executed = [], []

        def run(cmd, **kw):
            calls.append(cmd[-1])
            return Done("accounts\nchars\nitem_basic\n" if cmd[-1] == "SHOW TABLES" else "")

        class Cur:
            def execute(self, q): executed.append(q)

        class Db:
            def cursor(self): return Cur()
            def commit(self): pass
            def close(self): pass
        cfg = {"mariadb_dir": self.tmp, "db_port": 3306, "db_user": "xi", "db_pass": "p", "db_name": "xiforever"}
        up.update_database(cfg, self.server, log=lambda m: None, run=run, connect=lambda: Db())
        imported = [c for c in calls if "SOURCE" in c]
        self.assertEqual(len(imported), 2)                       # item_basic + triggers; accounts and chars kept
        self.assertTrue(all("accounts.sql" not in c and "chars.sql" not in c for c in imported))
        self.assertEqual(executed, ["ALTER x"])

    def test_real_player_table_list(self):
        server = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
        if not server:
            self.skipTest("no server folder given")
        self.assertEqual(sorted(up.player_tables(server)), sorted(up.PLAYER_DATA))


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=1)
