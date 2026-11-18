"""Stand-in tests for 'Add addon or plugin' (launcher_core.install_user_item) and the addon details. Run: python test_user_addons.py"""
import os, shutil, sys, tempfile, unittest, zipfile
KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KIT)
import launcher_core as core


class UserAddonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ashita = os.path.join(self.tmp, "Ashita")
        os.makedirs(os.path.join(self.ashita, "addons")); os.makedirs(os.path.join(self.ashita, "plugins"))
        self.backups = os.path.join(self.tmp, "backups")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def zip_of(self, files):
        path = os.path.join(self.tmp, "x%d.zip" % len(os.listdir(self.tmp)))
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        return path

    def test_github_style_zip_with_one_top_folder(self):
        z = self.zip_of({"cool-main/cool.lua": "addon.name = 'cool'\naddon.version = '1.2'\naddon.author = 'Someone'\naddon.desc = 'Does cool things.'",
                         "cool-main/README.md": "x"})
        # the top folder is not named like the lua file, so it is not an addon by itself...
        with self.assertRaises(RuntimeError):
            core.install_user_item(self.ashita, z, self.backups)
        z = self.zip_of({"Cool-main/cool/cool.lua": "addon.version = '1.2'", "Cool-main/cool/lib/x.lua": "--"})
        self.assertEqual(core.install_user_item(self.ashita, z, self.backups), [("addon", "cool")])
        self.assertTrue(os.path.exists(os.path.join(self.ashita, "addons", "cool", "lib", "x.lua")))

    def test_ashita_layout_zip_with_addons_and_plugins(self):
        z = self.zip_of({"addons/foo/foo.lua": "--", "plugins/Bar.dll": "MZ", "docs/readme.txt": "x"})
        self.assertEqual(sorted(core.install_user_item(self.ashita, z, self.backups)), [("addon", "foo"), ("plugin", "Bar")])

    def test_addon_folder_zip_and_plain_dll_and_folder(self):
        z = self.zip_of({"tracker/tracker.lua": "addon.desc = \"Tracks.\""})
        self.assertEqual(core.install_user_item(self.ashita, z, self.backups), [("addon", "tracker")])
        self.assertEqual(core.addon_info(self.ashita, "tracker")["desc"], "Tracks.")
        dll = os.path.join(self.tmp, "Shiny.dll"); open(dll, "wb").write(b"MZ")
        self.assertEqual(core.install_user_item(self.ashita, dll, self.backups), [("plugin", "Shiny")])
        folder = os.path.join(self.tmp, "src", "mine"); os.makedirs(folder); open(os.path.join(folder, "mine.lua"), "w").write("--")
        self.assertEqual(core.install_user_item(self.ashita, folder, self.backups), [("addon", "mine")])

    def test_replacing_keeps_a_backup(self):
        os.makedirs(os.path.join(self.ashita, "addons", "foo")); open(os.path.join(self.ashita, "addons", "foo", "foo.lua"), "w").write("old")
        core.install_user_item(self.ashita, self.zip_of({"foo/foo.lua": "new"}), self.backups)
        self.assertEqual(open(os.path.join(self.ashita, "addons", "foo", "foo.lua")).read(), "new")
        saved = os.listdir(self.backups)
        self.assertEqual(len(saved), 1)
        self.assertEqual(open(os.path.join(self.backups, saved[0], "foo.lua")).read(), "old")

    def test_bad_zip_and_nothing_found(self):
        with self.assertRaises(RuntimeError):
            core.install_user_item(self.ashita, self.zip_of({"../evil.lua": "x"}), self.backups)
        with self.assertRaises(RuntimeError):
            core.install_user_item(self.ashita, self.zip_of({"notes.txt": "x"}), self.backups)

    def test_origin_labels(self):
        self.assertEqual(core.item_origin("addon", "Gambits"), "XIRPG")
        self.assertEqual(core.item_origin("addon", "xiui", ["xiui"]), "download")
        self.assertEqual(core.item_origin("addon", "cool", ["xiui"], ["cool"]), "added by you")
        self.assertEqual(core.item_origin("addon", "fps"), "Ashita")


if __name__ == "__main__":
    unittest.main(verbosity=1)
