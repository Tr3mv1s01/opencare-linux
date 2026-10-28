"""Build a source release from an explicit allowlist, without user state or caches."""
from pathlib import Path
import hashlib
import runpy
import zipfile

root = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(root / 'opencare/__init__.py'))['__release_version__']
allowed_files = ['README.md', 'LICENSE', 'CHANGELOG.md', 'CONTRIBUTING.md',
                 'pyproject.toml', 'run.sh', '.gitignore', '.gitattributes']
allowed_dirs = ['opencare', 'tests', 'docs', 'packaging']
files = [root / name for name in allowed_files if (root / name).is_file()]
for directory in allowed_dirs:
    files.extend(p for p in (root / directory).rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.zip'))
files = sorted(files)
(root / 'SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n' for p in files))
archive = root.parent / f'OpenCare-Linux-{version}.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in [*files, root / 'SHA256SUMS']:
        z.write(p, Path('opencare') / p.relative_to(root))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
print(archive)
print(f'{archive.stat().st_size} bytes')
