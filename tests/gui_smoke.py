"""Run on a graphical Linux session: python3 tests/gui_smoke.py.
All writes are isolated to a temporary test home.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import time
from unittest.mock import patch
from opencare.core import Environment
from opencare.gui import App

with tempfile.TemporaryDirectory(prefix='opencare-ui-test-') as d:
    home = Path(d)
    (home / '.config/autostart').mkdir(parents=True)
    (home / '.config/autostart/demo.desktop').write_text('[Desktop Entry]\nName=Demo\nExec=demo\nType=Application\n')
    (home / '.cache/demo').mkdir(parents=True)
    (home / '.cache/demo/old').write_text('cache')
    import os
    os.utime(home / '.cache/demo/old', (time.time() - 20 * 86400,) * 2)
    app = App(Environment(home=home))
    app.update()
    assert len(app.tabs.tabs()) == 9
    assert app.winfo_width() >= 850
    assert not app.advanced_visible
    assert all(not app.nav[name].winfo_manager() for name in ['Конфигурации', 'Снимки', 'Диск'])
    app.toggle_advanced()
    app.update()
    assert all(app.nav[name].winfo_manager() == 'pack' for name in ['Конфигурации', 'Снимки', 'Диск'])
    app.toggle_advanced()
    app.update()
    reports = []
    app.report = lambda title, text: reports.append((title, text))
    def wait():
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            app.update()
            time.sleep(.02)
        app.update()
        assert not app.busy, 'GUI worker did not finish'
    app.show_guide()
    assert reports[-1][0] == 'Начните с проверки компьютера'
    app.tabs.select(app.frames['Очистка'])
    app.show_guide()
    assert reports[-1][0] == 'Как убрать ненужные файлы'
    app.scan_clean()
    wait()
    assert len(app.clean_items) == 1
    app.clean_tree.selection_set('0')
    with patch('opencare.gui.messagebox.askyesno', return_value=True):
        app.clean_selected()
        wait()
    assert not (home / '.cache/demo/old').exists()
    assert 'Место на том же диске пока не освобождено' in reports[-1][1]
    app.refresh_recovery()
    app.recovery_tree.selection_set('0')
    with patch('opencare.gui.messagebox.askyesno', return_value=True):
        app.restore()
        wait()
    assert (home / '.cache/demo/old').read_text() == 'cache'
    app.recovery_tree.selection_set('0')
    app.recovery_details()
    assert 'Изменение уже отменено' in reports[-1][1]
    app.load_startup()
    wait()
    demo = next(i for i, item in enumerate(app.start_items) if item['name'] == 'Demo')
    app.start_tree.selection_set(str(demo))
    with patch('opencare.gui.messagebox.askyesno', return_value=True):
        app.toggle_startup(False)
        wait()
    assert not next(item for item in app.start_items if item['name'] == 'Demo')['enabled']
    app.load_configs()
    wait()
    assert app.config_items
    app.open_editor(home / '.config/autostart/demo.desktop')
    app.update()
    assert any(child.winfo_class() == 'Toplevel' for child in app.winfo_children())
    for i in app.tabs.tabs():
        app.tabs.select(i)
        app.update()
    app.quick_scan()
    wait()
    result_windows = [child for child in app.winfo_children() if child.winfo_class() == 'Toplevel' and child.title() == 'Проверка завершена — ничего не изменено']
    assert len(result_windows) == 1
    assert (home / '.cache/demo/old').exists(), 'Quick check must not remove anything'
    def find_button(widget, label):
        for child in widget.winfo_children():
            if child.winfo_class() == 'TButton' and child.cget('text') == label:
                return child
            found = find_button(child, label)
            if found is not None:
                return found
    find_button(result_windows[0], 'Посмотреть временные файлы').invoke()
    wait()
    assert app.tabs.select() == str(app.frames['Очистка'])
    assert (home / '.cache/demo/old').exists()
    app.geometry('1100x720')
    app.update()
    assert app.frames['Обзор'].winfo_width() > 700
    app.destroy()
    print('GUI smoke OK: beginner menu, section help, readable recovery, scan → quarantine → restore, startup override, config editor')
