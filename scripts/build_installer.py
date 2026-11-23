"""Package a frozen application into an OS installer; never install system software."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import tomllib

ROOT=Path(__file__).resolve().parents[1]


def build_linux(source,output,with_engines=True):
    version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    architecture=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
    output.mkdir(parents=True,exist_ok=True)
    target=output/f'offline-document-toolkit_{version}_{architecture}.deb'
    with tempfile.TemporaryDirectory(prefix='odt-deb-') as directory:
        package=Path(directory)
        shutil.copytree(source,package/'opt/offline-document-toolkit',symlinks=True)
        control=package/'DEBIAN';control.mkdir()
        dependencies=['libegl1','libopengl0','libxcb-cursor0','libxkbcommon-x11-0']
        if with_engines:dependencies+=['tesseract-ocr','tesseract-ocr-eng','tesseract-ocr-hin','ghostscript','libreoffice-writer']
        (control/'control').write_text(f'Package: offline-document-toolkit\nVersion: {version}\n'
            f'Architecture: {architecture}\nMaintainer: Offline Document Toolkit contributors\n'
            f'Depends: {", ".join(dependencies)}\nSection: utils\nPriority: optional\n'
            'Description: Local document workspace, OCR, and submission workflows\n')
        desktop=package/'usr/share/applications';desktop.mkdir(parents=True)
        shutil.copyfile(ROOT/'packaging/offline-document-toolkit.desktop',desktop/'offline-document-toolkit.desktop')
        icons=package/'usr/share/icons/hicolor/scalable/apps';icons.mkdir(parents=True)
        shutil.copyfile(ROOT/'assets/document-toolkit.svg',icons/'offline-document-toolkit.svg')
        docs=package/'usr/share/doc/offline-document-toolkit';docs.mkdir(parents=True)
        shutil.copyfile(ROOT/'LICENSE',docs/'copyright')
        subprocess.run(['dpkg-deb','--root-owner-group','-Zxz','-z1','--build',str(package),str(target)],check=True)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'release/desktop/OfflineDocumentToolkit')
    parser.add_argument('--output',type=Path,default=ROOT/'release/installers')
    parser.add_argument('--without-engines',action='store_true',help='Linux: omit system engine dependencies')
    args=parser.parse_args()
    if not args.source.exists():
        raise SystemExit('Build the frozen application first (see README).')
    if platform.system()=='Linux':print(build_linux(args.source,args.output,not args.without_engines))
    elif platform.system()=='Windows':
        version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
        compiler=shutil.which('iscc') or 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe'
        subprocess.run([compiler,f'/DSourceDir={args.source.resolve()}',f'/DOutputDir={args.output.resolve()}',
                        f'/DAppVersion={version}',str(ROOT/'packaging/windows.iss')],check=True)
    else:raise SystemExit('Native installers are supported on Linux and Windows.')


if __name__=='__main__':main()
