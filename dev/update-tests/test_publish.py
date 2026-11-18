"""Stand-in tests for launcher_publish.py: no GitHub, no git pushes. Run: python test_publish.py"""
import os, sys, tempfile, unittest
KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KIT)
import launcher_publish as lp


class Done:
    def __init__(self, out="", code=0):
        self.stdout, self.returncode, self.stderr = out, code, ""


class PublishTests(unittest.TestCase):
    def test_next_version(self):
        self.assertEqual(lp.next_version("v0.1.9"), "v0.1.10")
        self.assertEqual(lp.next_version(None), "v0.0.1")

    def test_release_is_draft_until_every_file_is_up(self):
        calls = []

        def opener(method, url, token, data=None, body=None, content_type=None, length=None):
            calls.append((method, url.split("/repos/")[1], (data or {}).get("draft")))
            return {"id": 7}
        tmp = tempfile.mkdtemp()
        files = []
        for name in ("XIRPG.zip", "SHA256SUMS.txt"):
            path = os.path.join(tmp, name); open(path, "wb").write(b"x"); files.append(path)
        lp.make_release("me/repo", "v1.0.0", "t", "n", True, files, "tok", log=lambda m: None, opener=opener)
        self.assertEqual(calls[0], ("POST", "me/repo/releases", True))
        self.assertIn("assets?name=XIRPG.zip", calls[1][1])      # spaces become dots, like GitHub's own uploads
        self.assertEqual(calls[-1], ("PATCH", "me/repo/releases/7", False))

    def test_token_from_git(self):
        run = lambda cmd, **kw: Done("protocol=https\nhost=github.com\nusername=Hurami89\npassword=gho_abc\n")
        self.assertEqual(lp.github_token(run), "gho_abc")
        with self.assertRaises(RuntimeError):
            lp.github_token(lambda cmd, **kw: Done("", 1))


if __name__ == "__main__":
    unittest.main(verbosity=1)
