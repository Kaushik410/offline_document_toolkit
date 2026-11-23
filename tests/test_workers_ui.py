import os
from pathlib import Path
import time
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from tests.conftest import wait_until
from tests.worker_helpers import slow_output, process_identity
from utils.task_controller import run_task, shutdown_tasks


def test_worker_process_isolated_from_gui_and_delivers_result(qapp):
    parent=QWidget();results=[]
    run_task(parent,process_identity,on_success=results.append,show_progress=False)
    wait_until(qapp,lambda:bool(results))
    assert results[0] != os.getpid()
    parent.close()


def test_cancel_stops_current_operation_and_removes_partial_output(qapp,tmp_path):
    parent=QWidget();output=tmp_path/'result.txt';output.write_text('original')
    results=[];statuses=[];ticks=[]
    timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
    run_task(parent,slow_output,str(output),on_success=results.append,show_progress=False)
    controller=parent._task_controller
    controller.worker.signals.status.connect(statuses.append)
    wait_until(qapp,lambda:bool(statuses))
    started=time.monotonic();controller.cancel()
    wait_until(qapp,lambda:controller.worker is None,timeout=5)
    timer.stop()
    assert time.monotonic()-started < 5
    assert ticks and not results
    assert output.read_text() == 'original'
    assert not list(tmp_path.glob('.odt-*'))
    if os.name == 'posix':
        pid=int(statuses[0])
        state=Path(f'/proc/{pid}/stat')
        if state.exists():
            assert state.read_text().split()[2] == 'Z', 'Engine child survived cancellation'
    parent.close()


def test_gui_save_honors_current_compression_quality(qapp,tmp_path):
    from ui.image_editor_dialog import ImageEditorDialog
    source=tmp_path/'noise.jpg'
    Image.effect_noise((400,400),80).convert('RGB').save(source,quality=95)
    dialog=ImageEditorDialog(str(source),'compress')
    wait_until(qapp,lambda:dialog._task_controller.worker is None)
    with patch('ui.image_editor_dialog.QMessageBox.information'):
        for quality in [10,95]:
            dialog.widgets['quality'].setValue(quality)
            output=tmp_path/f'quality-{quality}.jpg'
            with patch('ui.image_editor_dialog.QFileDialog.getSaveFileName',return_value=(str(output),'')):
                dialog.save_output()
                wait_until(qapp,lambda:dialog._task_controller.worker is None)
    assert (tmp_path/'quality-10.jpg').stat().st_size < (tmp_path/'quality-95.jpg').stat().st_size
    dialog.close()


def test_main_window_and_preview_dialogs(qapp,pdf):
    from ui.main_window import MainWindow
    from ui.pdf_organizer_dialog import PDFOrganizerDialog
    from ui.ocr_preview_dialog import OCRPagePreviewDialog
    window=MainWindow()
    assert window.stack.count() == 10
    assert window.stack.currentWidget() is window.workspace_page
    wait_until(qapp,lambda:window.settings_page._task_controller.worker is None)
    organizer=PDFOrganizerDialog(str(pdf))
    wait_until(qapp,lambda:len(organizer.preview_cache)>0 and organizer._task_controller.worker is None)
    assert organizer.thumbnail_list.count() == 3
    organizer.move_page_down()
    wait_until(qapp,lambda:organizer._task_controller.worker is None)
    assert organizer.page_order == [1,0,2]
    preview=OCRPagePreviewDialog(str(pdf))
    wait_until(qapp,lambda:preview._task_controller.worker is None)
    preview.text_box.setPlainText('Edited text')
    preview.next_page()
    wait_until(qapp,lambda:preview._task_controller.worker is None)
    assert preview.page_texts[0] == 'Edited text'
    preview.close();organizer.close();window.close()


def test_entrypoint_preserves_selected_qt_platform(monkeypatch):
    import main
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'
    assert not hasattr(main,'PYSIDE6_DIR')
