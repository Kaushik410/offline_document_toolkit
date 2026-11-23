"""Qt-facing task lifecycle; callbacks always run on the GUI thread."""
from PySide6.QtCore import QObject, QThreadPool, Qt, Slot
from PySide6.QtWidgets import QProgressDialog, QMessageBox
from utils.task_worker import TaskWorker


_active = set()


class TaskController(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.worker = None
        self.dialog = None
        self.on_success = None
        parent.destroyed.connect(self.parent_gone)

    def parent_gone(self):
        if self.worker:
            self.worker.cancel()
        self.on_success = None
        _active.discard(self)

    def start(self, task_fn, *args, on_success=None, task_title="Processing document",
              show_progress=True, **kwargs):
        if self.worker is not None:
            return False
        self.on_success = on_success
        self.worker = TaskWorker(task_fn, *args, **kwargs)
        self.worker.signals.finished.connect(self.finished)
        self.worker.signals.error.connect(self.failed)
        self.worker.signals.cancelled.connect(self.cancelled)
        if show_progress:
            self.dialog = QProgressDialog(task_title + "…", "Cancel", 0, 0, self.parent())
            self.dialog.setWindowTitle(task_title)
            self.dialog.setWindowModality(Qt.WindowModal)
            self.dialog.setMinimumDuration(0)
            self.dialog.setAutoClose(False)
            self.dialog.setAutoReset(False)
            self.dialog.canceled.connect(self.cancel)
            self.worker.signals.progress.connect(self.progress)
            self.worker.signals.status.connect(self.dialog.setLabelText)
            self.dialog.show()
        _active.add(self)
        QThreadPool.globalInstance().start(self.worker)
        return True

    @Slot(int)
    def progress(self, value):
        if self.dialog:
            self.dialog.setRange(0, 100)
            self.dialog.setValue(min(value, 99))

    @Slot()
    def cancel(self):
        if self.worker:
            self.worker.cancel()
            if self.dialog:
                self.dialog.setLabelText("Cancelling…")
                self.dialog.setCancelButton(None)
                self.dialog.show()

    def reset(self):
        if self.dialog:
            self.dialog.canceled.disconnect(self.cancel)
            self.dialog.close()
            self.dialog.deleteLater()
        self.dialog = None
        self.worker = None
        callback, self.on_success = self.on_success, None
        _active.discard(self)
        return callback

    @Slot(object)
    def finished(self, result):
        was_cancelled = self.worker is not None and self.worker.is_cancelled()
        callback = self.reset()
        if callback and not was_cancelled:
            try:
                callback(result)
            except Exception as error:
                QMessageBox.critical(self.parent(), "Result error", str(error))

    @Slot(str)
    def failed(self, message):
        self.reset()
        QMessageBox.critical(self.parent(), "Operation failed", message)

    @Slot()
    def cancelled(self):
        self.reset()


def run_task(parent, task_fn, *args, **kwargs):
    if not hasattr(parent, "_task_controller"):
        parent._task_controller = TaskController(parent)
    return parent._task_controller.start(task_fn, *args, **kwargs)


def cancel_tasks(parent):
    for controller in tuple(_active):
        owner = controller.parent()
        if owner is parent or parent.isAncestorOf(owner):
            controller.cancel()


def shutdown_tasks():
    for controller in tuple(_active):
        controller.cancel()
    QThreadPool.globalInstance().waitForDone()
