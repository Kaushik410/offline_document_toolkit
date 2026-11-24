# Build separately on each target OS. System OCR/conversion engines stay external.
from PyInstaller.utils.hooks import copy_metadata

metadata = []
for distribution in ['PySide6', 'PySide6_Addons', 'PySide6_Essentials', 'shiboken6',
                     'pypdf', 'PyMuPDF', 'Pillow', 'opencv-python-headless',
                     'pytesseract', 'python-docx', 'numpy', 'lxml', 'packaging',
                     'typing_extensions']:
    metadata += copy_metadata(distribution)

a = Analysis(['main.py'], pathex=[], binaries=[],
    datas=[('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('README.md', '.'),
           ('assets/document-toolkit.svg', 'assets')] + metadata,
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pandas', 'matplotlib', 'pytest', 'IPython', 'tkinter'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OfflineDocumentToolkit',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OfflineDocumentToolkit')
