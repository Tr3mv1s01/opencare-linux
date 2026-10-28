"""Read-only integration against the current computer, using actual GUI workers."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opencare.core import Environment, desktop_info
from opencare.gui import App
with tempfile.TemporaryDirectory(prefix='opencare-host-ui-') as temp:
    errors = []
    with patch('opencare.gui.messagebox.showerror', side_effect=lambda *a, **kw: errors.append(str(a))):
        app = App(Environment(state=Path(temp) / 'state'))
        def wait():
            deadline = time.monotonic() + 60
            while app.busy and time.monotonic() < deadline:
                app.update()
                time.sleep(.02)
            app.update()
            assert not app.busy, 'Timed out'
            assert not errors, errors
        app.update()
        result = {'system': desktop_info(), 'gui': {}}
        for page, attribute in [('Программы', 'pkg_visible'), ('Автозагрузка', 'start_items'), ('Настройки', 'setting_items')]:
            app.select_page(page)
            wait()
            result['gui'][page] = len(getattr(app, attribute))
        result['gui']['Настоящие значки приложений'] = len(app.app_icons.loaded)
        assert len(app.app_icons.loaded) > 0
        assert [str(value) for value in app.tk.splitlist(app.pkg_tree.cget('show'))] == ['tree']
        for index, item in enumerate(app.pkg_visible):
            assert app.pkg_tree.item(str(index), 'text').strip() == item.name
            assert app.pkg_tree.item(str(index), 'image')
        assert all(isinstance(item.name, str) and item.icon is not None for item in app.pkg_items)
        assert not any(item.name.lower() in {'acl', 'accountsservice', 'adduser', 'libc6'} for item in app.pkg_items)
        result['gui']['Знакомые приложения'] = [item.name for item in app.pkg_items if any(name in item.name.lower() for name in ['obs studio', 'telegram', 'firefox', 'visual studio'])]
        assert all(item[1].startswith(('org.cinnamon', 'org.nemo')) for item in app.setting_items)
        app.select_page('Очистка')
        app.scan_clean()
        wait()
        result['gui']['Очистка: файлов без удаления'] = len(app.clean_items)
        app.select_page('Конфигурации')
        app.load_configs()
        wait()
        result['gui']['Конфигурации'] = len(app.config_items)
        app.select_page('Обзор')
        app.geometry('1100x720')
        app.update()
        assert app.stat_labels['desktop'][0].cget('text') == 'Cinnamon'
        assert app.frames['Обзор'].winfo_width() >= 750
        app.destroy()
    print(json.dumps(result, ensure_ascii=False, indent=2))
