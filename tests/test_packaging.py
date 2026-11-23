import zipfile
from pathlib import Path
from scripts.package_source import package


def test_source_package_excludes_private_documents(tmp_path):
    root=Path(__file__).resolve().parents[1]
    archive=package(root,tmp_path/'source.zip')
    with zipfile.ZipFile(archive) as source:
        names=source.namelist()
        assert any(name.endswith('/main.py') for name in names)
        assert any(name.endswith('/LICENSE') for name in names)
        assert any(name.endswith('/packaging/windows.iss') for name in names)
        assert any(name.endswith('/assets/document-toolkit.svg') for name in names)
        assert any(name.endswith('/.github/workflows/installers.yml') for name in names)
        assert not any('/local_data/' in name or name.endswith('app_settings.json') for name in names)
        assert not any(Path(name).suffix.lower() in {'.pdf','.docx','.png','.jpg','.jpeg','.bmp'} for name in names)


def test_linux_installer_contains_native_launcher_and_engine_dependencies(tmp_path):
    import shutil
    import subprocess
    import pytest
    from scripts.build_installer import build_linux
    if not shutil.which('dpkg-deb'):pytest.skip('Debian packaging tools unavailable')
    bundle=tmp_path/'bundle';bundle.mkdir();launcher=bundle/'OfflineDocumentToolkit'
    launcher.write_text('#!/bin/sh\nexit 0\n');launcher.chmod(0o755)
    package=build_linux(bundle,tmp_path/'installers')
    control=subprocess.check_output(['dpkg-deb','--field',str(package)],text=True)
    assert 'Version: 0.4.1' in control and 'tesseract-ocr-hin' in control and 'libreoffice-writer' in control
    for dependency in ('libxcb-cursor0','libxkbcommon-x11-0','libxcb-icccm4','libxcb-shape0','libxcb-keysyms1'):
        assert dependency in control
    subprocess.run(['dpkg-deb','--extract',str(package),str(tmp_path/'extracted')],check=True)
    assert (tmp_path/'extracted/opt/offline-document-toolkit/OfflineDocumentToolkit').is_file()
    desktop=tmp_path/'extracted/usr/share/applications/offline-document-toolkit.desktop'
    assert 'Exec=/opt/offline-document-toolkit/OfflineDocumentToolkit %F' in desktop.read_text()
