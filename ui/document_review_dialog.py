"""Embedded PDF review, synchronized navigation, search and difference overlays."""
from pathlib import Path
from PySide6.QtCore import Qt,QPointF,QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument,QPdfSearchModel
from shiboken6 import delete
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QSplitter,QLabel,QPushButton,
    QSpinBox,QDoubleSpinBox,QLineEdit,QListWidget,QTabWidget,QWidget,QScrollArea,QMessageBox)
from PIL.ImageQt import ImageQt
from ui.ocr_review_dialog import OCRReviewDialog
from services.review_service import render_difference
from utils.task_controller import run_task,cancel_tasks


class DocumentReviewDialog(QDialog):
    def __init__(self,before,after,comparison=None,review_file=None,initial_page=0,query='',approve=None,ocr_changed=None,parent=None,viewer_before=None,viewer_after=None):
        super().__init__(parent)
        self.setWindowTitle('Review document packet');self.resize(1250,850)
        self.before=before;self.after=after;self.comparison=comparison or []
        self.approval=approve;self.ocr_changed=ocr_changed;self.review_file=review_file
        self.views=[];self.documents=[];self.models=[]
        self.diff_owner=QWidget(self);self.diff_generation=0;self.closing=False
        layout=QVBoxLayout(self)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        toolbar.addWidget(QLabel('Page'))
        self.page=QSpinBox();self.page.setMinimum(1);toolbar.addWidget(self.page)
        toolbar.addWidget(QLabel('Zoom'))
        self.zoom=QDoubleSpinBox();self.zoom.setRange(.25,4);self.zoom.setSingleStep(.25);self.zoom.setValue(1);toolbar.addWidget(self.zoom)
        self.query=QLineEdit(query);self.query.setPlaceholderText('Find text in the PDF…');toolbar.addWidget(self.query,1)
        find=QPushButton('Find');find.clicked.connect(self.search);toolbar.addWidget(find)
        self.query.returnPressed.connect(self.search)
        split=QSplitter();layout.addWidget(split,1)
        self.changes=QListWidget();self.changes.setMaximumWidth(250);split.addWidget(self.changes)
        self.tabs=QTabWidget();split.addWidget(self.tabs);split.setStretchFactor(1,1)
        documents=QSplitter();self.tabs.addTab(documents,'Original and export' if before else 'Document')
        for label,path in ([('Original',viewer_before or before)] if before else [])+[('Export',viewer_after or after)]:
            pane=QWidget();box=QVBoxLayout(pane);box.addWidget(QLabel(label))
            # Keep documents outside the view's QObject child tree. Qt 6.11
            # can access its document while destroying the view's children.
            view=QPdfView();model=QPdfSearchModel(self);pdf=QPdfDocument(self)
            pdf.load(str(path));view.setDocument(pdf)
            view.setPageMode(QPdfView.PageMode.SinglePage);view.setZoomMode(QPdfView.ZoomMode.Custom)
            model.setDocument(pdf);view.setSearchModel(model)
            self.views.append(view);self.documents.append(pdf);self.models.append(model);box.addWidget(view,1);documents.addWidget(pane)
        self.difference=QLabel();self.difference.setAlignment(Qt.AlignCenter)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.difference)
        if before:self.tabs.addTab(scroll,'Highlight visual changes')
        self.status=QLabel('Compare page appearance and searchable text before approving.');self.status.setWordWrap(True);layout.addWidget(self.status)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        if review_file:
            review=QPushButton('Correct OCR text…');review.clicked.connect(self.review_ocr);buttons.addWidget(review)
        buttons.addStretch()
        close=QPushButton('Close');close.clicked.connect(self.reject);buttons.addWidget(close)
        if approve:
            button=QPushButton('Approve and export');button.clicked.connect(self.approve);buttons.addWidget(button)
        count=max([pdf.pageCount() for pdf in self.documents]+[1]);self.page.setMaximum(count)
        for index in range(count):
            row=self.comparison[index] if index<len(self.comparison) else {}
            labels=[]
            if row.get('visual_changed'):labels.append('appearance')
            if row.get('text_changed'):labels.append('text')
            if row.get('geometry_changed'):labels.append('page size')
            self.changes.addItem(f"Page {index+1}"+(': '+', '.join(labels) if labels else ' — unchanged'))
        self.changes.currentRowChanged.connect(lambda row:self.page.setValue(row+1))
        self.page.valueChanged.connect(self.navigate);self.zoom.valueChanged.connect(self.navigate)
        self.tabs.currentChanged.connect(self.navigate)
        self.page.setValue(min(initial_page+1,count));self.changes.setCurrentRow(self.page.value()-1)
        QTimer.singleShot(0,self,self.navigate)
        if query:QTimer.singleShot(100,self,self.search)

    def navigate(self,*args):
        if self.closing:return
        page=self.page.value()-1
        self.changes.blockSignals(True);self.changes.setCurrentRow(page);self.changes.blockSignals(False)
        for view,pdf in zip(self.views,self.documents):
            if page<pdf.pageCount():view.pageNavigator().jump(page,QPointF(0,0),self.zoom.value())
        if self.before and self.tabs.currentIndex()==1:
            controller=getattr(self.diff_owner,'_task_controller',None)
            if controller and controller.worker:
                controller.cancel();QTimer.singleShot(100,self,self.navigate);return
            self.diff_generation+=1;generation=self.diff_generation
            def complete(image):
                if self.closing or generation!=self.diff_generation:return
                self.difference.setPixmap(QPixmap.fromImage(ImageQt(image)))
                self.status.setText('Red highlights show pixel changes, including intended edits and compression differences.')
            run_task(self.diff_owner,render_difference,self.before,self.after,page,dpi=min(240,max(60,round(96*self.zoom.value()))),
                     on_success=complete,show_progress=False)

    def search(self):
        if self.closing:return
        for model in self.models:model.setSearchString(self.query.text())
        self.status.setText('Matches are highlighted on each page. Use the page list to inspect other pages.')

    def review_ocr(self):
        if OCRReviewDialog(self.review_file,self).exec():
            if self.ocr_changed:self.ocr_changed()
            self.accept()

    def approve(self):
        if self.approval and self.approval():self.accept()

    def done(self,result):
        if self.closing:
            super().done(result)
            return
        self.closing=True;self.diff_generation+=1;cancel_tasks(self)
        # PDF rendering/search jobs are asynchronous. Detach their consumers
        # before closing the document handles, including delayed search timers.
        for view in self.views:
            view.setSearchModel(None)
            view.setDocument(None)
            # QPdfView owns QPdfPageRenderer. Synchronous destruction joins
            # its render thread while our separately owned PDFs remain valid.
            delete(view)
        self.views.clear()
        for model in self.models:
            model.setSearchString('')
            model.setDocument(None)
            delete(model)
        self.models.clear()
        for pdf in self.documents:pdf.close()
        super().done(result)
