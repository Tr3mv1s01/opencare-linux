"""Application-menu inventory. System packages are never used as GUI fallback."""
import configparser
import dataclasses
import os
from pathlib import Path
import shutil
import subprocess
from . import core as c


@dataclasses.dataclass
class Application:
    name: str
    icon: str
    desktop_file: str
    package: c.Package | None = None
    description: str = ''


def menu_directories(env):
    bases = [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p.startswith('/')]
    return [*(p / 'applications' for p in reversed(bases)),
            Path('/var/lib/flatpak/exports/share/applications'),
            env.data / 'flatpak/exports/share/applications',
            Path('/var/lib/snapd/desktop/applications'), env.data / 'applications']


def inventory(env, directories=None, package_list=None):
    installed, errors = c.packages() if package_list is None else (package_list, [])
    by_name = {}
    for p in installed:
        by_name[(p.manager, p.name)] = p
        if p.manager == 'apt':
            by_name[(p.manager, p.name.split(':')[0])] = p
    entries = {}
    desktops = {x.lower().removeprefix('x-') for x in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':')}
    for directory in directories if directories is not None else menu_directories(env):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob('*.desktop')):
            ident = str(path.relative_to(directory)).replace('/', '-')
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            cfg.optionxform = str
            try:
                cfg.read_string(path.read_text(encoding='utf-8'))
                d = cfg['Desktop Entry']
                entries[ident] = None  # A hidden user entry also hides a system entry.
                if d.get('Type', '') != 'Application' or any(d.get(k, 'false').lower() == 'true' for k in ['Hidden', 'NoDisplay', 'Terminal']):
                    continue
                only = {x.lower().removeprefix('x-') for x in d.get('OnlyShowIn', '').split(';') if x}
                never = {x.lower().removeprefix('x-') for x in d.get('NotShowIn', '').split(';') if x}
                if (only and not only & desktops) or never & desktops:
                    continue
                check = d.get('TryExec')
                if check and not (Path(check).is_file() if check.startswith('/') else shutil.which(check)):
                    continue
                if not d.get('Name') or not (d.get('Exec') or d.get('DBusActivatable', '').lower() == 'true'):
                    continue
                name = d.get('Name[ru_RU]', d.get('Name[ru]', d['Name']))
                app = Application(name, d.get('Icon', ''), str(path), description=d.get('Comment[ru]', d.get('Comment', '')))
                flatpak = d.get('X-Flatpak', '')
                snap = d.get('X-SnapInstanceName', '')
                if flatpak:
                    scope = 'flatpak-user' if str(path).startswith(str(env.data)) else 'flatpak-system'
                    app.package = by_name.get((scope, flatpak))
                elif snap:
                    app.package = by_name.get(('snap', snap))
                entries[ident] = app
            except (OSError, UnicodeError, configparser.Error, KeyError) as e:
                errors.append(f'{path.name}: {e}')
    apps = [a for a in entries.values() if a is not None]
    unowned = [a for a in apps if a.package is None]
    # dpkg-query may return status 1 if some local launchers have no package owner;
    # the successful lines still provide valid ownership for all other launchers.
    if unowned and shutil.which('dpkg-query'):
        try:
            p = subprocess.run(['dpkg-query', '-S', *[a.desktop_file for a in unowned]], capture_output=True, text=True, timeout=30)
            owners = {}
            for line in p.stdout.splitlines():
                if ': /' in line:
                    names, path = line.split(': /', 1)
                    names = names.split(', ')
                    if len(names) == 1:
                        owners['/' + path] = names[0]
            for a in unowned:
                a.package = by_name.get(('apt', owners.get(a.desktop_file, '')))
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append('Не удалось определить способ удаления некоторых приложений: '+str(e))
    # On other distros, an unverified launcher remains visible, without an uninstall action.
    seen = set()
    result = []
    for a in sorted(apps, key=lambda x: x.name.casefold()):
        key = (a.name.casefold(), a.package.manager if a.package else '', a.package.name if a.package else a.desktop_file)
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result, errors


def protected_reason(app):
    if app.package is None:
        return 'Не удалось достоверно определить, как установлена эта программа. OpenCare не будет угадывать команду удаления. Удалите её через магазин приложений или средство, которым вы её устанавливали.'
    name = app.package.name.split(':')[0]
    if name in {'nemo', 'cinnamon', 'cinnamon-common', 'cinnamon-session', 'cinnamon-settings-daemon',
                'cinnamon-control-center', 'muffin', 'lightdm', 'slick-greeter', 'mintupdate',
                'mintinstall', 'mintsystem', 'mint-common', 'network-manager', 'network-manager-gnome',
                'gnome-shell', 'gnome-session', 'plasma-desktop', 'plasma-workspace', 'xfce4-session',
                'apt', 'dpkg', 'systemd', 'sudo', 'policykit-1', 'polkitd'} or name.startswith(('mint-meta-', 'linux-image-')):
        return 'Это часть рабочего стола или системного управления Linux. Её удаление через OpenCare отключено, чтобы не нарушить работу компьютера. Для изменения таких компонентов нужен отдельный системный инструмент.'
    return ''
