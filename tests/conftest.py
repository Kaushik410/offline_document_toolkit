import os
from pathlib import Path
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('ODT_NO_SETUP', '1')
os.environ.setdefault('ODT_CONFIG_DIR', str(Path(tempfile.gettempdir()) / 'odt-tests-config'))
os.environ.setdefault('ODT_OUTPUT_DIR', str(Path(tempfile.gettempdir()) / 'odt-tests-output'))

import pytest
from PIL import Image, ImageDraw, ImageFont
import fitz


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    from utils.task_controller import shutdown_tasks
    from utils.qt_runtime import configure_qt_plugins
    configure_qt_plugins()
    app = QApplication.instance() or QApplication([])
    yield app
    shutdown_tasks()


@pytest.fixture
def image(tmp_path):
    path = tmp_path / 'sample.png'
    image = Image.new('RGB', (900, 200), 'white')
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 42)
    except OSError:
        font = ImageFont.load_default(size=42)
    ImageDraw.Draw(image).text((25, 60), 'DOCUMENT TOOLKIT TEST', font=font, fill='black')
    image.save(path)
    return path


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / 'sample.pdf'
    with fitz.open() as document:
        for index in range(3):
            page = document.new_page(width=400, height=500)
            page.insert_text((30, 90), f'DOCUMENT TOOLKIT TEST PAGE {index + 1}', fontsize=16)
        document.save(path)
    return path


def wait_until(qapp, predicate, timeout=15):
    import time
    from PySide6.QtTest import QTest
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert predicate(), 'Background operation timed out'


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ODT_DATA_DIR", str(tmp_path / "workspace-state"))


@pytest.fixture(autouse=True)
def unexpected_gui_errors_fail_without_a_modal_dialog(monkeypatch):
    # A worker error otherwise opens a modal window inside processEvents(),
    # blocking the headless test before its wait timeout can run.
    from PySide6.QtWidgets import QMessageBox
    errors=[]
    def record_error(parent,title,message,*args,**kwargs):
        errors.append(f'{title}: {message}')
        return QMessageBox.StandardButton.Ok
    monkeypatch.setattr(QMessageBox,'critical',record_error)
    yield
    assert not errors,'Unexpected GUI errors: '+'; '.join(errors)
