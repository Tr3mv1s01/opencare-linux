import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from opencare import core as c


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = c.Environment(home=self.home)
        self.journal = c.Journal(self.env)

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, data=b'contents', old=False):
        p = self.home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if old:
            os.utime(p, (time.time() - 20 * 86400,) * 2)
        return p

    def test_scan_age_category_and_exclusions(self):
        old = self.file('.cache/app/old', old=True)
        self.file('.cache/app/new')
        self.file('Documents/keep', old=True)
        self.file('.local/share/Trash/files/t', old=True)
        (self.home / '.cache/link').symlink_to(self.home / 'Documents', target_is_directory=True)
        files, errors = c.Cleaner(self.env).scan()
        self.assertEqual([x.path for x in files], [str(old)])
        self.assertEqual(errors, [])

    def test_clean_restore_exact_bytes_and_mode(self):
        p = self.file('.cache/app/old', b'\x00\xffdata', old=True)
        os.chmod(p, 0o640)
        r = self.journal.quarantine([c.candidate(p)])
        self.assertFalse(p.exists())
        self.assertEqual(self.journal.restore(r['id']), [])
        self.assertEqual(p.read_bytes(), b'\x00\xffdata')
        self.assertEqual(p.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.journal.restore(r['id']), [])

    def test_stale_scan_is_not_moved(self):
        p = self.file('.cache/a')
        item = c.candidate(p)
        p.write_text('changed')
        r = self.journal.quarantine([item])
        self.assertEqual(p.read_text(), 'changed')
        self.assertTrue(r['errors'])

    def test_restore_conflict_preserves_new_file(self):
        p = self.file('.cache/a')
        r = self.journal.quarantine([c.candidate(p)])
        p.write_text('new')
        self.assertTrue(self.journal.restore(r['id']))
        self.assertEqual(p.read_text(), 'new')

    def test_edit_restore_and_external_conflict(self):
        p = self.file('.config/app.ini', b'old')
        r = self.journal.write(p, b'new')
        p.write_bytes(b'external')
        self.assertTrue(self.journal.restore(r['id']))
        self.assertEqual(p.read_bytes(), b'external')
        p.write_bytes(b'new')
        self.assertEqual(self.journal.restore(r['id']), [])
        self.assertEqual(p.read_bytes(), b'old')

    def test_new_file_restore_removes_override(self):
        p = self.home / '.config/autostart/test.desktop'
        r = self.journal.write(p, b'override')
        self.assertEqual(self.journal.restore(r['id']), [])
        self.assertFalse(p.exists())

    def test_symlink_and_outside_write_rejected(self):
        p = self.file('real/a')
        (self.home / 'linked').symlink_to(p.parent, target_is_directory=True)
        for path in [self.home / 'linked/a', self.home.parent / 'outside', self.env.state / 'test', self.home / '..' / 'escape']:
            with self.assertRaises(c.CareError):
                self.env.writable_file(path)

    def test_startup_system_override_and_rollback(self):
        system = self.home / 'system-autostart'
        system.mkdir()
        original = '[Desktop Entry]\nType=Application\nName=Demo\nExec=demo --arg %U\n'
        (system / 'demo.desktop').write_text(original)
        manager = c.Startup(self.env, [system])
        item = manager.list()[0]
        self.assertTrue(item['enabled'])
        r = manager.toggle(item, False)
        self.assertFalse(manager.list()[0]['enabled'])
        self.assertEqual((system / 'demo.desktop').read_text(), original)
        self.journal.restore(r['id'])
        self.assertTrue(manager.list()[0]['enabled'])

    def test_snapshot_add_remove_modify(self):
        p = self.file('.config/a', b'old')
        removed = self.file('.config/remove')
        a = c.snapshot(self.env, self.env.config, 'before')
        p.write_bytes(b'new')
        removed.unlink()
        self.file('.config/add')
        b = c.snapshot(self.env, self.env.config, 'after')
        self.assertEqual(c.compare_snapshots(a, b), [('Изменён', 'a'), ('Добавлен', 'add'), ('Удалён', 'remove')])
        b['root'] = 'different'
        with self.assertRaises(c.CareError):
            c.compare_snapshots(a, b)

    def test_duplicates_use_content_not_size(self):
        a = self.file('Documents/a', b'ABC')
        b = self.file('Documents/b', b'ABC')
        self.file('Documents/c', b'XYZ')
        files, dupes, errors = c.disk_scan(self.env, self.home / 'Documents', True)
        self.assertEqual(len(files), 3)
        self.assertEqual(dupes, [(3, [str(a), str(b)])])
        self.assertEqual(errors, [])

    def test_privacy_preserves_passwords_bookmarks(self):
        history = self.file('.config/chromium/Default/History', old=True)
        self.file('.config/chromium/Default/Login Data', old=True)
        self.file('.config/chromium/Default/Bookmarks', old=True)
        self.file('.mozilla/firefox/profile/places.sqlite', old=True)
        items, errors = c.Cleaner(self.env).scan(['privacy'], 0)
        self.assertEqual([x.path for x in items], [str(history)])

    def test_active_history_is_skipped(self):
        self.file('.config/chromium/Default/History', old=True)
        self.file('.config/chromium/Default/History-wal')
        items, errors = c.Cleaner(self.env).scan(['privacy'], 0)
        self.assertEqual(items, [])
        self.assertTrue(errors)

    def test_uninstall_no_shell_and_invalid_option(self):
        self.assertEqual(c.uninstall_command(c.Package('apt', 'demo:amd64', '1')), ['sudo', 'apt-get', 'remove', '--', 'demo:amd64'])
        for name in ['--help', 'abc;rm', 'a b', '$(id)']:
            with self.assertRaises(c.CareError):
                c.uninstall_command(c.Package('apt', name, '1'))

    def test_remnants_name_is_only_suggestion(self):
        p = self.file('.config/demo/settings')
        self.assertEqual(c.remnants(self.env, 'demo'), [str(p.parent)])
        with self.assertRaises(c.CareError):
            c.remnants(self.env, 'a')

    def test_package_inventory_parse(self):
        with patch.object(c.shutil, 'which', side_effect=lambda n: n if n == 'dpkg-query' else None), patch.object(c, 'run', return_value='ii \tdemo\t1.0\tDemo package\nrc \told\t0.1\tRemoved\n'):
            packages, errors = c.packages()
        self.assertEqual([p.name for p in packages], ['demo'])
        self.assertEqual(errors, [])

    def test_cinnamon_uses_its_own_settings(self):
        def run(argv):
            if argv[1] == 'list-schemas':
                return '\n'.join({x[1] for x in c.SETTINGS})
            if argv[1] == 'list-keys':
                return '\n'.join(x[2] for x in c.SETTINGS if x[1] == argv[2])
            return 'true\n'
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'X-Cinnamon', 'XDG_SESSION_DESKTOP': 'cinnamon'}), patch.object(c, 'run', side_effect=run), patch.object(c.shutil, 'which', return_value='/usr/bin/gsettings'):
            settings = c.available_settings()
        self.assertEqual(len(settings), 7)
        self.assertTrue(all(x[1].startswith(('org.cinnamon', 'org.nemo')) for x in settings))

    def test_unsupported_desktop_has_no_misleading_settings(self):
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_SESSION_DESKTOP': 'plasma'}), patch.object(c.shutil, 'which', return_value='/usr/bin/gsettings'):
            self.assertEqual(c.available_settings(), [])

    def test_dconf_failure_is_not_success(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, '', 'dconf-WARNING: failed to commit changes')
        with patch.object(c.subprocess, 'run', return_value=result):
            with self.assertRaises(c.CareError):
                c.run(['gsettings', 'set', 'schema', 'key', 'true'])

    def test_setting_roundtrip(self):
        values = {'value': 'true'}
        def run(argv):
            if argv[1] == 'get':
                return values['value'] + '\n'
            values['value'] = argv[-1]
            return ''
        with patch.object(c, 'run', side_effect=run), patch.object(c, 'available_settings', return_value=[c.GNOME_SETTINGS[2]]):
            record = c.set_setting(self.env, 'org.gnome.desktop.interface', 'enable-animations', 'false')
            self.assertEqual(values['value'], 'false')
            c.restore_setting(self.env, record)
            self.assertEqual(values['value'], 'true')


if __name__ == '__main__':
    unittest.main()
