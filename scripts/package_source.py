"""Build a source archive from an explicit allowlist, excluding user data."""
import argparse
from pathlib import Path
import zipfile

FILES = {'main.py','pyproject.toml','README.md','LICENSE','THIRD_PARTY_NOTICES.md',
         'requirements.txt','requirements-dev.txt','requirements-build.txt',
         'MANIFEST.in','OfflineDocumentToolkit.spec','app_settings.example.json','.gitignore'}
DIRECTORIES = {'services','ui','utils','scripts','tests','examples'}


def source_files(root):
    files = [root/name for name in FILES]
    for directory in DIRECTORIES:
        files.extend(path for path in (root/directory).rglob('*.py') if '__pycache__' not in path.parts)
    files.extend(root/name for name in ['.github/workflows/ci.yml',
        '.github/workflows/installers.yml', 'packaging/windows.iss',
        'packaging/offline-document-toolkit.desktop', 'assets/document-toolkit.svg',
        'packaging/baseline/manifest.json', 'packaging/baseline/0.4.0-source.zip',
        'packaging/verify-windows-signature.ps1'])
    if any(path.is_symlink() for path in files):
        raise ValueError('Source archives must not contain symbolic links.')
    return sorted(files)


def package(root, output):
    files=source_files(root)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path,Path('offline-document-toolkit')/path.relative_to(root))
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('release/offline-document-toolkit-source.zip'))
    args=parser.parse_args()
    print(package(Path(__file__).resolve().parents[1],args.output))
