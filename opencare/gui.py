"""Native Tk desktop interface, no browser server or network dependencies."""
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from . import core as c
from . import __display_version__
from . import applications as apps
from .icons import AppIcons
from .helptext import LABELS, ADVANCED, STEPS, STATUS, explain_error


class App(tk.Tk):
    def __init__(self, env=None):
        super().__init__()
        self.env = env or c.Environment()
        self.title(f'OpenCare {__display_version__} — помощь с Linux')
        self.geometry('1280x840')
        self.minsize(1100, 720)
        self.configure(bg='#f3f6fb')
        self.jobs = queue.Queue()
        self.busy = False
        self.setup_theme()
        shell = tk.Frame(self, bg='#f3f6fb')
        shell.pack(fill='both', expand=True)
        side = tk.Frame(shell, bg='#111d30', width=228)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        tk.Label(side, text='◈  OpenCare', bg='#111d30', fg='white', font=('Sans', 21, 'bold')).pack(anchor='w', padx=24, pady=(30, 3))
        tk.Label(side, text='ПОРЯДОК НА КОМПЬЮТЕРЕ', bg='#111d30', fg='#8395af', font=('Sans', 9, 'bold')).pack(anchor='w', padx=27, pady=(0, 30))
        tk.Label(side, text='ИНСТРУМЕНТЫ', bg='#111d30', fg='#6e819e', font=('Sans', 9, 'bold')).pack(anchor='w', padx=27, pady=(0, 12))
        names = ['Обзор', 'Очистка', 'Программы', 'Автозагрузка', 'Конфигурации', 'Снимки', 'Диск', 'Настройки', 'Восстановление']
        icons = ['◫', '✦', '▦', '↗', '≡', '▣', '◉', '⚙', '↶']
        self.nav = {}
        for name, icon in sorted(zip(names, icons), key=lambda pair: pair[0] in ADVANCED):
            button = tk.Button(side, text=f'{icon}   {LABELS[name]}', anchor='w', font=('Sans', 10),
                               bg='#111d30', fg='#b7c5da', activebackground='#253e61', activeforeground='white',
                               bd=0, relief='flat', padx=18, pady=11, cursor='hand2', highlightthickness=0,
                               command=lambda n=name: self.select_page(n))
            if name not in ADVANCED:
                button.pack(fill='x', padx=14, pady=2)
            self.nav[name] = button
        self.advanced_visible = False
        self.advanced_button = tk.Button(side, text='＋ Дополнительно', anchor='w', bg='#111d30', fg='#9db2d0', bd=0, padx=18, pady=10, cursor='hand2', command=self.toggle_advanced)
        self.advanced_button.pack(fill='x', padx=14, pady=(14, 0))
        info = c.desktop_info()
        footer = tk.Frame(side, bg='#1b2b42')
        footer.pack(side='bottom', fill='x', padx=16, pady=20)
        tk.Label(footer, text='●  '+info['desktop'], bg='#1b2b42', fg='#79deb7', anchor='w', font=('Sans', 11, 'bold'), padx=14, pady=12).pack(fill='x')
        tk.Label(footer, text='Локально · без подписки\n'+__display_version__, bg='#1b2b42', fg='#a3b3ca', anchor='w', justify='left', padx=14, pady=8).pack(fill='x')
        main = ttk.Frame(shell, padding=(28, 0, 28, 0))
        main.pack(side='left', fill='both', expand=True)
        header = ttk.Frame(main, padding=(0, 25, 0, 20))
        header.pack(fill='x')
        titlebox = ttk.Frame(header)
        titlebox.pack(side='left')
        self.page_title = tk.StringVar(value='Начнём с простого')
        self.page_subtitle = tk.StringVar(value='Обзор системы и быстрый доступ к инструментам')
        ttk.Label(titlebox, textvariable=self.page_title, style='Title.TLabel').pack(anchor='w')
        ttk.Label(titlebox, textvariable=self.page_subtitle, style='Muted.TLabel').pack(anchor='w', pady=(6, 0))
        ttk.Button(header, text='Как пользоваться?', command=self.show_guide).pack(side='right')
        self.tabs = ttk.Notebook(main, style='Pages.TNotebook')
        self.tabs.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Готово к работе. Выбери инструмент в меню слева.')
        self.progress = ttk.Progressbar(main, mode='indeterminate', style='Thin.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(12, 0))
        ttk.Label(main, textvariable=self.status, style='Muted.TLabel', padding=(0, 12)).pack(fill='x')
        self.frames = {}
        for name in names:
            f = ttk.Frame(self.tabs, padding=(0, 0, 0, 0))
            self.tabs.add(f, text=name)
            self.frames[name] = f
        self.nav['Обзор'].configure(bg='#2463eb', fg='white')
        self.overview()
        self.cleaner()
        self.programs()
        self.startup()
        self.configs()
        self.snapshots()
        self.disk()
        self.settings()
        self.recovery()
        self.after(100, self.poll)

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        for name in self.nav:
            if name in ADVANCED:
                if self.advanced_visible:
                    self.nav[name].pack(fill='x', padx=14, pady=2, before=self.advanced_button)
                else:
                    self.nav[name].pack_forget()
        self.advanced_button.configure(text='− Скрыть дополнительные' if self.advanced_visible else '＋ Дополнительно')
        current = self.tabs.tab(self.tabs.select(), 'text')
        if not self.advanced_visible and current in ADVANCED:
            self.select_page('Обзор')

    def show_guide(self):
        current = self.tabs.tab(self.tabs.select(), 'text')
        title, text = STEPS[current]
        self.report(title, text)

    def setup_theme(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        self.option_add('*Font', ('Sans', 10))
        self.option_add('*Text.background', '#ffffff')
        self.option_add('*Text.foreground', '#26354b')
        self.option_add('*Text.insertBackground', '#2463eb')
        self.option_add('*Text.selectBackground', '#dbe8ff')
        self.option_add('*Text.relief', 'flat')
        self.option_add('*Text.highlightThickness', 0)
        style.configure('.', background='#f3f6fb', foreground='#23344d', font=('Sans', 10))
        style.configure('TFrame', background='#f3f6fb')
        style.configure('TLabel', background='#f3f6fb')
        style.configure('Muted.TLabel', foreground='#6b7c93', font=('Sans', 10))
        style.configure('Title.TLabel', font=('Sans', 23, 'bold'), foreground='#14253e')
        style.configure('Badge.TLabel', background='#e4ecf8', foreground='#3a5680', font=('Sans', 10, 'bold'))
        style.configure('TButton', padding=(15, 10), background='#ffffff', foreground='#29415f', borderwidth=0, font=('Sans', 10, 'bold'))
        style.map('TButton', background=[('active', '#e2eafb'), ('disabled', '#edf1f7')], foreground=[('disabled', '#a4b0c1')])
        style.configure('Primary.TButton', background='#2463eb', foreground='white')
        style.map('Primary.TButton', background=[('active', '#184dcc'), ('disabled', '#aec4ef')], foreground=[('disabled', '#f5f8ff')])
        style.configure('TEntry', fieldbackground='white', padding=10, bordercolor='#dce4f0', lightcolor='#dce4f0', darkcolor='#dce4f0')
        style.configure('TSpinbox', fieldbackground='white', padding=7, bordercolor='#dce4f0')
        style.configure('TCheckbutton', background='#f3f6fb', padding=(0, 5), foreground='#425671')
        style.map('TCheckbutton', background=[('active', '#f3f6fb')])
        style.configure('Treeview', background='white', fieldbackground='white', foreground='#34465f', rowheight=38, borderwidth=0, font=('Sans', 10))
        style.configure('Treeview.Heading', background='#e9eff8', foreground='#63748d', relief='flat', padding=(10, 12), font=('Sans', 9, 'bold'))
        style.map('Treeview', background=[('selected', '#deebff')], foreground=[('selected', '#174db5')])
        style.configure('Vertical.TScrollbar', background='#ccd7e6', troughcolor='#f3f6fb', borderwidth=0, arrowsize=12)
        style.configure('Horizontal.TScrollbar', background='#ccd7e6', troughcolor='#f3f6fb', borderwidth=0, arrowsize=12)
        style.layout('Pages.TNotebook.Tab', [])
        style.configure('Pages.TNotebook', background='#f3f6fb', borderwidth=0, tabmargins=0)
        style.configure('Thin.Horizontal.TProgressbar', background='#2463eb', troughcolor='#e6edf7', borderwidth=0, thickness=3)

    def select_page(self, name):
        self.tabs.select(self.frames[name])
        for key, button in self.nav.items():
            button.configure(bg='#2463eb' if key == name else '#111d30', fg='white' if key == name else '#b7c5da')
        self.page_title.set('Начнём с простого' if name == 'Обзор' else LABELS[name])
        descriptions = {
            'Обзор': 'Обзор системы и быстрый доступ к инструментам',
            'Очистка': 'Посмотри, что занимает место. Выбери, что убрать.',
            'Программы': 'Установленные приложения и поиск оставшихся файлов',
            'Автозагрузка': 'Управляй приложениями, которые запускаются вместе с системой',
            'Конфигурации': 'Настройки приложений с резервной копией перед изменением',
            'Снимки': 'Сравни состояние файлов до и после изменений',
            'Диск': 'Найди большие файлы и одинаковые копии',
            'Настройки': 'Параметры именно твоего рабочего стола: '+c.desktop_info()['desktop'],
            'Восстановление': 'История действий и возврат к предыдущему состоянию',
        }
        self.page_subtitle.set(descriptions[name])
        if name in ADVANCED and not self.advanced_visible:
            self.toggle_advanced()
        if not self.busy:
            loaders = {'Программы': self.load_packages, 'Автозагрузка': self.load_startup,
                       'Настройки': self.load_settings, 'Восстановление': self.refresh_recovery, 'Снимки': self.load_snapshots}
            if name in loaders:
                loaders[name]()

    def task(self, title, work, done):
        if self.busy:
            messagebox.showinfo('Выполняется операция', 'Дождитесь завершения текущей операции.')
            return
        self.busy = True
        self.progress.start(12)
        self.status.set(title + '…')
        def worker():
            try:
                self.jobs.put((done, work(), None))
            except Exception as e:
                self.jobs.put((done, None, e))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            done, result, error = self.jobs.get_nowait()
            self.busy = False
            self.progress.stop()
            if error:
                self.status.set('Операция не выполнена')
                self.report('Не получилось завершить действие', explain_error(error)+'\n\nЧто сообщает система:\n'+str(error))
            else:
                self.status.set('Готово. Подсказка для этого раздела — кнопка «Как пользоваться?» вверху.')
                try:
                    done(result)
                except Exception as e:
                    messagebox.showerror('OpenCare', str(e))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def buttons(self, parent, actions, primary=True):
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=(0, 10))
        for index, (label, fn) in enumerate(actions):
            ttk.Button(bar, text=label, command=fn, style='Primary.TButton' if index == 0 and primary else 'TButton').pack(side='left', padx=(0, 6))
        return bar

    def note(self, parent, text):
        label = ttk.Label(parent, text=text, wraplength=740, justify='left', foreground='#6b7c93')
        label.pack(anchor='w', pady=(0, 16))
        parent.bind('<Configure>', lambda event: label.configure(wraplength=max(300, event.width - 10)), add='+')

    def table(self, parent, cols, widths=None):
        box = ttk.Frame(parent)
        box.pack(fill='both', expand=True)
        tree = ttk.Treeview(box, columns=[str(i) for i in range(len(cols))], show='headings', selectmode='extended')
        for i, label in enumerate(cols):
            tree.heading(str(i), text=label)
            tree.column(str(i), width=(widths or [180] * len(cols))[i], minwidth=60)
        y = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
        x = ttk.Scrollbar(box, orient='horizontal', command=tree.xview)
        tree.tag_configure('even', background='#f7f9fd')
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky='nsew')
        y.grid(row=0, column=1, sticky='ns')
        x.grid(row=1, column=0, sticky='ew')
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        return tree

    def fill(self, tree, rows):
        tree.delete(*tree.get_children())
        for i, row in enumerate(rows):
            tree.insert('', 'end', iid=str(i), values=row, tags=('even',) if i % 2 else ())

    def require_one(self, items):
        if len(items) != 1:
            messagebox.showinfo('Выберите одну строку', 'Щёлкните одну строку в списке, затем повторите действие. Для нескольких строк удерживайте Ctrl, но это действие выполняется по одной записи.')
            return False
        return True

    def selected(self, tree, items):
        return [items[int(i)] for i in tree.selection()]

    def report(self, title, text):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry('850x520')
        body = ttk.Frame(win)
        body.pack(fill='both', expand=True)
        txt = tk.Text(body, wrap='word', padx=20, pady=18)
        scroll = ttk.Scrollbar(body, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        txt.pack(side='left', fill='both', expand=True)
        txt.configure(font=('Sans', 12), spacing1=5, spacing3=8)
        txt.insert('1.0', text)
        txt.configure(state='disabled')
        ttk.Button(win, text='Закрыть', command=win.destroy).pack(pady=8)

    def overview(self):
        f = self.frames['Обзор']
        hero = tk.Frame(f, bg='#2463eb', padx=26, pady=22)
        hero.pack(fill='x', pady=(0, 20))
        tk.Label(hero, text='Больше порядка. Меньше лишнего.', font=('Sans', 22, 'bold'), bg='#2463eb', fg='white').pack(anchor='w')
        tk.Label(hero, text='Проверь кэш и автозагрузку — затем реши, что изменить.', font=('Sans', 11), bg='#2463eb', fg='#d5e4ff').pack(anchor='w', pady=(9, 16))
        tk.Button(hero, text='Проверить компьютер   →', command=self.quick_scan, bg='white', fg='#2157bb', activebackground='#e4edff', bd=0, padx=18, pady=10, font=('Sans', 11, 'bold'), cursor='hand2').pack(anchor='w')
        cards = tk.Frame(f, bg='#f3f6fb')
        cards.pack(fill='x', pady=(0, 22))
        self.stat_labels = {}
        for i, (key, title) in enumerate([('disk', 'СВОБОДНО НА ДИСКЕ'), ('desktop', 'РАБОЧИЙ СТОЛ'), ('journal', 'СОХРАНЁННЫХ ДЕЙСТВИЙ')]):
            box = tk.Frame(cards, bg='white', padx=20, pady=18)
            box.grid(row=0, column=i, sticky='nsew', padx=(0, 14 if i < 2 else 0))
            cards.columnconfigure(i, weight=1, uniform='cards')
            tk.Label(box, text=title, font=('Sans', 9, 'bold'), fg='#7b8da5', bg='white').pack(anchor='w')
            value = tk.Label(box, text='—', font=('Sans', 24, 'bold'), fg='#172d4d', bg='white')
            value.pack(anchor='w', pady=(9, 0))
            sub = tk.Label(box, text='', fg='#73839a', bg='white', font=('Sans', 9))
            sub.pack(anchor='w', pady=(6, 0))
            self.stat_labels[key] = (value, sub)
        ttk.Label(f, text='Что хотите сделать?', font=('Sans', 15, 'bold')).pack(anchor='w', pady=(0, 12))
        quick = tk.Frame(f, bg='#f3f6fb')
        quick.pack(fill='x')
        for i, (title, subtitle, target) in enumerate([
            ('✦  Освободить место', 'Кэш, корзина и временные данные', 'Очистка'),
            ('↗  Настроить запуск', 'Приложения в автозагрузке', 'Автозагрузка'),
            ('⚙  Настроить рабочий стол', 'Параметры '+c.desktop_info()['desktop'], 'Настройки')]):
            box = tk.Frame(quick, bg='white', padx=18, pady=15)
            box.grid(row=i, column=0, sticky='ew', pady=(0, 9))
            quick.columnconfigure(0, weight=1)
            tk.Label(box, text=title, font=('Sans', 12, 'bold'), bg='white', fg='#2d4565').pack(side='left')
            tk.Label(box, text=subtitle, bg='white', fg='#7b8da5', font=('Sans', 10)).pack(side='left', padx=18)
            tk.Button(box, text='Открыть  →', bg='#eaf1ff', fg='#2463eb', bd=0, padx=14, pady=7, cursor='hand2', command=lambda n=target: self.select_page(n)).pack(side='right')
        self.overview_caption = tk.StringVar()
        ttk.Label(f, textvariable=self.overview_caption, style='Muted.TLabel', wraplength=870).pack(anchor='w', pady=(14, 6))
        self.refresh_overview()

    def refresh_overview(self):
        s = c.summary(self.env)
        info = c.desktop_info()
        self.stat_labels['disk'][0].configure(text=c.human(s['disk_free']))
        self.stat_labels['disk'][1].configure(text='из '+c.human(s['disk_total']))
        self.stat_labels['desktop'][0].configure(text=info['desktop'])
        self.stat_labels['desktop'][1].configure(text=info['distro'])
        self.stat_labels['journal'][0].configure(text=str(s['journal_operations']))
        self.stat_labels['journal'][1].configure(text='можно посмотреть и отменить')
        self.overview_caption.set('● Работает локально. Изменения — после твоего подтверждения. Убранные файлы можно вернуть в разделе «Вернуть изменения».')

    def quick_scan(self):
        def work():
            files, errors = c.Cleaner(self.env).scan()
            startup = c.Startup(self.env).list()
            return files, startup, errors
        def done(result):
            files, startup, errors = result
            win = tk.Toplevel(self)
            win.title('Проверка завершена — ничего не изменено')
            win.geometry('720x470')
            frame = ttk.Frame(win, padding=24)
            frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='Проверка завершена', font=('Sans', 19, 'bold')).pack(anchor='w')
            self.note(frame, f'Ничего не удалено и не отключено.\n\nНайдено временных файлов старше недели: {len(files)} ({c.human(sum(x.size for x in files))}).\nПрограмм и компонентов при входе в Linux: {len(startup)}. Это не означает, что все они лишние.\n\nВыберите, что хотите посмотреть. Сначала OpenCare покажет список; изменения потребуют подтверждения.')
            def go(page):
                win.destroy()
                self.select_page(page)
                if page == 'Очистка' and not self.busy:
                    self.scan_clean()
            self.buttons(frame, [('Посмотреть временные файлы', lambda: go('Очистка'))])
            self.buttons(frame, [('Посмотреть запуск программ', lambda: go('Автозагрузка'))])
            if errors:
                ttk.Button(frame, text='Что не удалось проверить', command=lambda: self.report('Не всё проверено', '\n'.join(errors))).pack(anchor='w')
            ttk.Button(frame, text='Закрыть без изменений', command=win.destroy).pack(anchor='w', pady=12)
        self.task('Проверка компьютера без изменений', work, done)

    def cleaner(self):
        f = self.frames['Очистка']
        self.note(f, 'Сначала найдите файлы — это ничего не удаляет. Затем выберите строки и уберите их с возможностью возврата. Файлы останутся в хранилище OpenCare до удаления копий. Подробнее — «Как пользоваться?» вверху.')
        bar = self.buttons(f, [('1. Найти файлы', self.scan_clean), ('2. Убрать выбранные', self.clean_selected), ('Выбрать всё', lambda: self.clean_tree.selection_set(self.clean_tree.get_children()))])
        self.clean_flags = {}
        for key, label, default in [('cache', 'Временные данные приложений (кэш) — начните с этого', True), ('trash', 'Файлы, которые уже находятся в корзине Linux', False), ('privacy', 'История Chrome / Chromium и список недавних документов — закройте браузер', False)]:
            var = tk.BooleanVar(value=default)
            self.clean_flags[key] = var
            ttk.Checkbutton(f, text=label, variable=var).pack(anchor='w')
        row = ttk.Frame(f)
        row.pack(fill='x', pady=8)
        ttk.Label(row, text='Не трогать файлы новее, чем (дней):').pack(side='left')
        self.age = tk.StringVar(value='7')
        ttk.Spinbox(row, from_=0, to=3650, textvariable=self.age, width=7).pack(side='left', padx=8)
        self.clean_info = tk.StringVar()
        ttk.Label(f, textvariable=self.clean_info, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        self.clean_items = []
        self.clean_tree = self.table(f, ['Файл', 'Размер', 'Категория'], [650, 100, 180])

    def scan_clean(self):
        try:
            age = int(self.age.get())
        except ValueError:
            messagebox.showerror('Сколько дней?', 'Введите целое число от 0 и больше. Например, 7 — искать файлы старше недели.')
            return
        if age < 0:
            messagebox.showinfo('Сколько дней?', 'Количество дней не может быть отрицательным. Для начала оставьте 7.')
            return
        cats = [k for k, v in self.clean_flags.items() if v.get()]
        if not cats:
            messagebox.showinfo('Что искать?', 'Отметьте хотя бы один вид файлов. Для начала выберите временные данные приложений.')
            return
        def done(result):
            self.clean_items, errors = result
            self.fill(self.clean_tree, [(x.path, c.human(x.size), x.category) for x in self.clean_items])
            self.clean_info.set(f'Найдено: {len(self.clean_items)} файлов, {c.human(sum(x.size for x in self.clean_items))}. Выберите строки.' if self.clean_items else 'Подходящих файлов нет. Ничего менять не нужно.')
            if errors:
                self.report('Пропущенные каталоги', '\n'.join(errors))
        self.task('Сканирование', lambda: c.Cleaner(self.env).scan(cats, age), done)

    def clean_selected(self):
        items = self.selected(self.clean_tree, self.clean_items)
        self.quarantine(items, self.scan_clean)

    def quarantine(self, items, refresh=None):
        if not items:
            messagebox.showinfo('Выбор', 'Сначала нажмите «Найти файлы», затем щёлкните нужные строки в списке. Для нескольких строк удерживайте Ctrl.')
            return
        preview = '\n'.join(x.path for x in items[:15])
        if not messagebox.askyesno('Убрать файлы с возможностью возврата?', f'Выбрано файлов: {len(items)}, объём: {c.human(sum(x.size for x in items))}.\n\nОни исчезнут из исходных папок, но сохранятся в OpenCare. Место на том же диске пока не освободится. Вернуть их можно в «Вернуть изменения».\n\n{preview}\n\nУбрать выбранные файлы?' ):
            return
        def done(r):
            self.report('Файлы убраны с возможностью возврата', f"Убрано файлов: {sum(x['phase'] == 'applied' for x in r['entries'])}.\n\nОни хранятся в OpenCare. Место на том же диске пока не освобождено.\nЧтобы вернуть файлы: «Вернуть изменения» → выберите действие → «Отменить действие».\nЧтобы освободить место: после проверки удалите копии навсегда в том же разделе.\n" + ('\nНе удалось убрать:\n'+'\n'.join(r['errors']) if r['errors'] else ''))
            self.refresh_recovery()
            if refresh:
                refresh()
        self.task('Сохранение файлов для возможного возврата', lambda: c.Journal(self.env).quarantine(items), done)

    def programs(self):
        f = self.frames['Программы']
        self.note(f, 'Здесь приложения из меню Linux: значок и обычное название. Библиотеки и другие пакеты без значка приложения в этот список не попадают. Компоненты рабочего стола, которые здесь встречаются, защищены от удаления.')
        self.buttons(f, [('Обновить список', self.load_packages), ('Удалить выбранную…', self.remove_package), ('О программе', self.application_details)])
        ttk.Label(f, text='Найти приложение:', style='Muted.TLabel').pack(anchor='w', pady=(0, 6))
        self.pkg_filter = tk.StringVar()
        ttk.Entry(f, textvariable=self.pkg_filter).pack(fill='x', pady=(0, 8))
        self.pkg_filter.trace_add('write', lambda *_: self.filter_packages())
        self.app_count = tk.StringVar(value='Загружаем приложения при открытии раздела…')
        ttk.Label(f, textvariable=self.app_count, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        self.pkg_items, self.pkg_visible = [], []
        self.app_icons = None
        box = ttk.Frame(f)
        box.pack(fill='both', expand=True)
        self.pkg_tree = ttk.Treeview(box, show='tree', selectmode='browse', style='Apps.Treeview')
        ttk.Style(self).configure('Apps.Treeview', rowheight=52, font=('Sans', 12))
        self.pkg_tree.column('#0', width=650, minwidth=250)
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.pkg_tree.yview)
        self.pkg_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.pkg_tree.pack(side='left', fill='both', expand=True)
        self.pkg_tree.tag_configure('even', background='#f7f9fd')
        self.pkg_tree.bind('<Double-1>', lambda _: self.application_details())

    def load_packages(self):
        def done(result):
            self.pkg_items, errors = result
            self.filter_packages()
            if errors:
                self.status.set('Список приложений загружен. Для части записей есть подробности проверки.')
        self.task('Поиск приложений из меню Linux', lambda: apps.inventory(self.env), done)

    def filter_packages(self):
        query = self.pkg_filter.get().casefold()
        self.pkg_visible = [app for app in self.pkg_items if query in (app.name+' '+app.description).casefold()]
        if self.app_icons is None:
            self.app_icons = AppIcons(self)
        self.pkg_tree.delete(*self.pkg_tree.get_children())
        for i, app in enumerate(self.pkg_visible):
            self.pkg_tree.insert('', 'end', iid=str(i), text='  '+app.name,
                                 image=self.app_icons.get(app.icon), tags=('even',) if i % 2 else ())
        self.app_count.set(f'Приложений: {len(self.pkg_visible)}' if self.pkg_visible else 'Приложений с таким названием нет. Попробуйте другое название.' if query else 'Приложения с ярлыками в меню не найдены. Системные пакеты вместо них не показываются.')

    def application_details(self):
        chosen = self.selected(self.pkg_tree, self.pkg_visible)
        if not self.require_one(chosen):
            return
        app = chosen[0]
        reason = apps.protected_reason(app)
        self.report(app.name, app.name+'\n\n'+(app.description or 'Приложение из меню вашего Linux.')+'\n\n'+(reason or 'Удаление доступно через кнопку «Удалить выбранную…». Перед удалением Linux покажет, что изменится, и запросит подтверждение.'))

    def remove_package(self):
        selected = self.selected(self.pkg_tree, self.pkg_visible)
        if len(selected) != 1:
            messagebox.showinfo('Выбор', 'Щёлкните одну знакомую программу в списке.')
            return
        app = selected[0]
        reason = apps.protected_reason(app)
        if reason:
            messagebox.showinfo('Удаление недоступно: '+app.name, reason)
            return
        command = c.uninstall_command(app.package)
        text = shlex.join(command)
        win = tk.Toplevel(self)
        win.title('Удаление: '+app.name)
        ttk.Label(win, text='Сейчас откроется терминал — окно команд. Linux покажет, что будет удалено,\nи запросит подтверждение. Если список непонятен, отмените удаление.\nПароль в терминале может вводиться без отображения символов.', padding=15).pack()
        entry = ttk.Entry(win, width=95)
        ttk.Label(win, text=app.name, font=('Sans', 16, 'bold'), padding=15).pack()
        ttk.Button(win, text='Показать техническую команду', command=lambda: entry.pack(padx=15, pady=10)).pack(pady=5)
        entry.insert(0, text)
        entry.configure(state='readonly')
        def launch():
            if not messagebox.askyesno('Подтверждение', f'Начать удаление «{app.name}»?\n\nLinux откроет окно команд и запросит подтверждение. Прочитайте список перед окончательным согласием.', parent=win):
                return
            terminal = next((x for x in ['x-terminal-emulator', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'xterm'] if shutil.which(x)), None)
            if not terminal:
                messagebox.showinfo('Терминал', 'Скопируйте команду и выполните её в своём терминале.', parent=win)
                return
            # Command is generated from validated package IDs and shell-quoted.
            script = text + '; printf "\\nНажмите Enter для закрытия…"; read answer'
            if terminal == 'gnome-terminal':
                argv = [terminal, '--', 'sh', '-c', script]
            elif terminal == 'xfce4-terminal':
                argv = [terminal, '--command', shlex.join(['sh', '-c', script])]
            else:
                argv = [terminal, '-e', 'sh', '-c', script]
            try:
                subprocess.Popen(argv)
                win.destroy()
            except OSError as e:
                messagebox.showerror('Терминал', str(e))
        ttk.Button(win, text='Запустить в терминале', command=launch).pack(pady=15)

    def find_remnants(self):
        selected = self.selected(self.pkg_tree, self.pkg_visible)
        term = simpledialog.askstring('Поиск остатков', 'Часть названия приложения (минимум 3 символа):', initialvalue=(selected[0].package.name if selected[0].package else selected[0].name) if len(selected) == 1 else '')
        if not term:
            return
        def done(paths):
            win = tk.Toplevel(self)
            win.title('Предполагаемые остатки')
            win.geometry('850x500')
            self.note(win, 'Это только папки с похожими названиями, а не доказанные остатки программы. Они могут содержать документы и настройки. Откройте список файлов и убирайте лишь то, что вам понятно.')
            tree = self.table(win, ['Путь'], [780])
            self.fill(tree, [(p,) for p in paths])
            def move():
                chosen = self.selected(tree, paths)
                if not chosen:
                    return
                def scan():
                    items = []
                    for path in chosen:
                        p = Path(path)
                        if p.is_file():
                            items.append(c.candidate(p, 'Предполагаемые остатки'))
                        else:
                            items.extend(c.candidate(x, 'Предполагаемые остатки') for x, _ in c.walk_files(p))
                    return items
                self.task('Просмотр файлов остатков', scan, lambda items: self.remnant_preview(items))
            ttk.Button(win, text='Просмотреть файлы выбранных путей', command=move).pack(pady=8)
        self.task('Поиск остатков', lambda: c.remnants(self.env, term), done)

    def remnant_preview(self, items):
        win = tk.Toplevel(self)
        win.title('Файлы предполагаемых остатков')
        win.geometry('850x500')
        tree = self.table(win, ['Файл', 'Размер'], [680, 100])
        self.fill(tree, [(x.path, c.human(x.size)) for x in items])
        ttk.Button(win, text='Убрать выбранные с возможностью возврата', command=lambda: self.quarantine(self.selected(tree, items))).pack(pady=8)

    def startup(self):
        f = self.frames['Автозагрузка']
        self.note(f, 'Эти программы могут запускаться при входе в Linux. Отключение не удаляет программу и не закрывает её сейчас: оно повлияет на следующий вход. Начните только со знакомых названий.')
        self.buttons(f, [('Обновить', self.load_startup), ('Запускать при входе', lambda: self.toggle_startup(True)), ('Не запускать при входе', lambda: self.toggle_startup(False))])
        self.start_items = []
        self.start_tree = self.table(f, ['Программа', 'Запуск при входе', 'Примечание'], [330, 180, 260])
        self.start_tree.bind('<Double-1>', lambda _: self.startup_details())

    def load_startup(self):
        def done(items):
            self.start_items = items
            self.fill(self.start_tree, [(i['name'], 'Разрешён' if i['enabled'] else 'Отключён', 'Зависит от рабочего стола' if i['condition'] else '') for i in items])
        self.task('Чтение автозагрузки', lambda: c.Startup(self.env).list(), done)

    def startup_details(self):
        items = self.selected(self.start_tree, self.start_items)
        if self.require_one(items):
            item = items[0]
            self.report('Подробности запуска: '+item['name'], 'Эту запись использует Linux при входе в систему.\n\nТехнические подробности:\nКоманда: '+item['exec']+'\nФайл: '+item['source']+'\nУсловие рабочего стола: '+(item['condition'] or 'нет'))

    def toggle_startup(self, enabled):
        items = self.selected(self.start_tree, self.start_items)
        if not items:
            messagebox.showinfo('Выберите программу', 'Щёлкните нужную строку в списке, затем повторите действие.')
            return
        if not messagebox.askyesno('Запуск при входе в Linux', ('Включить' if enabled else 'Отключить') + ' выбранные записи?\n' + '\n'.join(x['name'] for x in items)):
            return
        self.task('Изменение автозагрузки', lambda: [c.Startup(self.env).toggle(x, enabled) for x in items], lambda _: self.load_startup())

    def configs(self):
        f = self.frames['Конфигурации']
        self.note(f, 'Это дополнительный инструмент для ручного изменения настроек. Новичку лучше сначала открыть обычные настройки нужной программы. Если знаете, какой файл изменить, закройте программу перед редактированием. Предыдущая версия сохранится для отмены.')
        self.buttons(f, [('Найти файлы', self.load_configs), ('Открыть файл…', self.choose_config), ('Редактировать выбранный', self.edit_selected_config)])
        self.config_query = tk.StringVar()
        ttk.Entry(f, textvariable=self.config_query).pack(fill='x', pady=(0, 8))
        self.config_items = []
        self.config_tree = self.table(f, ['Путь', 'Размер'], [800, 120])
        self.config_tree.bind('<Double-1>', lambda _: self.edit_selected_config())

    def load_configs(self):
        q = self.config_query.get()
        def done(r):
            self.config_items, errors = r
            self.fill(self.config_tree, [(p, c.human(s)) for p, s in self.config_items])
            if errors:
                self.report('Пропуски', '\n'.join(errors))
        self.task('Поиск конфигураций', lambda: c.config_files(self.env, q), done)

    def choose_config(self):
        p = filedialog.askopenfilename(initialdir=self.env.config)
        if p:
            self.open_editor(p)

    def edit_selected_config(self):
        items = self.selected(self.config_tree, self.config_items)
        if self.require_one(items):
            self.open_editor(items[0][0])

    def open_editor(self, path):
        try:
            original = c.read_config(self.env, path)
        except Exception as e:
            messagebox.showerror('Редактор', str(e))
            return
        win = tk.Toplevel(self)
        win.title(path)
        win.geometry('950x650')
        text = tk.Text(win, wrap='none', undo=True)
        text.pack(fill='both', expand=True)
        text.insert('1.0', original)
        bar = ttk.Frame(win, padding=8)
        bar.pack(fill='x')
        search, replace = tk.StringVar(), tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=22).pack(side='left')
        ttk.Entry(bar, textvariable=replace, width=22).pack(side='left', padx=6)
        def find():
            text.tag_remove('found', '1.0', 'end')
            q = search.get()
            if not q:
                return
            pos = '1.0'
            first = None
            while True:
                pos = text.search(q, pos, stopindex='end', exact=True)
                if not pos:
                    break
                if first is None:
                    first = pos
                end = f'{pos}+{len(q)}c'
                text.tag_add('found', pos, end)
                pos = end
            text.tag_configure('found', background='#ffe08a', foreground='black')
            if first:
                text.see(first)
        def replace_all():
            q = search.get()
            if q and messagebox.askyesno('Замена', 'Заменить все вхождения в открытом буфере?', parent=win):
                value = text.get('1.0', 'end-1c').replace(q, replace.get())
                text.delete('1.0', 'end')
                text.insert('1.0', value)
        def save():
            nonlocal original
            try:
                if c.read_config(self.env, path) != original:
                    raise c.CareError('Файл изменился извне. Откройте его заново.')
                value = text.get('1.0', 'end-1c')
                if messagebox.askyesno('Сохранение', f'Записать {path}?\nИсходная версия сохранится в журнале.', parent=win):
                    c.Journal(self.env).write(path, value.encode(), 'Редактор: ' + Path(path).name)
                    original = value
                    self.status.set('Конфигурация сохранена с резервной копией')
            except Exception as e:
                messagebox.showerror('Сохранение', str(e), parent=win)
        for label, fn in [('Найти', find), ('Заменить всё', replace_all), ('Сохранить', save)]:
            ttk.Button(bar, text=label, command=fn).pack(side='left', padx=3)

    def snapshots(self):
        f = self.frames['Снимки']
        self.note(f, 'Сохраните список файлов папки «До», затем «После» изменения настроек и сравните две записи. Вы увидите, какие файлы изменились. Это не резервная копия: вернуть содержимое файлов из такого списка нельзя.')
        self.buttons(f, [('Сохранить состояние папки…', self.new_snapshot), ('Обновить', self.load_snapshots), ('Сравнить две записи', self.compare)])
        self.snap_items = []
        self.snap_tree = self.table(f, ['Дата', 'Метка', 'Каталог', 'Файлов', 'Пропуски'], [180, 170, 450, 80, 80])
        self.load_snapshots()

    def load_snapshots(self):
        items = []
        for p in sorted(self.env.snapshots.glob('*.json')):
            try:
                items.append(json.loads(p.read_text()))
            except (ValueError, OSError):
                pass
        self.snap_items = items
        self.fill(self.snap_tree, [(x['created'][:19], x['label'], x['root'], len(x['files']), len(x['errors'])) for x in items])

    def new_snapshot(self):
        root = filedialog.askdirectory(initialdir=self.env.config)
        if not root:
            return
        label = simpledialog.askstring('Метка', 'Название снимка:')
        if label is None:
            return
        def done(doc):
            self.load_snapshots()
            if doc['errors']:
                self.report('Неполный снимок — пропуски', '\n'.join(doc['errors']))
        self.task('Создание снимка', lambda: c.snapshot(self.env, root, label), done)

    def compare(self):
        items = self.selected(self.snap_tree, self.snap_items)
        if len(items) != 2:
            messagebox.showinfo('Сравнение', 'Выберите два снимка одного каталога (Ctrl + щелчок).')
            return
        items.sort(key=lambda x: x['created'])
        try:
            changes = c.compare_snapshots(*items)
            self.report('Изменения между снимками', '\n'.join(f'{s}: {p}' for s, p in changes) or 'Изменений нет.')
        except c.CareError as e:
            messagebox.showerror('Сравнение', str(e))

    def disk(self):
        f = self.frames['Диск']
        self.note(f, 'Выберите знакомую папку, например «Загрузки». Сверху появятся самые большие файлы. Поиск ничего не меняет. Убирайте только файлы, назначение которых вам понятно.')
        self.buttons(f, [('Выбрать папку и найти файлы', self.scan_disk), ('Убрать выбранные', self.disk_quarantine), ('Показать группы дубликатов', self.show_duplicates)])
        self.dupe_flag = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Искать одинаковые файлы (это займёт больше времени)', variable=self.dupe_flag).pack(anchor='w', pady=(0, 8))
        self.disk_items, self.dupes = [], []
        self.disk_tree = self.table(f, ['Файл', 'Размер'], [850, 130])

    def scan_disk(self):
        root = filedialog.askdirectory(initialdir=self.env.home)
        if not root:
            return
        dupes = self.dupe_flag.get()
        def done(r):
            self.disk_items, self.dupes, errors = r
            self.fill(self.disk_tree, [(p, c.human(s)) for p, s in self.disk_items])
            self.status.set(f'{len(self.disk_items)} файлов • {len(self.dupes)} групп дубликатов')
            if errors:
                self.report('Пропуски анализа', '\n'.join(errors))
        self.task('Анализ диска', lambda: c.disk_scan(self.env, root, dupes), done)

    def disk_quarantine(self):
        try:
            self.quarantine([c.candidate(p) for p, _ in self.selected(self.disk_tree, self.disk_items)])
        except Exception as e:
            messagebox.showerror('Файлы', str(e))

    def show_duplicates(self):
        self.report('Дубликаты', '\n\n'.join(c.human(size) + ' каждый:\n' + '\n'.join(paths) for size, paths in self.dupes) or 'Дубликаты не найдены или поиск не включён.')

    def settings(self):
        f = self.frames['Настройки']
        self.settings_hint = tk.StringVar(value='Определён рабочий стол: '+c.desktop_info()['desktop']+'. Нажми «Обновить» для проверки доступных параметров.')
        ttk.Label(f, textvariable=self.settings_hint, style='Muted.TLabel', wraplength=870).pack(anchor='w', pady=(0, 16))
        self.buttons(f, [('Обновить', self.load_settings), ('Включить', lambda: self.change_setting('true')), ('Выключить', lambda: self.change_setting('false'))])
        self.setting_items = []
        self.setting_tree = self.table(f, ['Настройка', 'Состояние'], [670, 150])

    def load_settings(self):
        def done(items):
            self.setting_items = items
            self.fill(self.setting_tree, [(x[0], 'Включено' if x[4] == 'true' else 'Выключено') for x in items])
            desktop = c.desktop_info()['desktop']
            self.settings_hint.set(f'{desktop} · {len(items)} доступных настроек. Выбери строку и нажми «Включить» или «Выключить». Изменения можно отменить.' if items else f'Для {desktop} нет доступных переключателей. Неподдерживаемые параметры не показываются.')
        self.task('Чтение настроек', c.available_settings, done)

    def change_setting(self, value):
        items = self.selected(self.setting_tree, self.setting_items)
        if not self.require_one(items):
            return
        if not messagebox.askyesno('Настройка', f"{'Включить' if value == 'true' else 'Выключить'} «{items[0][0]}»?"):
            return
        x = items[0]
        self.task('Изменение настройки', lambda: c.set_setting(self.env, x[1], x[2], value), lambda _: self.load_settings())

    def recovery(self):
        f = self.frames['Восстановление']
        self.note(f, 'Выберите действие и нажмите «Отменить действие», чтобы вернуть убранные файлы или прежние настройки. Копии занимают место. Кнопка «Удалить копии навсегда…» освобождает его, но после этого вернуть файлы через OpenCare нельзя.')
        self.buttons(f, [('Отменить действие', self.restore), ('Обновить', self.refresh_recovery), ('Что было изменено', self.recovery_details)])
        self.buttons(f, [('Удалить копии навсегда…', self.purge)], primary=False)
        self.recovery_items = []
        self.recovery_tree = self.table(f, ['Когда', 'Что изменили', 'Можно ли отменить'], [170, 350, 250])
        self.refresh_recovery()

    def refresh_recovery(self):
        self.recovery_items = c.Journal(self.env).records()
        self.fill(self.recovery_tree, [(r['created'].replace('T', ' '), r['title'], STATUS.get(r['status'], r['status'])) for r in self.recovery_items])

    def recovery_details(self):
        items = self.selected(self.recovery_tree, self.recovery_items)
        if not self.require_one(items):
            return
        r = items[0]
        lines = [r['title'], 'Когда: '+r['created'].replace('T', ' '),
                 'Состояние: '+STATUS.get(r['status'], r['status']), '']
        if 'setting' in r:
            setting = r['setting']
            name = next((x[0] for x in c.SETTINGS if x[1:3] == (setting['schema'], setting['key'])), setting['key'])
            readable = lambda value: 'Включено' if value == 'true' else 'Выключено' if value == 'false' else value
            lines += [name, 'Было: '+readable(setting['before']), 'Стало: '+readable(setting['after'])]
        else:
            for entry in r['entries']:
                action = 'Файл убран и сохранён для возврата' if entry['kind'] == 'move' else 'Изменено содержимое файла'
                if entry.get('phase') == 'restored':
                    action = 'Изменение уже отменено'
                lines += [action, entry['path'], '']
        if r.get('errors'):
            lines += ['Что не удалось выполнить:', *r['errors']]
        self.report('Что было изменено', '\n'.join(lines))

    def restore(self):
        items = self.selected(self.recovery_tree, self.recovery_items)
        if not self.require_one(items):
            return
        if not messagebox.askyesno('Восстановление', 'Отменить выбранную операцию?'):
            return
        r = items[0]
        def work():
            if 'setting' in r:
                c.restore_setting(self.env, r)
                return []
            return c.Journal(self.env).restore(r['id'])
        def done(errors):
            self.refresh_recovery()
            self.report('Восстановление', '\n'.join(errors) if errors else 'Действие отменено. Файлы или настройки возвращены в прежнее состояние.')
        self.task('Восстановление', work, done)

    def purge(self):
        items = self.selected(self.recovery_tree, self.recovery_items)
        if not items:
            messagebox.showinfo('Выберите действие', 'Сначала щёлкните действие в списке. Его сохранённые копии будут удалены только после подтверждения.')
            return
        if not messagebox.askyesno('Необратимое удаление', 'Навсегда удалить выбранные резервные копии?\nОтмена очистки и изменений станет невозможна.\n\n' + '\n'.join(r['title'] for r in items)):
            return
        def work():
            for r in items:
                ident = r['id']
                if Path(ident).name != ident:
                    raise c.CareError('Неверный ID')
                shutil.rmtree(self.env.journal / ident)
        self.task('Удаление резервных копий', work, lambda _: self.refresh_recovery())


def main():
    if os.geteuid() == 0:
        raise SystemExit('Не запускайте OpenCare от root. Используйте обычную учётную запись.')
    App().mainloop()
