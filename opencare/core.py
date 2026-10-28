from __future__ import annotations
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import uuid


class CareError(Exception):
    pass


def run(argv, timeout=45):
    """No shell, no elevation, bounded execution."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CareError(str(e)) from e
    if argv[0] == 'gsettings' and p.returncode == 0 and any(x in p.stderr.lower() for x in ('dconf-critical', 'dconf-warning', 'failed to commit')):
        raise CareError('Не удалось обратиться к настройкам текущего сеанса: ' + p.stderr.strip())
    if p.returncode:
        raise CareError(p.stderr.strip() or p.stdout.strip() or f'Код завершения {p.returncode}')
    return p.stdout


def atomic_write(path: Path, data: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.opencare-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def dump(path, obj):
    atomic_write(Path(path), json.dumps(obj, ensure_ascii=False, indent=2).encode())


def within(path, root):
    return path == root or root in path.parents


def human(n):
    for unit in ('Б', 'КиБ', 'МиБ', 'ГиБ', 'ТиБ'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} ПиБ'


@dataclasses.dataclass
class Candidate:
    path: str
    size: int
    category: str
    mtime_ns: int
    inode: int
    device: int


class Environment:
    def __init__(self, home=None, state=None):
        self.home = Path(home or Path.home()).absolute()
        def xdg(name, fallback):
            if home is not None:
                return self.home / fallback
            value = Path(os.environ.get(name, str(self.home / fallback)))
            return value if value.is_absolute() else self.home / fallback
        self.config = xdg('XDG_CONFIG_HOME', '.config')
        self.cache = xdg('XDG_CACHE_HOME', '.cache')
        self.data = xdg('XDG_DATA_HOME', '.local/share')
        self.state = Path(state) if state else xdg('XDG_STATE_HOME', '.local/state') / 'opencare'
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)
        self.journal = self.state / 'journal'
        self.journal.mkdir(exist_ok=True, mode=0o700)
        self.snapshots = self.state / 'snapshots'
        self.snapshots.mkdir(exist_ok=True, mode=0o700)

    def writable_file(self, value):
        p = Path(value).absolute()
        if '..' in p.parts:
            raise CareError('Путь с .. не допускается')
        if not within(p, self.home) or within(p, self.state):
            raise CareError('Изменять можно только пользовательские файлы вне каталога OpenCare.')
        # Reject every symlink component, including a linked parent directory.
        for q in (p, *p.parents):
            if q.is_symlink():
                raise CareError(f'Символические ссылки не изменяются: {q}')
        if p.exists() and not p.is_file():
            raise CareError(f'Ожидался обычный файл: {p}')
        return p

    def roots(self):
        return [self.cache, self.home / '.thumbnails', self.home / '.local/share/Trash/files']


class Journal:
    """A durable write-ahead record; cleanup moves bytes instead of destroying them."""
    def __init__(self, env):
        self.env = env

    def records(self):
        result = []
        for p in self.env.journal.glob('*/record.json'):
            try:
                r = json.loads(p.read_text())
                result.append(r)
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda r: r['created'], reverse=True)

    def start(self, title):
        ident = dt.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
        directory = self.env.journal / ident
        directory.mkdir(mode=0o700)
        r = {'id': ident, 'title': title, 'created': dt.datetime.now().isoformat(timespec='seconds'),
             'status': 'active', 'entries': [], 'errors': []}
        self.save(r)
        return r

    def save(self, r):
        dump(self.env.journal / r['id'] / 'record.json', r)

    def quarantine(self, candidates, title='Очистка'):
        r = self.start(title)
        for c in candidates:
            try:
                p = self.env.writable_file(c.path)
                s = p.stat()
                if (s.st_mtime_ns, s.st_ino, s.st_dev, s.st_size) != (c.mtime_ns, c.inode, c.device, c.size):
                    raise CareError('Файл изменился после сканирования — пропущен')
                dest = self.env.journal / r['id'] / f"{len(r['entries']):06d}.backup"
                entry = {'path': str(p), 'backup': dest.name, 'kind': 'move', 'phase': 'pending'}
                r['entries'].append(entry)
                self.save(r)
                shutil.move(str(p), str(dest))
                entry['phase'] = 'applied'
                self.save(r)
            except (CareError, OSError) as e:
                r['errors'].append(f'{c.path}: {e}')
                self.save(r)
        r['status'] = 'done'
        self.save(r)
        return r

    def write(self, path, content, title='Изменение файла'):
        p = self.env.writable_file(path)
        r = self.start(title)
        dest = self.env.journal / r['id'] / '000000.backup'
        exists = p.exists()
        mode = stat.S_IMODE(p.stat().st_mode) if exists else 0o600
        if exists:
            shutil.copy2(p, dest)
        e = {'path': str(p), 'backup': dest.name if exists else None, 'kind': 'write',
             'phase': 'pending', 'mode': mode, 'after_sha256': hashlib.sha256(content).hexdigest()}
        r['entries'].append(e)
        self.save(r)
        atomic_write(p, content, mode)
        e['phase'] = 'applied'
        r['status'] = 'done'
        self.save(r)
        return r

    def restore(self, ident):
        if Path(ident).name != ident:
            raise CareError('Неверный идентификатор операции')
        record_path = self.env.journal / ident / 'record.json'
        r = json.loads(record_path.read_text())
        errors = []
        for e in reversed(r['entries']):
            if e.get('phase') == 'restored':
                continue
            try:
                p = self.env.writable_file(e['path'])
                b = record_path.parent / e['backup'] if e['backup'] else None
                if b and (b.parent != record_path.parent or b.is_symlink()):
                    raise CareError('Неверный путь резервной копии')
                if e['kind'] == 'move':
                    if not b or not b.exists():
                        if e['phase'] == 'pending' and p.exists():
                            e['phase'] = 'restored'
                            continue
                        raise CareError('Резервная копия отсутствует')
                    if p.exists():
                        raise CareError('По исходному пути уже есть файл; он не будет перезаписан')
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(b), str(p))
                else:
                    if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() != e['after_sha256']:
                        raise CareError('Файл изменён после операции; восстановление пропущено')
                    if b:
                        atomic_write(p, b.read_bytes(), e.get('mode', 0o600))
                    elif p.exists():
                        p.unlink()
                e['phase'] = 'restored'
                self.save(r)
            except (OSError, CareError) as exc:
                errors.append(f"{e['path']}: {exc}")
        r['status'] = 'restored' if not errors else 'restore_partial'
        self.save(r)
        return errors


def walk_files(root, limit=150000):
    """No following symlinks; permission errors are returned separately by callers."""
    root = Path(root)
    if root.is_symlink() or not root.exists():
        return
    count = 0
    def error(e):
        raise e
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=error):
        dirs[:] = sorted(d for d in dirs if not (Path(parent) / d).is_symlink())
        for name in sorted(names):
            p = Path(parent) / name
            try:
                s = p.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(s.st_mode):
                yield p, s
                count += 1
                if count >= limit:
                    raise CareError(f'Достигнут лимит {limit} файлов; выберите более узкий каталог')


class Cleaner:
    def __init__(self, env):
        self.env = env

    def scan(self, categories=('cache',), age_days=7):
        if age_days < 0:
            raise CareError('Возраст не может быть отрицательным')
        roots = []
        if 'cache' in categories:
            roots += [(self.env.cache, 'Кэш'), (self.env.home / '.thumbnails', 'Миниатюры')]
        if 'trash' in categories:
            roots += [(self.env.data / 'Trash/files', 'Корзина'), (self.env.data / 'Trash/info', 'Метаданные корзины')]
        if 'privacy' in categories:
            # Only explicit history databases; cookies, passwords and bookmarks excluded.
            for base in (self.env.config / 'chromium', self.env.config / 'google-chrome'):
                if base.exists():
                    roots += [(p / 'History', 'История Chromium') for p in base.iterdir()
                              if p.is_dir() and not p.is_symlink() and (p.name == 'Default' or p.name.startswith('Profile '))]
            roots += [(self.env.data / 'recently-used.xbel', 'Недавние документы')]
        result, errors, seen = [], [], set()
        cutoff = time.time() - age_days * 86400
        for root, category in roots:
            try:
                if category == 'История Chromium' and any(Path(str(root) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
                    errors.append(f'{root}: есть служебные файлы SQLite; закройте браузер и повторите')
                    continue
                self.env.writable_file(root / '_check' if root.is_dir() else root)
                files = [(root, root.lstat())] if root.is_file() and not root.is_symlink() else walk_files(root)
                for p, s in files:
                    if within(p, self.env.state) or str(p) in seen or s.st_mtime > cutoff:
                        continue
                    if not stat.S_ISREG(s.st_mode):
                        continue
                    seen.add(str(p))
                    result.append(Candidate(str(p), s.st_size, category, s.st_mtime_ns, s.st_ino, s.st_dev))
            except (OSError, CareError) as e:
                errors.append(f'{root}: {e}')
        return result, errors


def candidate(path, category='Выбранный файл'):
    p = Path(path)
    s = p.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise CareError('Не обычный файл')
    return Candidate(str(p), s.st_size, category, s.st_mtime_ns, s.st_ino, s.st_dev)


class Startup:
    def __init__(self, env, system_dirs=None):
        self.env = env
        self.user_dir = env.config / 'autostart'
        self.system_dirs = [Path(x) for x in (system_dirs if system_dirs is not None else ['/etc/xdg/autostart'])]

    def list(self):
        import configparser
        entries = {}
        for directory in [*self.system_dirs, self.user_dir]:
            if not directory.exists() or directory.is_symlink():
                continue
            for p in sorted(directory.glob('*.desktop')):
                if p.is_symlink():
                    continue
                cfg = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    cfg.read(p, encoding='utf-8')
                    d = cfg['Desktop Entry']
                    entries[p.name] = {'id': p.name, 'name': d.get('Name[ru]', d.get('Name', p.stem)),
                                      'exec': d.get('Exec', ''), 'enabled': d.get('Hidden', 'false').lower() != 'true'
                                      and d.get('X-GNOME-Autostart-enabled', 'true').lower() != 'false',
                                      'source': str(p), 'scope': 'Пользователь' if directory == self.user_dir else 'Системный',
                                      'condition': d.get('OnlyShowIn', '') or d.get('NotShowIn', '')}
                except (OSError, ValueError, KeyError, configparser.Error):
                    continue
        return list(entries.values())

    def toggle(self, item, enabled):
        import configparser
        source = Path(item['source'])
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str
        cfg.read_string(source.read_text())
        cfg['Desktop Entry']['Hidden'] = 'false' if enabled else 'true'
        cfg['Desktop Entry']['X-GNOME-Autostart-enabled'] = 'true' if enabled else 'false'
        import io
        out = io.StringIO()
        cfg.write(out, space_around_delimiters=False)
        return Journal(self.env).write(self.user_dir / source.name, out.getvalue().encode(), 'Автозагрузка: ' + item['name'])


@dataclasses.dataclass
class Package:
    manager: str
    name: str
    version: str
    description: str = ''


def packages():
    result, errors = [], []
    if shutil.which('dpkg-query'):
        try:
            for line in run(['dpkg-query', '-W', '-f=${db:Status-Abbrev}\t${binary:Package}\t${Version}\t${binary:Summary}\n']).splitlines():
                cols = line.split('\t', 3)
                if len(cols) == 4 and cols[0].startswith('ii'):
                    result.append(Package('apt', *cols[1:]))
        except CareError as e:
            errors.append(str(e))
    elif shutil.which('rpm'):
        try:
            for line in run(['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{SUMMARY}\n']).splitlines():
                c = line.split('\t', 2)
                if len(c) == 3:
                    result.append(Package('dnf' if shutil.which('dnf') else 'zypper', *c))
        except CareError as e:
            errors.append(str(e))
    elif shutil.which('pacman'):
        try:
            for line in run(['pacman', '-Q']).splitlines():
                c = line.split(' ', 1)
                if len(c) == 2:
                    result.append(Package('pacman', *c))
        except CareError as e:
            errors.append(str(e))
    if shutil.which('flatpak'):
        for scope in ('--user', '--system'):
            try:
                for line in run(['flatpak', 'list', scope, '--app', '--columns=application,version,name']).splitlines():
                    c = line.split('\t', 2)
                    if len(c) == 3:
                        result.append(Package('flatpak-user' if scope == '--user' else 'flatpak-system', *c))
            except CareError as e:
                errors.append(f'Flatpak {scope}: {e}')
    if shutil.which('snap'):
        try:
            for line in run(['snap', 'list']).splitlines()[1:]:
                c = line.split()
                if len(c) >= 2:
                    result.append(Package('snap', c[0], c[1]))
        except CareError as e:
            errors.append(str(e))
    return result, errors


def uninstall_command(pkg):
    # Package IDs are arguments, never shell text; reject option-like / corrupt IDs.
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:@-]*', pkg.name):
        raise CareError('Некорректное имя пакета')
    commands = {'apt': ['sudo', 'apt-get', 'remove', '--', pkg.name],
                'dnf': ['sudo', 'dnf', 'remove', '--', pkg.name],
                'zypper': ['sudo', 'zypper', 'remove', '--', pkg.name],
                'pacman': ['sudo', 'pacman', '-R', '--', pkg.name],
                'flatpak-user': ['flatpak', 'uninstall', '--user', '--', pkg.name],
                'flatpak-system': ['flatpak', 'uninstall', '--system', '--', pkg.name],
                'snap': ['sudo', 'snap', 'remove', '--', pkg.name]}
    try:
        return commands[pkg.manager]
    except KeyError:
        raise CareError('Менеджер пакетов не поддерживается')


def remnants(env, term):
    """Explicit name matches, never asserted to be owned by an application."""
    if len(term.strip()) < 3:
        raise CareError('Для поиска остатков введите минимум 3 символа')
    matches = []
    for root in (env.config, env.cache, env.data):
        if not root.exists() or root.is_symlink():
            continue
        for p in root.iterdir():
            if term.casefold() in p.name.casefold() and not p.is_symlink() and not within(p, env.state):
                matches.append(str(p))
    return sorted(matches)


def config_files(env, query=''):
    result, errors = [], []
    for root in (env.config,):
        try:
            for p, s in walk_files(root, 50000):
                if within(p, env.state) or s.st_size > 1024 * 1024 or query.casefold() not in str(p).casefold():
                    continue
                result.append((str(p), s.st_size))
        except (OSError, CareError) as e:
            errors.append(str(e))
    return result, errors


def read_config(env, path):
    p = env.writable_file(path)
    if p.stat().st_size > 1024 * 1024:
        raise CareError('Редактор ограничен файлами до 1 МиБ')
    b = p.read_bytes()
    if b'\0' in b:
        raise CareError('Бинарные файлы нельзя редактировать')
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        raise CareError('Поддерживается текст UTF-8')


def snapshot(env, root, label=''):
    root = Path(root).absolute()
    if '..' in root.parts:
        raise CareError('Путь с .. не допускается')
    if not within(root, env.home) or root.is_symlink():
        raise CareError('Снимки поддерживаются только внутри домашней папки без символических ссылок')
    for parent in root.parents:
        if parent.is_symlink():
            raise CareError('Родитель снимка является символической ссылкой')
    if not root.is_dir():
        raise CareError('Выберите существующий каталог')
    files, errors = {}, []
    try:
        for p, s in walk_files(root):
            if within(p, env.state):
                continue
            try:
                if s.st_size > 10 * 1024 * 1024:
                    errors.append(f'{p}: больше 10 МиБ — сохранены только размер и время')
                    digest = None
                else:
                    digest = hashlib.sha256(p.read_bytes()).hexdigest()
                files[str(p.relative_to(root))] = {'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'sha256': digest}
            except OSError as e:
                errors.append(f'{p}: {e}')
    except (OSError, CareError) as e:
        errors.append(str(e))
    ident = dt.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    doc = {'id': ident, 'root': str(root), 'label': label, 'created': dt.datetime.now().isoformat(), 'files': files, 'errors': errors}
    dump(env.snapshots / (ident + '.json'), doc)
    return doc


def compare_snapshots(a, b):
    if a['root'] != b['root']:
        raise CareError('Выберите два снимка одного каталога')
    changes = []
    for name in sorted(set(a['files']) | set(b['files'])):
        old, new = a['files'].get(name), b['files'].get(name)
        status = 'Добавлен' if old is None else 'Удалён' if new is None else 'Изменён'
        if old is None or new is None or old != new:
            changes.append((status, name))
    return changes


def disk_scan(env, root, duplicates=False):
    root = Path(root).absolute()
    if '..' in root.parts:
        raise CareError('Путь с .. не допускается')
    if not within(root, env.home) or root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise CareError('Выберите каталог внутри домашней папки без символических ссылок')
    files, errors, groups = [], [], {}
    try:
        for p, s in walk_files(root):
            if within(p, env.state):
                continue
            files.append((str(p), s.st_size))
            if duplicates and s.st_size:
                groups.setdefault(s.st_size, []).append(p)
    except (CareError, OSError) as e:
        errors.append(str(e))
    dupes = []
    for size, paths in groups.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for p in paths:
            try:
                h = hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b''):
                        h.update(chunk)
                by_hash.setdefault(h.hexdigest(), []).append(str(p))
            except OSError as e:
                errors.append(str(e))
        dupes += [(size, paths) for paths in by_hash.values() if len(paths) > 1]
    return sorted(files, key=lambda x: x[1], reverse=True), dupes, errors


GNOME_SETTINGS = [
    ('Скрытые файлы в файловом менеджере', 'org.gnome.nautilus.preferences', 'show-hidden-files', 'bool'),
    ('Секунды в системных часах', 'org.gnome.desktop.interface', 'clock-show-seconds', 'bool'),
    ('Анимации интерфейса', 'org.gnome.desktop.interface', 'enable-animations', 'bool'),
    ('День недели в часах', 'org.gnome.desktop.interface', 'clock-show-weekday', 'bool'),
]
CINNAMON_SETTINGS = [
    ('Скрытые файлы в Nemo', 'org.nemo.preferences', 'show-hidden-files', 'bool'),
    ('Секунды в системных часах', 'org.cinnamon.desktop.interface', 'clock-show-seconds', 'bool'),
    ('Дата в системных часах', 'org.cinnamon.desktop.interface', 'clock-show-date', 'bool'),
    ('24-часовой формат времени', 'org.cinnamon.desktop.interface', 'clock-use-24h', 'bool'),
    ('Анимации интерфейса', 'org.cinnamon.desktop.interface', 'enable-animations', 'bool'),
    ('Эффекты окон', 'org.cinnamon', 'desktop-effects', 'bool'),
    ('Эффекты при смене рабочего стола', 'org.cinnamon', 'desktop-effects-workspace', 'bool'),
]
SETTINGS = GNOME_SETTINGS + CINNAMON_SETTINGS


def desktop_info():
    raw = os.environ.get('XDG_CURRENT_DESKTOP', '') + ':' + os.environ.get('XDG_SESSION_DESKTOP', '')
    lower = raw.lower()
    desktop = 'Cinnamon' if 'cinnamon' in lower else 'GNOME' if 'gnome' in lower else 'KDE' if 'kde' in lower else 'Xfce' if 'xfce' in lower else 'Не определён'
    distro = 'Linux'
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if line.startswith('PRETTY_NAME='):
                distro = line.split('=', 1)[1].strip('"')
    except OSError:
        pass
    return {'desktop': desktop, 'distro': distro, 'session': os.environ.get('XDG_SESSION_TYPE', 'неизвестна')}


def available_settings():
    if not shutil.which('gsettings'):
        return []
    desktop = desktop_info()['desktop']
    supported = CINNAMON_SETTINGS if desktop == 'Cinnamon' else GNOME_SETTINGS if desktop == 'GNOME' else []
    if not supported:
        return []
    schemas = set(run(['gsettings', 'list-schemas']).splitlines())
    result = []
    for item in supported:
        if item[1] in schemas and item[2] in run(['gsettings', 'list-keys', item[1]]).splitlines():
            if run(['gsettings', 'writable', item[1], item[2]]).strip() != 'true':
                continue
            value = run(['gsettings', 'get', item[1], item[2]]).strip()
            if value in ('true', 'false'):
                result.append((*item, value))
    return result


def set_setting(env, schema, key, value):
    allowed = {(x[1], x[2]) for x in available_settings()}
    if (schema, key) not in allowed or value not in ('true', 'false'):
        raise CareError('Настройка не поддерживается')
    old = run(['gsettings', 'get', schema, key]).strip()
    r = Journal(env).start('Настройка: ' + key)
    r['setting'] = {'schema': schema, 'key': key, 'before': old, 'after': value}
    Journal(env).save(r)
    run(['gsettings', 'set', schema, key, value])
    if run(['gsettings', 'get', schema, key]).strip() != value:
        raise CareError('Рабочий стол не подтвердил изменение настройки')
    r['status'] = 'done'
    Journal(env).save(r)
    return r


def restore_setting(env, record):
    s = record['setting']
    if (s['schema'], s['key']) not in {(x[1], x[2]) for x in SETTINGS}:
        raise CareError('Неизвестная настройка')
    current = run(['gsettings', 'get', s['schema'], s['key']]).strip()
    if current != s['after']:
        raise CareError('Настройка уже изменена извне; восстановление пропущено')
    run(['gsettings', 'set', s['schema'], s['key'], s['before']])
    if run(['gsettings', 'get', s['schema'], s['key']]).strip() != s['before']:
        raise CareError('Не удалось подтвердить восстановление')
    record['status'] = 'restored'
    Journal(env).save(record)


def summary(env):
    usage = shutil.disk_usage(env.home)
    return {'home': str(env.home), 'disk_total': usage.total, 'disk_free': usage.free,
            'disk_used': usage.used, 'system': os.uname().sysname + ' ' + os.uname().release,
            'journal_operations': len(Journal(env).records()), 'state': str(env.state)}
