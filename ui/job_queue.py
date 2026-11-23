"""Persistent jobs run independently of the currently selected screen."""
from pathlib import Path
import uuid
from PySide6.QtCore import QObject,QTimer,QThreadPool,Signal,Slot
from services.workspace_store import WorkspaceStore,data_directory
from services.workflow_service import execute_workflow
from utils.task_worker import TaskWorker


class JobQueue(QObject):
    changed=Signal()
    def __init__(self,store=None,parent=None):
        super().__init__(parent)
        self.store=store or WorkspaceStore();self.owner=uuid.uuid4().hex
        self.worker=None;self.current_id=None;self.stop_state='paused';self.running=True
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.tick)
        self.timer.start()

    def directory(self,job_id):return self.store.path.parent/'jobs'/job_id

    @Slot()
    def tick(self):
        if not self.running:return
        if not self.store.acquire(self.owner):return
        if self.worker:return
        job=self.store.claim(self.owner)
        if not job:return
        self.current_id=job['id']
        self.worker=TaskWorker(execute_workflow,job['spec'],str(self.directory(job['id'])))
        self.worker.signals.finished.connect(self.finished)
        self.worker.signals.error.connect(self.failed)
        self.worker.signals.cancelled.connect(self.cancelled)
        self.worker.signals.progress.connect(self.progress)
        self.worker.signals.status.connect(self.status)
        QThreadPool.globalInstance().start(self.worker);self.changed.emit()

    @Slot(int)
    def progress(self,value):
        if self.current_id:self.store.update_job(self.current_id,progress=value)
        self.changed.emit()

    @Slot(str)
    def status(self,value):
        if self.current_id:self.store.update_job(self.current_id,message=value)
        self.changed.emit()

    @Slot(object)
    def finished(self,result):
        self.store.update_job(self.current_id,state=result['state'],result=result,error='',progress=100,message=result['message'],owner=None)
        self.worker=None;self.current_id=None;self.changed.emit()
        if not self.running:self.store.release(self.owner)

    @Slot(str)
    def failed(self,error):
        self.store.update_job(self.current_id,state='failed',error=error,message='Failed; retry resumes completed stages',owner=None)
        self.worker=None;self.current_id=None;self.changed.emit()
        if not self.running:self.store.release(self.owner)

    @Slot()
    def cancelled(self):
        self.store.update_job(self.current_id,state=self.stop_state,message='Stopped; completed stages retained',owner=None)
        self.worker=None;self.current_id=None;self.changed.emit()
        if not self.running:self.store.release(self.owner)

    def stop(self,job_id,state='paused'):
        if self.current_id==job_id and self.worker:
            self.stop_state=state;self.worker.cancel()
        else:self.store.update_job(job_id,state=state,message='Stopped before processing')
        self.changed.emit()

    def shutdown(self):
        self.running=False;self.timer.stop()
        if self.worker:
            self.stop_state='interrupted';self.worker.cancel()
        else:self.store.release(self.owner)
