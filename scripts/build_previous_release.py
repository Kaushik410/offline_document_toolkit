"""Build the audited previous source snapshot for a genuine package-version upgrade."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def unpack_baseline(destination,manifest_path=None):
    manifest_path=Path(manifest_path) if manifest_path else ROOT/'packaging/baseline/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    source=manifest_path.parent/manifest['file']
    if hashlib.sha256(source.read_bytes()).hexdigest()!=manifest['sha256']:
        raise ValueError('Previous source snapshot checksum does not match the audited baseline.')
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):raise ValueError('Use an empty baseline build folder.')
    with zipfile.ZipFile(source) as archive:
        records=archive.infolist()
        if len(records)>5000 or sum(row.file_size for row in records)>32*1024**2:
            raise ValueError('Unexpectedly large baseline source archive.')
        for row in records:
            path=PurePosixPath(row.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in row.filename or (row.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe baseline source path.')
        archive.extractall(destination)
    return destination/'offline-document-toolkit',manifest


def build(output,manifest_path=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='odt-previous-source-') as directory:
        source,manifest=unpack_baseline(directory,manifest_path)
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--workpath',str(Path(directory)/'work'),
            '--distpath',str(Path(directory)/'desktop'),'OfflineDocumentToolkit.spec'],cwd=source,check=True)
        subprocess.run([sys.executable,'scripts/build_installer.py','--source',str(Path(directory)/'desktop/OfflineDocumentToolkit'),
            '--output',str(output)],cwd=source,check=True)
    result={'version':manifest['version'],'source_sha256':manifest['sha256'],
            'installers':[path.name for path in output.iterdir() if path.suffix in ('.deb','.exe')]}
    (output/'baseline-build.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'release/previous-installer')
    args=parser.parse_args();print(json.dumps(build(args.output)))
