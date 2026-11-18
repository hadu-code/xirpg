"""Tests for launcher_coop.py: two launchers talking (in one process and over a real local socket), on the two scratch
databases of cooptest.py. Run: python test_coop.py"""
import os, shutil, socket, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cooptest as ct
import launcher_coop as co
import launcher_passport as pp

ACC, CHAR = 1000, 21828
EC_CERT = """-----BEGIN CERTIFICATE-----
MIIBdjCCARugAwIBAgIULDlKfR9l/fb0yXTvvQVLjxXNiRowCgYIKoZIzj0EAwIw
EDEOMAwGA1UEAwwFeGkgZWMwHhcNMjYxMTE3MDYzMzAzWhcNMzYxMTE0MDYzMzAz
WjAQMQ4wDAYDVQQDDAV4aSBlYzBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABIfg
ZOOG8MR+IvKcvM6uVtZcvTW7WsTAT7qf5NDqIqeF74k4B7N1OY33jPg6RXnzfoW+
SoigdfLy2NwyJr3if/qjUzBRMB0GA1UdDgQWBBRkpSWSPSkj5MrYpKOM1Xb7jDLv
nTAfBgNVHSMEGDAWgBRkpSWSPSkj5MrYpKOM1Xb7jDLvnTAPBgNVHRMBAf8EBTAD
AQH/MAoGCCqGSM49BAMCA0kAMEYCIQDPoRUAVW6zF0u8Lq/RLrk6auscKOXwjY2i
lfGcrpzw9AIhAO5mn9ctQp0qW9RBg+prSZMDmmkpLMMjg+SuuAbnw+rp
-----END CERTIFICATE-----
"""
EC_KEY = "SHA256:auYh3nDD3T27FzeUjneaYCuGCEE5nW8gdpDCOvZzsKU"      # from openssl: the SHA-256 of the certificate's public key
# the certificate and fingerprint of xiloader's own tests (phoenixffxi/xiloader tests/check.cpp, kTestCert): the loader
# must compute the same text from a server's certificate as the launcher does, or a visitor's game refuses to connect
LOADER_CERT = """-----BEGIN CERTIFICATE-----
MIIBDDCBs6ADAgECAgEBMAoGCCqGSM49BAMCMA8xDTALBgNVBAMMBHRlc3QwIBcN
MjYwMTAxMDAwMDAwWhgPMjEyNTEyMDgwMDAwMDBaMA8xDTALBgNVBAMMBHRlc3Qw
WTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAASwbGIkyhvRgigpcqra5z8ED4Ucmozy
8n/VJHznJKuw15E9YLhvZoXaxV21BJ2L/pv5VdpzOiOMxY8Udht/7v0lMAoGCCqG
SM49BAMCA0gAMEUCIBX/KS5+0nCJtKuhjmXQu3T7VhYJIFSZlyc0aIddco+YAiEA
jfgkHciDspy3cTuUvUgkBwkANFNN+XIUHX2cyxg+BNQ=
-----END CERTIFICATE-----
"""
LOADER_KEY = "SHA256:IkhRxEk3oYnYqqIL4KWZ/JZBriCuL529sTOX0yN2sGM"


def read(path, mode="r"):
    with open(path, mode) as handle:
        return handle.read()


def setUpModule():
    try:
        ct.drop_worlds()
    except Exception as e:
        raise unittest.SkipTest(f"no database to test on ({e})")


def tearDownModule():
    ct.drop_worlds()


