"""Organized local search with in-app page navigation and file-change detection."""
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLineEdit,QPushButton,
    QTableWidget,QTableWidgetItem,QHeaderView,QLabel,QFileDialog,QMessageBox,QComboBox,QInputDialog)
from services.library_service import index_documents,refresh_documents,relink_document
from utils.task_controller import run_task


class LibraryPage(QWidget):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store
        layout=QVBoxLayout(self);title=QLabel('Local document library');title.setObjectName('TitleLabel');layout.addWidget(title)
        self.status=QLabel('Search, organize and review indexed PDFs locally.');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QHBoxLayout();layout.addLayout(row)
        self.query=QLineEdit();self.query.setPlaceholderText('Search words across indexed documents…');self.query.returnPressed.connect(self.search);row.addWidget(self.query,1)
        self.tag=QComboBox();self.collection=QComboBox();row.addWidget(self.tag);row.addWidget(self.collection)
        self.tag.currentIndexChanged.connect(self.search);self.collection.currentIndexChanged.connect(self.search)
        buttons=QGridLayout();layout.addLayout(buttons)
        for index,(label,callback) in enumerate([('Search',self.search),('Index PDFs',self.choose),('Open matching page',self.open),
            ('Tags / collection',self.organize),('Find duplicates',self.duplicates),('Recheck files',lambda:self.recheck(True)),
            ('Relink moved file',self.relink),('Remove from library',self.forget)]):
            button=QPushButton(label);button.clicked.connect(callback);buttons.addWidget(button,index//4,index%4)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Document','Page','Matching text / labels'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(lambda index:self.open());layout.addWidget(self.table,1)
        self.refresh_filters();self.search()
        self.timer=QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self.check_visible);self.timer.start()

    def refresh_filters(self):
        for combo,kind,label in [(self.tag,'tag','All tags'),(self.collection,'collection','All collections')]:
            selected=combo.currentText();combo.blockSignals(True);combo.clear();combo.addItem(label,'')
            for value in self.store.label_values(kind):combo.addItem(value,value)
            index=combo.findText(selected);combo.setCurrentIndex(max(0,index));combo.blockSignals(False)

    def show_records(self,records):
        self.table.setRowCount(0)
        for record in records:
            row=self.table.rowCount();self.table.insertRow(row)
            labels=self.store.labels(record['path'])
            text=record.get('excerpt',record.get('description',f"{record.get('page_count',0)} indexed pages"))
            if labels:text+=' • '+', '.join(label['value'] for label in labels)
            for col,value in enumerate([record['path'],record.get('page','—'),text]):
                item=QTableWidgetItem(str(value));item.setData(Qt.UserRole,record);self.table.setItem(row,col,item)

    def search(self,*args):
        self.show_records(self.store.search(self.query.text(),tag=self.tag.currentData() or '',collection=self.collection.currentData() or ''))

    def choose(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Index PDF documents','','PDF files (*.pdf)')
        if not paths:return
        def done(result):
            self.search()
            if result['errors']:QMessageBox.warning(self,'Some files were not indexed','\n'.join(row['error'] for row in result['errors']))
        run_task(self,index_documents,paths,str(self.store.path),on_success=done,task_title='Indexing local documents')

    def selected_record(self):
        item=self.table.item(self.table.currentRow(),0)
        return item.data(Qt.UserRole) if item else None

    def selected(self):
        record=self.selected_record();return record['path'] if record else None

    def open(self):
        from ui.document_review_dialog import DocumentReviewDialog
        record=self.selected_record()
        if not record:return
        if not Path(record['path']).is_file():
            QMessageBox.information(self,'Document moved','Locate the file with Relink moved file.');return
        from services.review_service import prepare_view_copy
        query=self.query.text()
        def complete(display):
            DocumentReviewDialog(None,record['path'],initial_page=max(0,record.get('page',1)-1),
                query=query,parent=self,viewer_after=display).exec()
        run_task(self,prepare_view_copy,record['path'],str(self.store.path.parent/'previews'),on_success=complete,task_title='Opening document')

    def organize(self):
        path=self.selected()
        if not path:return
        labels=self.store.labels(path)
        tags=','.join(row['value'] for row in labels if row['kind']=='tag')
        tags,ok=QInputDialog.getText(self,'Document tags','Comma-separated tags:',text=tags)
        if not ok:return
        current=next((row['value'] for row in labels if row['kind']=='collection'),'')
        collection,ok=QInputDialog.getText(self,'Document collection','Collection name (blank for none):',text=current)
        if not ok:return
        try:self.store.set_labels(path,tags.split(','),collection)
        except ValueError as error:QMessageBox.information(self,'Labels',str(error));return
        self.refresh_filters();self.search()

    def duplicates(self):
        rows=self.store.duplicate_documents()
        self.show_records([{**row,'description':'Duplicate content: '+row['fingerprint'][:12]} for row in rows])
        self.status.setText(f'{len(rows)} indexed files belong to duplicate-content groups. No files were deleted.')

    def check_visible(self):
        if self.isVisible():self.recheck(False)

    def recheck(self,force=False):
        def done(result):
            self.search();self.status.setText(f"Updated {len(result['changed'])} files; {len(result['missing'])} missing; {len(result['errors'])} errors. Use Relink for moved files.")
        run_task(self,refresh_documents,str(self.store.path),force=force,on_success=done,show_progress=False)

    def relink(self):
        old=self.selected()
        if not old:return
        new,_=QFileDialog.getOpenFileName(self,'Locate moved PDF','','PDF files (*.pdf)')
        if new:run_task(self,relink_document,str(self.store.path),old,new,on_success=lambda result:self.search(),task_title='Checking moved document')

    def forget(self):
        path=self.selected()
        if path:self.store.forget_document(path);self.refresh_filters();self.search()
