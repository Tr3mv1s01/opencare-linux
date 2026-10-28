"""Host integration check. --toggle-settings temporarily flips and restores desktop
preferences. This option must be run only with the computer owner's authorization.
Does not remove packages or clean actual user data.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opencare import core as c

parser = argparse.ArgumentParser()
parser.add_argument('--toggle-settings', action='store_true')
args = parser.parse_args()
report = {'system': c.desktop_info(), 'checks': {}}
with tempfile.TemporaryDirectory(prefix='opencare-machine-') as temp:
    env = c.Environment(state=Path(temp) / 'journal-state')
    packages, errors = c.packages()
    report['checks']['packages'] = {'count': len(packages), 'errors': errors}
    report['checks']['startup'] = {'count': len(c.Startup(env).list())}
    files, errors = c.Cleaner(env).scan(['cache'], 7)
    report['checks']['cache_readonly'] = {'files': len(files), 'bytes': sum(x.size for x in files), 'skipped_roots': len(errors)}
    files, errors = c.config_files(env)
    report['checks']['config_readonly'] = {'files': len(files), 'warnings': len(errors)}
    settings = c.available_settings()
    report['checks']['settings'] = {'count': len(settings), 'desktop': c.desktop_info()['desktop'], 'roundtrips': []}
    if args.toggle_settings:
        from gi.repository import Gio
        for name, schema, key, typ, initial in settings:
            gio = Gio.Settings.new(schema)
            user_value = gio.get_user_value(key)
            record = None
            try:
                target = 'false' if initial == 'true' else 'true'
                record = c.set_setting(env, schema, key, target)
                assert c.run(['gsettings', 'get', schema, key]).strip() == target
                c.restore_setting(env, record)
                assert c.run(['gsettings', 'get', schema, key]).strip() == initial
            finally:
                # Restore both effective value and absence/presence of original user override.
                if user_value is None:
                    c.run(['gsettings', 'reset', schema, key])
                else:
                    c.run(['gsettings', 'set', schema, key, user_value.print_(True)])
                assert c.run(['gsettings', 'get', schema, key]).strip() == initial
            report['checks']['settings']['roundtrips'].append({'setting': name, 'key': schema+'.'+key, 'result': 'changed, read back, restored'})
    print(json.dumps(report, ensure_ascii=False, indent=2))