class Plain(unittest.TestCase):
    """The parts that need no database."""

    def test_sealed_messages(self):
        key, other = os.urandom(16), os.urandom(16)
        blob = os.urandom(70000)
        sealed = co.seal(key, {"op": "x", "n": 5}, blob)
        self.assertEqual(co.unseal(key, sealed), ({"op": "x", "n": 5}, blob))
        self.assertNotIn(blob[:64], sealed)                                # the file is not readable in passing
        self.assertNotEqual(sealed, co.seal(key, {"op": "x", "n": 5}, blob))   # never the same bytes twice
        with self.assertRaises(co.CoopError):
            co.unseal(other, sealed)
        for spot in (5, 30, 60, len(sealed) - 1):
            broken = bytearray(sealed)
            broken[spot] ^= 1
            with self.assertRaises(co.CoopError):
                co.unseal(key, bytes(broken))
        self.assertEqual(co.unseal(key, co.seal(key, {})), ({}, b""))

    def test_invite_codes(self):
        secret = "ab" * 16
        code = co.make_invite("192.168.1.20", 54100, secret, "Hurami's world")
        self.assertTrue(code.startswith("XIFO1-"))
        self.assertEqual(co.read_invite("  " + code[:20] + "\n" + code[20:] + " "),
                         {"address": "192.168.1.20", "port": 54100, "secret": secret, "world": "Hurami's world"})
        for bad in ("", "hello", "XIFO1-!!!", co.make_invite("bad host;rm", 1, secret, "w"), co.make_invite("1.2.3.4", 70000, secret, "w"),
                    co.make_invite("1.2.3.4", 54100, "short", "w")):
            with self.assertRaises(co.CoopError):
                co.read_invite(bad)

    def test_logins_come_from_the_invite(self):
        gkey = co.guest_key("ab" * 16, "0123456789abcdef01234567")
        self.assertEqual(gkey, co.guest_key("ab" * 16, "0123456789abcdef01234567"))
        self.assertNotEqual(gkey, co.guest_key("ab" * 16, "1123456789abcdef01234567"))
        self.assertRegex(co.guest_login("0123456789abcdef01234567"), r"^[a-z0-9]{3,16}$")
        self.assertRegex(co.guest_password(gkey), r"^[a-z2-7]{16}$")

    def test_server_key_matches_openssl(self):
        self.assertEqual(co.certificate_fingerprint(EC_CERT), EC_KEY)
        self.assertEqual(co.certificate_fingerprint(LOADER_CERT), LOADER_KEY)
        self.assertIsNone(co.certificate_fingerprint("not a certificate"))
        folder = tempfile.mkdtemp()
        try:
            self.assertIsNone(co.server_fingerprint(folder))
            with open(os.path.join(folder, "login.cert"), "w") as handle:
                handle.write(EC_CERT)
            self.assertEqual(co.server_fingerprint(folder), EC_KEY)
        finally:
            shutil.rmtree(folder)

    def test_boot_file_for_a_visit(self):
        self.assertEqual(co.visit_command("--server 127.0.0.1 --user me --pass secret --hide", "100.64.0.9", "vabc", "pw", EC_KEY),
                         f"--server 100.64.0.9 --user vabc --pass pw --fingerprint {EC_KEY} --hide")
        self.assertEqual(co.visit_command("", "10.0.0.2", "vabc", "pw", "SHA256:x; calc"), "--server 10.0.0.2 --user vabc --pass pw")
        ashita = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(ashita, "config", "boot"))
            with open(os.path.join(ashita, "config", "boot", "xiforever.ini"), "w") as handle:
                handle.write("[ashita.boot]\nfile = .\\\\bootloader\\\\xiloader.exe\ncommand = --server 127.0.0.1 --user me --pass mine\nscript = xiforever.txt\n")
            host = {"address": "10.0.0.2", "game_address": "10.0.0.2", "login": "vabc", "gkey": "cd" * 32, "fingerprint": EC_KEY}
            self.assertEqual(co.write_visit_boot(ashita, "xiforever.ini", host), co.VISIT_BOOT)
            text = read(os.path.join(ashita, "config", "boot", co.VISIT_BOOT))
            self.assertIn(f"command = --server 10.0.0.2 --user vabc --pass {co.guest_password('cd' * 32)} --fingerprint {EC_KEY}", text)
            self.assertIn("script = xiforever.txt", text)
            self.assertIn("--user me --pass mine", read(os.path.join(ashita, "config", "boot", "xiforever.ini")))   # untouched
            with self.assertRaises(co.CoopError):
                co.write_visit_boot(ashita, "xiforever.ini", dict(host, game_address="evil & calc", address="evil & calc"))
        finally:
            shutil.rmtree(ashita)

    def test_macros_follow_the_character(self):
        game = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(game, "USER", "5544"))
            with open(os.path.join(game, "USER", "5544", "mcr.dat"), "w") as handle:
                handle.write("macros")
            self.assertTrue(co.copy_user_folder(game, 0x5544, 0x5545))
            self.assertEqual(read(os.path.join(game, "USER", "5545", "mcr.dat")), "macros")
            self.assertFalse(co.copy_user_folder(game, 0x5544, 0x5544))
            self.assertFalse(co.copy_user_folder(game, 0x7777, 0x5545))
            self.assertFalse(co.copy_user_folder(None, 1, 2))
        finally:
            shutil.rmtree(game)

    def test_addresses(self):
        self.assertEqual([co.address_kind(a) for a in ("192.168.1.5", "10.1.2.3", "172.20.0.1", "100.101.102.103", "127.0.0.1", "8.8.8.8", "169.254.1.1")],
                         ["lan", "lan", "lan", "tailscale", "loopback", "direct", "none"])
        self.assertEqual(co.suggest_address("tailscale", [{"address": "192.168.1.5", "kind": "lan"}, {"address": "100.70.1.1", "kind": "tailscale"}]), "100.70.1.1")
        self.assertEqual(co.suggest_address("lan", []), "")

    def test_firewall(self):
        script = co.firewall_script(r"C:\XIRPG\server", 54100, "tailscale")
        for piece in (r"'C:\XIRPG\server\xi_map.exe'", "-RemoteAddress 100.64.0.0/10", "-LocalPort 54100", co.FIREWALL_RULE):
            self.assertIn(piece, script)
        self.assertIn("LocalSubnet", co.firewall_script("C:\\s", 54100, "lan"))

        class Done:
            returncode, stderr = 0, ""
            def __init__(self, out):
                self.stdout = out
        self.assertTrue(co.firewall_open("C:\\s", 54100, "lan", run=lambda *a, **k: Done("5\n"))[0])
        self.assertFalse(co.firewall_open("C:\\s", 54100, "lan", run=lambda *a, **k: Done("Access denied"))[0])

    def test_get_tailscale(self):
        kit = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, kit, True)
        folder = os.path.join(kit, "coop", "downloads")
        installer = b"MZ" + b"\0" * (2 * 1024 * 1024)

        class Answer:
            def __init__(self, body, url="https://dl.tailscale.com/stable/tailscale-setup-1.99.0.exe"):
                self.body, self.url = body, url
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def geturl(self):
                return self.url
            def read(self, n):
                piece, self.body = self.body[:n], self.body[n:]
                return piece

        asked = []
        def opener(body=installer, **kw):
            def go(request, timeout=None):
                asked.append(request.full_url)
                return Answer(body, **kw)
            return go
        # only Tailscale's own site counts
        for url, ok in (("https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe", True), ("https://dl.tailscale.com/x.exe", True),
                        ("https://tailscale.com/download", True), ("http://pkgs.tailscale.com/x.exe", False),
                        ("https://tailscale.com.example.org/x.exe", False), ("https://nottailscale.com/x.exe", False), ("", False)):
            self.assertEqual(co._tailscale_site(url), ok, url)
        self.assertTrue(co._tailscale_site(co.TAILSCALE_INSTALLER) and co._tailscale_site(co.TAILSCALE_PAGE))

        said = []
        path = co.download_tailscale(kit, said.append, opener())
        self.assertEqual((path, asked), (os.path.join(folder, "tailscale-setup.exe"), [co.TAILSCALE_INSTALLER]))
        self.assertEqual(open(path, "rb").read(), installer)
        self.assertEqual(os.listdir(folder), ["tailscale-setup.exe"])
        self.assertIn("2 MB", said[-1])
        os.remove(path)
        # what must not be kept: an error page, a hand-over to another site, a download that never ends, no internet
        def no_internet(request, timeout=None):
            raise OSError("no route to host")
        for bad in (opener(b"<html>not found</html>"), opener(b"<!" + b"x" * (2 * 1024 * 1024)), opener(url="https://example.org/tailscale-setup.exe"),
                    no_internet):
            with self.assertRaises(co.CoopError):
                co.download_tailscale(kit, said.append, bad)
            self.assertEqual(os.listdir(folder), [])
        limit, co.TAILSCALE_MAX_BYTES = co.TAILSCALE_MAX_BYTES, 1024 * 1024
        try:
            with self.assertRaises(co.CoopError):
                co.download_tailscale(kit, said.append, opener())
        finally:
            co.TAILSCALE_MAX_BYTES = limit
        self.assertEqual(os.listdir(folder), [])

        # Windows has to vouch for the file: a valid signature, and Tailscale's
        class Checked:
            returncode, stderr = 0, ""
            def __init__(self, out):
                self.stdout = out
        calls = []
        def windows(out):
            def run(args, **kw):
                calls.append((args, kw))
                return Checked(out)
            return run
        theirs = "Valid\nCN=Tailscale Inc., O=Tailscale Inc., L=Toronto, S=Ontario, C=CA\n"
        self.assertEqual(co.signed_by_tailscale(r"C:\kit\x y.exe", windows(theirs))[0], True)
        args, kw = calls[-1]
        self.assertEqual(kw["env"]["XIFO_CHECK_FILE"], r"C:\kit\x y.exe")
        self.assertNotIn("x y.exe", " ".join(args))                       # the path is never part of the command text
        self.assertIn("Get-AuthenticodeSignature", " ".join(args))
        for out in ("Valid\nCN=Somebody Else, O=Somebody Else, C=US\n", "NotSigned\n", "HashMismatch\nCN=Tailscale Inc., O=Tailscale Inc., C=CA\n",
                    "Valid\nCN=Tailscale Inc. Fans, O=Others, C=US\n", "Valid\n", ""):
            ok, detail = co.signed_by_tailscale("x.exe", windows(out))
            self.assertFalse(ok, out)
            self.assertIn("signature", detail)
        def broken(args, **kw):
            raise FileNotFoundError("powershell")
        self.assertFalse(co.signed_by_tailscale("x.exe", broken)[0])

        # the button: download, check, start. Nothing is started unless the check passed, and a refused file is removed.
        started = []
        self.assertEqual(co.install_tailscale(kit, said.append, windows(theirs), opener(), started.append), path)
        self.assertEqual(started, [path])
        self.assertTrue(os.path.exists(path))
        started.clear()
        with self.assertRaises(co.CoopError) as refused:
            co.install_tailscale(kit, said.append, windows("NotSigned\n"), opener(), started.append)
        self.assertIn("signature", str(refused.exception))
        self.assertEqual((started, os.listdir(folder)), ([], []))
        with self.assertRaises(co.CoopError):
            co.install_tailscale(kit, said.append, windows(theirs), no_internet, started.append)
        self.assertEqual(started, [])
        def declined(p):
            raise OSError("The operation was canceled by the user")
        with self.assertRaises(co.CoopError) as told:
            co.install_tailscale(kit, said.append, windows(theirs), opener(), declined)
        self.assertIn(path, str(told.exception))                           # ...and says where the installer is

        # installed or not, logged in or not
        program, address = co.tailscale_program, co.tailscale_address
        try:
            co.tailscale_program = lambda: None
            self.assertEqual(co.tailscale_state(), "missing")
            co.tailscale_program = lambda: r"C:\Program Files\Tailscale\tailscale.exe"
            co.tailscale_address = lambda run=None: None
            self.assertEqual(co.tailscale_state(), "off")
            co.tailscale_address = lambda run=None: "100.101.102.103"
            self.assertEqual(co.tailscale_state(), "ready")
        finally:
            co.tailscale_program, co.tailscale_address = program, address

    def test_settings_and_take_back_rule(self):
        kit = tempfile.mkdtemp()
        try:
            settings = co.load_settings(kit)
            self.assertFalse(settings["enabled"] or settings["hosting"])
            self.assertRegex(settings["secret"], r"^[0-9a-f]{32}$")
            settings.update({"enabled": True, "max_guests": 99, "mode": "nonsense"})
            co.save_settings(kit, settings)
            again = co.load_settings(kit)
            self.assertEqual((again["enabled"], again["max_guests"], again["mode"], again["secret"]), (True, 6, "lan", settings["secret"]))
        finally:
            shutil.rmtree(kit)
        now = 1_000_000
        self.assertTrue(co.can_take_back({"arrived": False}, now)[0])
        self.assertFalse(co.can_take_back({"arrived": True}, now)[0])
        self.assertFalse(co.can_take_back({"arrived": True, "unreachable_since": now - 3600}, now)[0])
        self.assertTrue(co.can_take_back({"arrived": True, "unreachable_since": now - 25 * 3600}, now)[0])
        self.assertTrue(co.can_take_back({"arrived": True, "gone": True}, now)[0])
        self.assertIsNone(co.versions_clash({"server": "v0.1.30"}, {"server": "v0.1.30"}))
        self.assertIsNone(co.versions_clash({"server": "dev"}, {"server": "v0.1.30"}))
        self.assertIn("v0.1.29", co.versions_clash({"server": "v0.1.30"}, {"server": "v0.1.29"}))


