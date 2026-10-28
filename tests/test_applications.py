import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from opencare import applications as a, core as c


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = c.Environment(home=self.home)
        self.system = self.home / 'system'
        self.user = self.home / 'user'
        self.system.mkdir()
        self.user.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def desktop(self, name, fields='', root=None):
        p = (root or self.system) / name
        p.write_text('[Desktop Entry]\nType=Application\nName=OBS Studio\nExec=obs\nIcon=com.obsproject.Studio\n'+fields)
        return p

    def test_inventory_is_apps_not_packages(self):
        p = self.desktop('obs.desktop', 'Name[ru]=OBS Studio\n')
        packages = [c.Package('apt', 'obs-studio', '1'), c.Package('apt', 'acl', '1'), c.Package('apt', 'accountsservice', '1')]
        import subprocess
        output = subprocess.CompletedProcess([], 0, f'obs-studio: {p}\n', '')
        with patch.object(a.subprocess, 'run', return_value=output), patch.object(a.shutil, 'which', return_value='dpkg-query'):
            apps, errors = a.inventory(self.env, [self.system], packages)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].name, 'OBS Studio')
        self.assertEqual(apps[0].package.name, 'obs-studio')
        self.assertEqual(apps[0].icon, 'com.obsproject.Studio')
        self.assertEqual(errors, [])

    def test_missing_launchers_never_fall_back_to_packages(self):
        apps, errors = a.inventory(self.env, [self.system], [c.Package('apt', 'acl', '1')])
        self.assertEqual(apps, [])

    def test_no_display_terminal_and_hidden_are_excluded(self):
        self.desktop('hidden.desktop', 'Hidden=true\n')
        self.desktop('internal.desktop', 'NoDisplay=true\n')
        self.desktop('terminal.desktop', 'Terminal=true\n')
        self.assertEqual(a.inventory(self.env, [self.system], [])[0], [])

    def test_user_hidden_entry_overrides_system(self):
        self.desktop('app.desktop')
        self.desktop('app.desktop', 'Hidden=true\n', self.user)
        self.assertEqual(a.inventory(self.env, [self.system, self.user], [])[0], [])

    def test_flatpak_identity_has_correct_scope(self):
        root = self.env.data / 'applications'
        root.mkdir(parents=True)
        self.desktop('studio.desktop', 'X-Flatpak=com.obsproject.Studio\n', root)
        pkg = c.Package('flatpak-user', 'com.obsproject.Studio', '1')
        apps, _ = a.inventory(self.env, [root], [pkg])
        self.assertEqual(apps[0].package, pkg)

    def test_local_app_visible_but_no_guessed_uninstall(self):
        self.desktop('manual.desktop')
        with patch.object(a.shutil, 'which', return_value=None):
            apps, _ = a.inventory(self.env, [self.system], [])
        self.assertEqual(len(apps), 1)
        self.assertIsNone(apps[0].package)
        self.assertTrue(a.protected_reason(apps[0]))

    def test_desktop_component_is_protected(self):
        app = a.Application('Файлы', 'nemo', 'nemo.desktop', c.Package('apt', 'nemo', '1'))
        self.assertTrue(a.protected_reason(app))
        app.package = c.Package('apt', 'obs-studio', '1')
        self.assertEqual(a.protected_reason(app), '')
