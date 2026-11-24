from pathlib import Path
import json
from PySide6.QtCore import Qt,QTimer,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QHeaderView,
    QLabel,QPushButton,QTextEdit,QMessageBox,QSplitter,QGridLayout)
from ui.ocr_review_dialog import OCRReviewDialog
from services.workflow_service import approve_export


class JobsPage(QWidget):
    def __init__(self,store,queue,parent=None):
        super().__init__(parent);self.store=store;self.queue=queue
        layout=QVBoxLayout(self);title=QLabel('Jobs and export review');title.setObjectName('TitleLabel');layout.addWidget(title)
        split=QSplitter(Qt.Vertical);layout.addWidget(split,1)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Job','State','Progress','Status'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers);split.addWidget(self.table)
        self.details=QTextEdit();self.details.setReadOnly(True);split.addWidget(self.details)
        buttons=QGridLayout();layout.addLayout(buttons)
        for index,(label,callback) in enumerate([('Pause',lambda:self.stop('paused')),('Cancel',lambda:self.stop('cancelled')),
            ('Resume / retry',self.retry),('Review OCR',self.review),('Review packet',self.open_staged),
            ('Approve and export',self.approve),('Open export folder',self.open_output)]):
            button=QPushButton(label);button.clicked.connect(callback);buttons.addWidget(button,index//4,index%4)
        self.table.itemSelectionChanged.connect(self.show_details)
        queue.changed.connect(self.refresh)
        self.timer=QTimer(self);self.timer.setInterval(2500);self.timer.timeout.connect(self.refresh);self.timer.start()
        self.refresh()

    def selected_id(self):
        item=self.table.item(self.table.currentRow(),0)
        return item.data(Qt.UserRole) if item else None

    def refresh(self):
        selected=self.selected_id();self.table.blockSignals(True);self.table.setRowCount(0)
        for job in self.store.jobs():
            row=self.table.rowCount();self.table.insertRow(row)
            for col,value in enumerate([job['title'],job['state'],f"{job['progress']}%",job['message']]):
                item=QTableWidgetItem(str(value));item.setData(Qt.UserRole,job['id']);self.table.setItem(row,col,item)
            if job['id']==selected:self.table.selectRow(row)
        self.table.blockSignals(False)
        if self.table.currentRow()<0 and self.table.rowCount():self.table.selectRow(0)
        self.show_details()

    def show_details(self):
        job_id=self.selected_id()
        if not job_id:return
        job=self.store.job(job_id);lines=[job['title'],f"State: {job['state']} • attempts: {job['attempts']}",job['message']]
        if job['error']:lines.extend(['',job['error']])
        result=job['result']
        if result:
            for report in result.get('reports',[]):
                lines.extend(['',report['summary']])
                for check in report['checks']:lines.append(('✓ ' if check['passed'] else '✗ ')+check['name']+': '+check['detail'])
                if report.get('reason'):lines.append(report['reason'])
                if report.get('quality'):lines.append(f"Image quality {report['quality']}, resolution {report.get('dpi')} DPI")
            lines.extend(['','Exports:']+result.get('outputs',[]))
        self.details.setPlainText('\n'.join(lines))

    def stop(self,state):
        job_id=self.selected_id()
        if job_id and self.store.job(job_id)['state'] in ('queued','running'):self.queue.stop(job_id,state)

    def retry(self):
        job_id=self.selected_id()
        if not job_id:return
        try:self.store.retry(job_id)
        except ValueError as error:QMessageBox.information(self,'Job status',str(error))
        self.refresh()

    def review(self):
        job_id=self.selected_id()
        if not job_id:return
        result=self.store.job(job_id)['result'] or {}
        path=result.get('review_file')
        if not path:QMessageBox.information(self,'OCR review','This job has no OCR review data yet.');return
        OCRReviewDialog(path,self).exec()

    def open_staged(self):
        from services.review_service import prepare_packet_review
        from ui.document_review_dialog import DocumentReviewDialog
        from utils.task_controller import run_task
        job_id=self.selected_id()
        if not job_id:return
        job=self.store.job(job_id);result=job['result'] or {}
        staged=result.get('staged',[])
        if not staged:return
        def corrected():
            if self.store.job(job_id)['state']=='needs_review':
                self.store.retry(job_id);self.refresh()
        def complete(comparison):
            dialog=DocumentReviewDialog(comparison['before'],comparison['after'],comparison['pages'],
                review_file=result.get('review_file') if job['state']=='needs_review' else None,
                approve=(lambda:self.approve(job_id)) if job['state']=='needs_review' else None,
                ocr_changed=corrected,parent=self,viewer_before=comparison.get('viewer_before'),viewer_after=comparison.get('viewer_after'))
            dialog.exec()
        run_task(self,prepare_packet_review,job['spec']['document'],staged,str(self.queue.directory(job_id)/'review'),
            on_success=complete,task_title='Preparing packet comparison')

    def approve(self,job_id=None):
        job_id=job_id if isinstance(job_id,str) else self.selected_id()
        if not job_id:return
        job=self.store.job(job_id);result=job['result'] or {}
        if job['state']!='needs_review':return
        if not result.get('ready_to_export'):
            if result.get('review_file'):
                review=json.loads(Path(result['review_file']).read_text())
                if not review.get('approved') and review['uncertain_words']:
                    QMessageBox.information(self,'OCR review required','Review and approve the uncertain words first.');return
            if not all(report['passed'] for report in result.get('reports',[])):
                QMessageBox.information(self,'Requirements not met','Adjust the workflow requirements or remove pages, then queue a new job.');return
        approve_export(self.queue.directory(job_id));self.store.retry(job_id);self.refresh();return True

    def open_output(self):
        job_id=self.selected_id()
        if job_id:
            outputs=(self.store.job(job_id)['result'] or {}).get('outputs',[])
            if outputs:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(outputs[0]).parent)))