class TwoLaunchers(unittest.TestCase):
    def setUp(self):
        self.home = ct.make_world(ct.HOME_DB)
        self.host_db = ct.make_world(ct.HOST_DB)
        ct.make_account(self.home, ACC, "homeplayer")
        ct.make_character(self.home, ACC, CHAR, "Visitor")
        ct.make_character(self.home, ACC, CHAR + 2, "Alt", linkshell=False)
        ct.make_account(self.host_db, ACC, "hostplayer")
        ct.make_character(self.host_db, ACC, CHAR, "Hostess", linkshell=False)
        self.tmp = tempfile.mkdtemp()
        self.kit_home, self.kit_host, self.server = (os.path.join(self.tmp, n) for n in ("home", "host", "server"))
        for folder in (self.kit_home, self.kit_host, os.path.join(self.server, "modules", "custom", "lua")):
            os.makedirs(folder)
        with open(os.path.join(self.server, "login.cert"), "w") as handle:
            handle.write(EC_CERT)
        self.settings = co.load_settings(self.kit_host)
        self.settings.update({"enabled": True, "hosting": True, "address": "127.0.0.1", "max_guests": 3})
        self.logs = []
        self.host = co.Host({"server_dir": self.server}, self.kit_host, self.settings, log=self.logs.append, connect=lambda: ct.connect(ct.HOST_DB))
        self.cfg = {"server_dir": None}
        self.down = False
        self.invite = co.read_invite(co.make_invite("127.0.0.1", 54100, self.settings["secret"], "Host world"))

    def tearDown(self):
        self.host.stop()
        for conn in (self.home, self.host_db):
            conn.rollback()
            conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # the "network": straight into the host object, or nothing when the host is switched off
    def post(self, address, port, key_header, body, timeout):
        if self.down:
            raise OSError("no route")
        try:
            return self.host.handle(key_header, body, "tester")
        except co.Busy:
            raise OSError("503")
        except Exception:
            error = OSError("403")
            error.code = 403
            raise error

    def home_conn(self):
        return ct.connect(ct.HOME_DB)

    def kw(self):
        return {"post": self.post, "connect": self.home_conn, "log": self.logs.append}

    def q(self, conn, sql, params=()):
        rows = ct.run(conn, sql, params)
        conn.rollback()
        return rows

    def go(self):
        return co.start_visit(self.cfg, self.kit_home, self.invite, CHAR, **self.kw())

    def row(self):
        return co.away(self.cfg, self.home_conn)[0]

    def guest(self):
        return self.host.guests()[0]

    # --- the happy path ---
    def test_a_whole_visit(self):
        greeting = co.hello(self.invite, post=self.post)
        self.assertEqual((greeting["open"], greeting["guests"], greeting["max_guests"], greeting["fingerprint"]), (True, 0, 3, EC_KEY))
        host = self.go()
        self.assertTrue(host["arrived"])
        self.assertNotIn("secret", host)                                   # the invite's secret is not kept after arriving
        self.assertEqual(host["fingerprint"], EC_KEY)
        guest = self.guest()
        self.assertEqual((guest["name"], guest["state"], guest["login"]), ("Visitor", "active", host["login"]))
        self.assertNotIn(guest["charid"], (CHAR, CHAR + 2))                 # not the host's id, not the visitor's other character's
        self.assertEqual(host["host_charid"], guest["charid"])
        self.assertIn("Visitor is visiting this world.", read(os.path.join(self.server, "modules", "custom", "lua", "coop_in.txt")))
        self.assertFalse(os.path.exists(co._outgoing(self.kit_home, CHAR)))
        # the launcher's regular look: a first copy at once, then not again for five minutes unless something happened
        now = time.time()
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now, **self.kw()), "checkpoint")
        self.assertTrue(os.path.exists(co.checkpoint_file(self.kit_home, CHAR)))
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 20, **self.kw()), "ok")
        self.host.last_checkpoint.clear()
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 400, **self.kw()), "ok")   # offline, nothing new
        ct.run(self.host_db, "INSERT INTO accounts_sessions (accid, charid, session_key, server_addr, server_port, client_addr) VALUES (?, ?, 'k', 0, 0, 0)",
               (guest["accid"], guest["charid"]))
        ct.run(self.host_db, "UPDATE char_stats SET mlvl = 31 WHERE charid = ?", (guest["charid"],))
        self.host_db.commit()
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 800, **self.kw()), "checkpoint")   # playing: a fresh copy
        self.assertEqual(pp.unpack(read(co.checkpoint_file(self.kit_home, CHAR), "rb"))["summary"]["level"], 31)
        # coming home: not while in the game, not past things left behind unless asked
        with self.assertRaises(co.Refused) as stop:
            co.come_home(self.cfg, self.kit_home, CHAR, **self.kw())
        self.assertEqual(stop.exception.code, "online")
        ct.run(self.host_db, "DELETE FROM accounts_sessions WHERE charid = ?", (guest["charid"],))
        ct.run(self.host_db, "INSERT INTO delivery_box (charid, charname, box, slot, itemid, itemsubid, quantity, extra, senderid, sender, received, sent) "
                             "VALUES (?, 'Visitor', 1, 8, 4112, 0, 3, NULL, 0, 'AH-Jeuno', 0, 0)", (guest["charid"],))
        self.host_db.commit()
        with self.assertRaises(co.Refused) as stop:
            co.come_home(self.cfg, self.kit_home, CHAR, **self.kw())
        self.assertEqual((stop.exception.code, stop.exception.extra["holdings"]), ("holdings", {"auctions": 0, "delivery": 1}))
        self.assertEqual(self.guest()["state"], "active")
        result = co.come_home(self.cfg, self.kit_home, CHAR, force=True, **self.kw())
        self.assertEqual((result["name"], result["already"], result["changes"]["levels"]), ("Visitor", False, 1))
        self.assertEqual(self.q(self.home, "SELECT c.accid, s.mlvl FROM chars c JOIN char_stats s USING (charid) WHERE c.charid = ?", (CHAR,)), [(ACC, 31)])
        self.assertEqual(co.away(self.cfg, self.home_conn), [])
        self.assertEqual(self.host.guests(), [])                            # the host heard, and tidied up
        self.assertEqual(self.q(self.host_db, "SELECT charname FROM chars"), [("Hostess",)])
        self.assertFalse(os.path.exists(co.checkpoint_file(self.kit_home, CHAR)))
        self.assertTrue(any("home safely" in line for line in self.logs))

    def test_squad_mates_come_along(self):
        ct.make_squad(self.host_db, CHAR, [(1, "Momo", 1, 60), (2, "Kyo", 3, 60)])
        home = ct.make_squad(self.home, CHAR, [(1, "Kasumi", 1, 30), (3, "Gio", 3, 28)], unlocks=(100,))
        ct.make_squad(self.home, CHAR + 2, [(1, "Stays", 1, 9)])                      # the other character's mate stays home
        self.go()
        guest = self.guest()
        there = dict(self.q(self.host_db, "SELECT slot, id FROM squad_mate WHERE charid = ?", (guest["charid"],)))
        self.assertEqual(sorted(there), [1, 3])
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM squad_mate")[0][0], 4)
        ct.run(self.host_db, "UPDATE squad_job SET level = 32 WHERE squad_id = ? AND job = 1", (there[1],))
        self.host_db.commit()
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=time.time(), **self.kw()), "checkpoint")
        saved = pp.unpack(read(co.checkpoint_file(self.kit_home, CHAR), "rb"))["summary"]["squad"]
        self.assertEqual([(m["name"], m["level"]) for m in saved], [("Kasumi", 32), ("Gio", 28)])
        ct.run(self.host_db, "UPDATE squad_job SET level = 34 WHERE squad_id = ? AND job = 1", (there[1],))
        self.host_db.commit()
        result = co.come_home(self.cfg, self.kit_home, CHAR, **self.kw())
        self.assertEqual([(m["name"], m["gained"]) for m in result["changes"]["mates"]], [("Kasumi", 4)])
        self.assertEqual(self.q(self.home, "SELECT m.id, m.name, j.level FROM squad_mate m JOIN squad_job j ON j.squad_id = m.id AND j.job = m.mjob "
                                           "WHERE m.charid = ? ORDER BY m.slot", (CHAR,)), [(home[1], "Kasumi", 34), (home[3], "Gio", 28)])
        self.assertEqual(self.q(self.home, "SELECT name FROM squad_mate WHERE charid = ?", (CHAR + 2,)), [("Stays",)])
        # the host tidied up: only its own two mates are left, with nothing of the visitor's
        self.assertEqual(self.q(self.host_db, "SELECT name FROM squad_mate ORDER BY slot"), [("Momo",), ("Kyo",)])
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM squad_job WHERE squad_id NOT IN (SELECT id FROM squad_mate)")[0][0], 0)
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM squad_equip WHERE squad_id NOT IN (SELECT id FROM squad_mate)")[0][0], 0)
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM squad_unlock")[0][0], 0)
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM char_vars WHERE varname LIKE 'SQUAD%' AND charid <> ?", (CHAR,))[0][0], 0)

    def test_host_sends_everyone_home(self):
        self.go()
        self.assertEqual(self.host.send_everyone_home(), [])
        self.assertEqual(self.guest()["state"], "left")
        self.assertFalse(co.hello(self.invite, post=self.post)["open"])
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), **self.kw()), "home")      # the visitor's launcher fetches it
        self.assertEqual(co.away(self.cfg, self.home_conn), [])
        self.assertEqual(self.host.guests(), [])

    def test_return_by_file(self):
        self.go()
        self.host.send_home(self.guest()["guest_id"])
        self.down = True                                                    # the launchers cannot talk any more
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), **self.kw()), "unreachable")
        result = co.load_return_file(self.cfg, self.kit_home, self.guest()["final_file"], connect=self.home_conn)
        self.assertEqual((result["name"], result["already"]), ("Visitor", False))
        self.assertEqual(co.away(self.cfg, self.home_conn), [])

    # --- trouble on the way there ---
    def test_refused_arrival_unpacks_at_once(self):
        ct.run(self.host_db, "UPDATE chars SET charname = 'Visitor' WHERE charid = ?", (CHAR,))
        self.host_db.commit()
        with self.assertRaises(co.Refused):
            self.go()
        self.assertEqual(co.away(self.cfg, self.home_conn), [])
        self.assertEqual(self.q(self.home, "SELECT accid FROM chars WHERE charid = ?", (CHAR,)), [(ACC,)])
        self.assertEqual(self.host.guests(), [])

    def test_lost_answer_then_retry(self):
        real = self.post

        def deaf(address, port, key_header, body, timeout):
            answer = real(address, port, key_header, body, timeout)
            if len(body) > 2000:                                            # the passport got there, the answer did not come back
                raise OSError("timed out")
            return answer

        with self.assertRaises(co.Unreachable):
            co.start_visit(self.cfg, self.kit_home, self.invite, CHAR, post=deaf, connect=self.home_conn, log=self.logs.append)
        row = self.row()
        self.assertFalse(row["host"].get("arrived"))
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, row, **self.kw()), "not-arrived")
        self.assertTrue(co.can_take_back(row["host"])[0])
        host = co.finish_arrival(self.cfg, self.kit_home, CHAR, **self.kw())
        self.assertTrue(host["arrived"])
        self.assertEqual(len(self.host.guests()), 1)
        self.assertEqual(self.q(self.host_db, "SELECT COUNT(*) FROM chars WHERE charname = 'Visitor'")[0][0], 1)
        with self.assertRaises(co.CoopError):
            co.cancel_visit(self.cfg, self.kit_home, CHAR, connect=self.home_conn)       # too late: it is there

    def test_cancel_when_the_host_never_answers(self):
        real = self.post

        def half(address, port, key_header, body, timeout):
            if len(body) > 2000:
                raise OSError("no route")
            return real(address, port, key_header, body, timeout)

        with self.assertRaises(co.Unreachable):
            co.start_visit(self.cfg, self.kit_home, self.invite, CHAR, post=half, connect=self.home_conn, log=self.logs.append)
        self.assertEqual(len(co.away(self.cfg, self.home_conn)), 1)
        co.cancel_visit(self.cfg, self.kit_home, CHAR, connect=self.home_conn, log=self.logs.append)
        self.assertEqual(co.away(self.cfg, self.home_conn), [])
        self.assertEqual(self.q(self.home, "SELECT accid FROM chars WHERE charid = ?", (CHAR,)), [(ACC,)])

    def test_closed_worlds_and_other_versions(self):
        self.settings["hosting"] = False
        with self.assertRaises(co.Refused) as stop:
            self.go()
        self.assertEqual(stop.exception.code, "closed")
        self.settings["hosting"] = True
        for folder, version in ((self.server, "v0.1.30"), ):
            with open(os.path.join(folder, "VERSION.txt"), "w") as handle:
                handle.write(f"XIRPG server {version}\n")
        mine = os.path.join(self.tmp, "myserver")
        os.makedirs(mine)
        with open(os.path.join(mine, "VERSION.txt"), "w") as handle:
            handle.write("XIRPG server v0.1.29\n")
        with self.assertRaises(co.Refused) as stop:
            co.start_visit({"server_dir": mine}, self.kit_home, self.invite, CHAR, **self.kw())
        self.assertEqual(stop.exception.code, "version")
        self.assertEqual(co.away(self.cfg, self.home_conn), [])

    # --- trouble while away ---
    def test_take_back_after_a_day_out_of_reach(self):
        self.go()
        guest = self.guest()
        now = time.time()
        co.keep_visit(self.cfg, self.kit_home, self.row(), now=now, **self.kw())            # a checkpoint exists
        ct.run(self.host_db, "UPDATE char_stats SET mlvl = 44 WHERE charid = ?", (guest["charid"],))
        self.host_db.commit()
        self.down = True
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 60, **self.kw()), "unreachable")
        self.assertEqual(co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 7200, **self.kw()), "unreachable")
        host = self.row()["host"]
        self.assertEqual(host["unreachable_since"], int(now + 60))           # counted from the first miss
        self.assertFalse(co.can_take_back(host, now + 7200)[0])
        self.assertTrue(co.can_take_back(host, now + 60 + 24 * 3600 + 5)[0])
        result = co.take_back(self.cfg, self.kit_home, CHAR, connect=self.home_conn, log=self.logs.append)
        self.assertTrue(result["from_checkpoint"])
        self.assertEqual(self.q(self.home, "SELECT c.accid, s.mlvl FROM chars c JOIN char_stats s USING (charid) WHERE c.charid = ?", (CHAR,)), [(ACC, 30)])
        self.down = False                                                   # the host comes back: its copy cannot come home any more
        self.host.send_home(guest["guest_id"])
        final = read(self.guest()["final_file"], "rb")
        conn = self.home_conn()
        self.assertTrue(pp.come_home(conn, final)["already"])
        conn.close()
        self.assertEqual(self.q(self.home, "SELECT mlvl FROM char_stats WHERE charid = ?", (CHAR,)), [(30,)])

    def test_coming_back_into_reach_clears_the_clock(self):
        self.go()
        now = time.time()
        self.down = True
        co.keep_visit(self.cfg, self.kit_home, self.row(), now=now, **self.kw())
        self.assertIn("unreachable_since", self.row()["host"])
        self.down = False
        co.keep_visit(self.cfg, self.kit_home, self.row(), now=now + 30, **self.kw())
        self.assertNotIn("unreachable_since", self.row()["host"])

    def test_answer_lost_on_the_way_home(self):
        self.go()
        real = self.post
        calls = []

        def flaky(address, port, key_header, body, timeout):
            answer = real(address, port, key_header, body, timeout)
            calls.append(len(answer))
            if len(calls) == 1:                                             # the passport is made, then the line drops
                raise OSError("reset")
            return answer

        with self.assertRaises(co.Unreachable):
            co.come_home(self.cfg, self.kit_home, CHAR, post=flaky, connect=self.home_conn, log=self.logs.append)
        self.assertEqual(self.guest()["state"], "left")
        self.assertEqual(len(co.away(self.cfg, self.home_conn)), 1)          # still safely "away" at home
        result = co.come_home(self.cfg, self.kit_home, CHAR, post=flaky, connect=self.home_conn, log=self.logs.append)
        self.assertFalse(result["already"])
        self.assertEqual(self.host.guests(), [])
        self.assertEqual(self.q(self.home, "SELECT accid FROM chars WHERE charid = ?", (CHAR,)), [(ACC,)])

    # --- who may ask for what ---
    def test_keys(self):
        with self.assertRaises(co.Refused) as stop:
            co.hello(dict(self.invite, secret="00" * 16), post=self.post)
        self.assertEqual(stop.exception.code, "key")
        host = self.go()
        other = dict(host, guest_id="f" * 24)                               # a made-up visitor
        with self.assertRaises(co.Refused):
            co._guest_call(other, {"op": "status"}, post=self.post)
        wrong = dict(host, gkey="11" * 32)                                  # the right visitor, the wrong key
        with self.assertRaises(co.Refused):
            co._guest_call(wrong, {"op": "go_home"}, post=self.post)
        self.assertEqual(self.guest()["state"], "active")
        with self.assertRaises(co.Refused):                                # a visitor's key is not an invite
            co.call(self.invite, "invite", bytes.fromhex(host["gkey"]), {"op": "hello"}, post=self.post)
        with self.assertRaises(co.Refused) as stop:                        # nothing to confirm before leaving
            co._guest_call(host, {"op": "confirm_home"}, post=self.post)
        self.assertEqual(stop.exception.code, "active")
        self.host.failures.clear()
        for _ in range(21):
            with self.assertRaises(co.Refused):
                co.hello(dict(self.invite, secret="00" * 16), post=self.post)
        with self.assertRaises(co.Refused):                                # now even the right code waits ten minutes
            co.hello(self.invite, post=self.post)

    def test_guest_limit_and_second_visitor(self):
        self.settings["max_guests"] = 1
        self.go()
        ct.make_character(self.home, ACC, CHAR + 5, "Second", linkshell=False)
        with self.assertRaises(co.Refused):
            co.start_visit(self.cfg, self.kit_home, self.invite, CHAR + 5, **self.kw())
        self.assertEqual([r["name"] for r in co.away(self.cfg, self.home_conn)], ["Visitor"])
        self.settings["max_guests"] = 2
        co.start_visit(self.cfg, self.kit_home, self.invite, CHAR + 5, **self.kw())
        self.assertEqual(sorted(g["name"] for g in self.host.guests()), ["Second", "Visitor"])

    # --- over a real socket ---
    def test_real_http(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.settings["port"] = port
        self.host.start()
        invite = dict(self.invite, port=port)
        self.assertEqual(co.hello(invite)["world"]["id"], pp.world_identity(self.host_db)["id"])
        host = co.start_visit(self.cfg, self.kit_home, invite, CHAR, connect=self.home_conn, log=self.logs.append)
        self.assertTrue(host["arrived"])
        with self.assertRaises(co.Refused) as stop:
            co.hello(dict(invite, secret="00" * 16))
        self.assertEqual(stop.exception.code, "key")
        results = co.test_connection(invite)
        self.assertTrue(results[0][1])
        self.assertEqual(len(results), 1 + len(co.GAME_PORTS))
        result = co.come_home(self.cfg, self.kit_home, CHAR, connect=self.home_conn, log=self.logs.append)
        self.assertFalse(result["already"])
        self.host.stop()
        with self.assertRaises(co.Unreachable):
            co.hello(invite, timeout=3)
        self.assertFalse(co.test_connection(invite)[0][1])

    # --- the host's PC ---
    def test_zone_address_follows_hosting(self):
        cols = [r[0] for r in self.q(self.host_db, "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'zone_settings'")]
        self.assertIn("zoneip", cols)
        for zone in (230, 231):
            ct.run(self.host_db, "INSERT INTO zone_settings (zoneid, zoneip, zoneport, name) VALUES (?, '127.0.0.1', 54230, ?)", (zone, f"z{zone}"))
        self.host_db.commit()
        connect = lambda: ct.connect(ct.HOST_DB)
        cfg = {"server_dir": self.server}
        self.settings.update({"address": "192.168.1.20"})
        here = lambda address: address in ("192.168.1.20", "192.168.1.77")
        self.assertTrue(co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect, is_local=here))
        self.assertEqual(co.zone_address(cfg, connect), "192.168.1.20")
        self.assertIn("hosting = true", read(os.path.join(self.server, "modules", "custom", "lua", "coop_config.lua")))
        self.settings["hosting"] = False
        self.assertFalse(co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect))
        self.assertEqual(co.zone_address(cfg, connect), "127.0.0.1")
        self.assertEqual(co.load_settings(self.kit_host)["zoneip_set"], "")
        # hosting again on a network this PC has left: the world stays private this time (the owner must still get in)
        self.settings["hosting"] = True
        self.assertFalse(co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect, is_local=lambda a: False))
        self.assertEqual(co.zone_address(cfg, connect), "127.0.0.1")
        self.assertTrue(any("stays private" in line for line in self.logs))
        self.assertTrue(self.settings["hosting"])                           # the choice is kept for next time
        self.assertTrue(co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect, is_local=here))
        self.settings["hosting"] = False
        co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect, is_local=here)
        self.assertEqual(co.zone_address(cfg, connect), "127.0.0.1")
        self.assertTrue(co.is_local_address("127.0.0.1"))
        self.assertFalse(co.is_local_address("203.0.113.9"))
        # an address somebody set by hand is left alone when hosting was never on
        ct.run(self.host_db, "UPDATE zone_settings SET zoneip = '10.9.9.9'")
        self.host_db.commit()
        co.prepare_world(cfg, self.kit_host, self.settings, log=self.logs.append, connect=connect)
        self.assertEqual(co.zone_address(cfg, connect), "10.9.9.9")
        with self.assertRaises(co.CoopError):
            co.set_zone_address(cfg, "'; DROP TABLE chars; --", connect)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=1)
