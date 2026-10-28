import argparse
import dataclasses
import json
import os
from . import core as c


def main():
    parser = argparse.ArgumentParser(description='OpenCare — свободное обслуживание Linux')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('info', help='Сведения о системе (JSON)')
    scan = sub.add_parser('scan', help='Только просканировать, без изменения файлов')
    scan.add_argument('--category', action='append', choices=['cache', 'trash', 'privacy'])
    scan.add_argument('--days', type=int, default=7)
    sub.add_parser('packages', help='Установленные пакеты')
    sub.add_parser('startup', help='Записи автозагрузки')
    sub.add_parser('journal', help='Журнал изменений')
    snap = sub.add_parser('snapshot', help='Создать снимок каталога')
    snap.add_argument('directory')
    snap.add_argument('--label', default='')
    args = parser.parse_args()
    if not args.command:
        from .gui import main as gui_main
        gui_main()
        return
    if os.geteuid() == 0:
        parser.error('Запускайте OpenCare от обычного пользователя, не от root.')
    env = c.Environment()
    try:
        if args.command == 'info':
            result = c.summary(env)
        elif args.command == 'scan':
            files, errors = c.Cleaner(env).scan(args.category or ['cache'], args.days)
            result = {'files': [dataclasses.asdict(f) for f in files], 'errors': errors,
                      'total_bytes': sum(f.size for f in files)}
        elif args.command == 'packages':
            pkgs, errors = c.packages()
            result = {'packages': [dataclasses.asdict(p) for p in pkgs], 'errors': errors}
        elif args.command == 'startup':
            result = c.Startup(env).list()
        elif args.command == 'journal':
            result = c.Journal(env).records()
        else:
            result = c.snapshot(env, args.directory, args.label)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (c.CareError, OSError, ValueError) as e:
        parser.exit(1, f'Ошибка: {e}\n')


if __name__ == '__main__':
    main()
