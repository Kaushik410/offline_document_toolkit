"""Workspace backup, restore and explicit, reference-aware storage cleanup."""
from pathlib import Path
import os
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,
    QFileDialog,QMessageBox,QTabWidget,QWidget)
from services.storage_service import inspect_storage,cleanup_storage
from services.project_archive import backup_workspace,restore_workspace
from utils.app_config import AppConfig
from utils.task_controller import run_task,cancel_tasks


class StorageDialog(QDialog):
    projectDeleted=Signal(str)
    def __init__(self,store,queue,parent=None):
        super().__init__(parent);self.store=store;self.queue=queue
        self.setWindowTitle('Workspace storage and backups');self.resize(800,570)
        layout=QVBoxLayout(self)
        self.summary=QLabel('Calculating storage…');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        layout.addWidget(QLabel('Backups contain original snapshots, undo history, recipes, and local job state. Exported packets stay separate.'))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        self.projects=QListWidget();tabs.addTab(self.projects,'Projects')
        self.jobs=QListWidget();tabs.addTab(self.jobs,'Job history')
        remove=QPushButton('Delete selected history entry…');layout.addWidget(remove)
        remove.clicked.connect(lambda:self.remove(tabs.currentIndex()))
        row=QHBoxLayout();layout.addLayout(row)
        for label,callback in [('Back up workspace…',self.backup),('Restore backup…',self.restore),
                               ('Clean unused cache…',self.cleanup),('Refresh',self.refresh),('Close',self.accept)]:
            button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        self.refresh()

    def refresh(self):
        self.project_rows=self.store.projects();self.job_rows=self.store.jobs()
        self.projects.clear();self.projects.addItems([row['name'] for row in self.project_rows])
        self.jobs.clear();self.jobs.addItems([row['title']+' — '+row['state'] for row in self.job_rows])
        def complete(report):
            self.summary.setText(f"Managed files: {report['managed_bytes']/1024**2:.1f} MiB • database: {report['database_bytes']/1024**2:.1f} MiB\n"
                f"Unreferenced cache older than 24 hours: {report['reclaimable_bytes']/1024**2:.1f} MiB. Undo history and retained jobs are protected.")
        run_task(self,inspect_storage,str(self.store.path),on_success=complete,show_progress=False)

    def remove(self,index):
        rows=self.project_rows if index==0 else self.job_rows
        current=(self.projects if index==0 else self.jobs).currentRow()
        if current<0:return
        row=rows[current]
        if QMessageBox.question(self,'Delete history entry','Delete this saved history entry? Original input files and published exports are preserved.')!=QMessageBox.Yes:return
        try:
            if index==0:self.store.delete_project(row['id']);self.projectDeleted.emit(row['id'])
            else:self.store.delete_job(row['id'])
        except ValueError as error:QMessageBox.information(self,'Stop the job first',str(error))
        self.refresh()

    def cleanup(self):
        if QMessageBox.question(self,'Clean unused cache','Remove only unreferenced managed cache files older than 24 hours?')!=QMessageBox.Yes:return
        run_task(self,cleanup_storage,str(self.store.path),on_success=lambda result:self.refresh(),task_title='Cleaning unused cache')

    def backup(self):
        if any(row['state']=='running' for row in self.store.jobs()):
            QMessageBox.information(self,'Pause jobs first','Pause running jobs before backing up the workspace.');return
        path,_=QFileDialog.getSaveFileName(self,'Back up workspace','workspace.odtbackup','Workspace backup (*.odtbackup)')
        from utils.file_dialog_utils import normalize_output_selection
        path=normalize_output_selection(self,path,'.odtbackup')
        if not path:return
        self.queue.timer.stop()
        def complete(result):
            self.queue.timer.start();QMessageBox.information(self,'Backup complete',result)
        if not run_task(self,backup_workspace,str(self.store.path),path,on_success=complete,task_title='Backing up workspace'):
            self.queue.timer.start()

    def restore(self):
        if any(row['state']=='running' for row in self.store.jobs()):
            QMessageBox.information(self,'Pause jobs first','Pause running jobs before restoring a workspace.');return
        path,_=QFileDialog.getOpenFileName(self,'Restore workspace','','Workspace backup (*.odtbackup)')
        if not path:return
        destination=QFileDialog.getExistingDirectory(self,'Choose a new, empty workspace folder')
        if not destination:return
        def complete(folder):
            config=AppConfig.load_config();config['workspace_directory']=folder;config.pop('last_project',None);AppConfig.save_config(config)
            if os.environ.get('ODT_DATA_DIR'):
                QMessageBox.information(self,'Workspace restored','Restart with ODT_DATA_DIR set to:\n'+folder)
            else:
                QMessageBox.information(self,'Workspace restored','The app will close. Open it again to use the restored workspace. Queued jobs restore as paused.')
                self.accept();self.parent().window().close()
        run_task(self,restore_workspace,path,destination,on_success=complete,task_title='Restoring workspace')

    def done(self,result):
        cancel_tasks(self)
        if self.queue.running:self.queue.timer.start()
        super().done(result)
