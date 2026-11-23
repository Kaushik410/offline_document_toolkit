from pathlib import Path
import copy
from PySide6.QtCore import Qt,Signal,QTimer,QSize
from PySide6.QtGui import QPixmap,QIcon
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,
    QFileDialog,QMessageBox,QInputDialog,QLineEdit,QAbstractItemView,QSplitter,QGridLayout,QSizePolicy)
from PIL.ImageQt import ImageQt

from ui.image_editor_dialog import ImageCanvas
from ui.workflow_dialog import WorkflowDialog
from services.workspace_model import WorkspaceModel
from services.workspace_service import import_documents,render_workspace_page,cached_workspace_preview
from utils.app_config import AppConfig
from utils.task_controller import run_task,cancel_tasks


class DocumentList(QListWidget):
    filesDropped=Signal(list)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True);self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction);self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(80,110));self.setWordWrap(True)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:super().dragEnterEvent(event)
    def dragMoveEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
        else:super().dragMoveEvent(event)
    def dropEvent(self,event):
        if event.mimeData().hasUrls():
            self.filesDropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:super().dropEvent(event)


class WorkspaceCanvas(ImageCanvas):
    def __init__(self,parent_dialog):
        super().__init__(allow_selection=True,parent_dialog=parent_dialog)
        self.full_pixmap=None
        self.setMinimumSize(300,300)
        self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)

    def set_pixmap_from_qpixmap(self,pixmap,reset_user_input=True):
        self.full_pixmap=pixmap
        super().set_pixmap_from_qpixmap(pixmap,reset_user_input)
        self.fit_preview()

    def fit_preview(self):
        if self.full_pixmap and not self.full_pixmap.isNull():
            self.display_pixmap=self.full_pixmap.scaled(self.size()-QSize(8,8),Qt.KeepAspectRatio,Qt.SmoothTransformation)
            self.setPixmap(self.display_pixmap)
            self.selection_rect_original=None;self.rubber_band.hide()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'full_pixmap'):self.fit_preview()

    def clear(self):
        self.full_pixmap=None;self.display_pixmap=None;self.selection_rect_original=None
        self.rubber_band.hide();super().clear()


class WorkspacePage(QWidget):
    jobQueued=Signal(str)
    def __init__(self,store,queue,parent=None):
        super().__init__(parent);self.store=store;self.queue=queue
        self.model=WorkspaceModel();self.project_id=None;self.preview_image=None;self.refreshing=False;self.closing=False
        self.preview_owner=QWidget(self);self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.load_preview);self.preview_generation=0
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,18)
        title=QLabel('Document workspace');title.setObjectName('TitleLabel');layout.addWidget(title)
        header=QHBoxLayout();layout.addLayout(header)
        self.project_name=QLineEdit('Untitled workspace');self.project_name.editingFinished.connect(self.save_project)
        header.addWidget(self.project_name,1)
        for label,callback in [('New',self.new_project),('Open project',self.open_project),('Add files',self.choose_files)]:
            button=QPushButton(label);button.clicked.connect(callback);header.addWidget(button)
        tools=QGridLayout();layout.addLayout(tools)
        self.undo_button=QPushButton('Undo');self.redo_button=QPushButton('Redo')
        self.undo_button.clicked.connect(self.undo);self.redo_button.clicked.connect(self.redo)
        tools.addWidget(self.undo_button,0,0);tools.addWidget(self.redo_button,0,1)
        for index,(label,callback) in enumerate([('Rotate',lambda:self.edit('rotate')),('Crop',lambda:self.edit('crop')),
            ('Blur',lambda:self.edit('blur')),('Text',lambda:self.edit('add_text')),
            ('Grayscale',lambda:self.edit('black_white')),('Brightness',lambda:self.edit('brightness_contrast')),
            ('Denoise',lambda:self.edit('denoise')),('Delete pages',self.delete_pages)]):
            button=QPushButton(label);button.clicked.connect(callback);tools.addWidget(button,(index+2)//5,(index+2)%5)
        for index,(label,callback) in enumerate([('Document role',self.assign_role),('Checklist',self.checklist),
            ('Suggest order',self.suggest_order),('Fill PDF form',self.fill_form),('Redact area',self.redact),
            ('Export project',self.export_project),('Import project',self.import_project),('Storage / backup',self.storage)]):
            button=QPushButton(label);button.clicked.connect(callback);tools.addWidget(button,2+index//5,index%5)
        splitter=QSplitter();layout.addWidget(splitter,1)
        self.pages=DocumentList();self.pages.setMinimumWidth(260)
        self.pages.filesDropped.connect(self.add_files)
        self.pages.currentItemChanged.connect(self.selection_changed)
        self.pages.model().rowsMoved.connect(self.reordered)
        splitter.addWidget(self.pages)
        self.canvas=WorkspaceCanvas(self)
        splitter.addWidget(self.canvas);splitter.setStretchFactor(1,1)
        self.status=QLabel('Drop PDF, DOCX, or image files into the page list. Originals are preserved.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        bottom=QHBoxLayout();layout.addLayout(bottom)
        bottom.addWidget(QLabel('Select an area on the preview for Crop, Blur, or Text.'))
        bottom.addStretch()
        self.prepare_button=QPushButton('Prepare for submission…');self.prepare_button.clicked.connect(self.queue_submission)
        self.prepare_button.setStyleSheet('background:#2563eb;color:white;padding:10px;font-weight:bold;')
        bottom.addWidget(self.prepare_button)
        config=AppConfig.load_config()
        if config.get('last_project'):
            try:
                self.project_id=config['last_project'];self.model=WorkspaceModel(self.store.project(self.project_id))
                rows={row['id']:row for row in self.store.projects()}
                self.project_name.setText(rows[self.project_id]['name'])
            except (KeyError,ValueError):self.project_id=None;self.model=WorkspaceModel()
        self.refresh()

    def set_status(self,message):self.status.setText(message)

    def choose_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add documents','','Documents (*.pdf *.docx *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        if paths:self.add_files(paths)

    def add_files(self,paths):
        def completed(result):
            if result['assets']:
                self.model.import_assets(result['assets']);self.changed()
            if result['errors']:QMessageBox.warning(self,'Some files could not be imported','\n'.join(row['error'] for row in result['errors']))
        run_task(self,import_documents,paths,on_success=completed,task_title='Importing documents')

    def save_project(self):
        self.project_id=self.store.save_project(self.project_name.text() or 'Untitled workspace',self.model.serialize(),self.project_id)
        config=AppConfig.load_config();config['last_project']=self.project_id;AppConfig.save_config(config)

    def new_project(self):
        self.model=WorkspaceModel();self.project_id=None;self.project_name.setText('Untitled workspace');self.changed()

    def open_project(self):
        projects=self.store.projects()
        if not projects:return
        labels=[f"{row['name']} ({row['id'][:6]})" for row in projects]
        selected,ok=QInputDialog.getItem(self,'Open project','Project',labels,0,False)
        if ok:
            row=projects[labels.index(selected)];self.project_id=row['id'];self.project_name.setText(row['name'])
            self.model=WorkspaceModel(self.store.project(self.project_id));self.changed()

    def selected(self):
        item=self.pages.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self):
        selected=self.selected();self.refreshing=True;self.pages.clear()
        for number,page in enumerate(self.model.document['pages']):
            asset=self.model.document['assets'][page['asset']]
            item=QListWidgetItem(f"{number+1}. {asset['name']} — page {page['page']+1}\n{asset.get('role','unassigned')} • {len(page['edits'])} edits • {len(page.get('redactions',[]))} redactions")
            item.setData(Qt.UserRole,page['id'])
            if page['page']<len(asset['thumbnails']):item.setIcon(QIcon(asset['thumbnails'][page['page']]))
            self.pages.addItem(item)
            if page['id']==selected:self.pages.setCurrentItem(item)
        self.refreshing=False
        if self.pages.currentRow()<0 and self.pages.count():self.pages.setCurrentRow(0)
        self.undo_button.setEnabled(self.model.position>0)
        self.redo_button.setEnabled(self.model.position<len(self.model.history)-1)
        self.prepare_button.setEnabled(bool(self.model.document['pages']))
        self.selection_changed()

    def changed(self):self.save_project();self.refresh()
    def undo(self):self.model.undo();self.changed()
    def redo(self):self.model.redo();self.changed()

    def reordered(self,*args):
        if not self.refreshing:
            self.model.reorder([self.pages.item(index).data(Qt.UserRole) for index in range(self.pages.count())]);self.save_project()

    def selection_changed(self,*args):
        if self.refreshing:return
        self.preview_image=None
        self.preview_generation+=1;self.preview_timer.start(80)

    def load_preview(self):
        if self.closing:return
        page_id=self.selected()
        if not page_id:
            self.canvas.clear();self.preview_image=None;return
        controller=getattr(self.preview_owner,'_task_controller',None)
        if controller and controller.worker:
            controller.cancel();self.preview_timer.start(100);return
        generation=self.preview_generation
        def completed(image):
            if generation!=self.preview_generation:return
            self.preview_image=image
            pixmap=QPixmap.fromImage(ImageQt(image));self.canvas.set_pixmap_from_qpixmap(pixmap)
            item=self.pages.currentItem()
            if item:item.setIcon(QIcon(pixmap.scaled(100,130,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
        run_task(self.preview_owner,cached_workspace_preview,copy.deepcopy(self.model.document),page_id,
                 on_success=completed,show_progress=False)

    def edit(self,kind):
        page_id=self.selected()
        if not page_id:return
        if self.preview_image is None:
            self.set_status('Wait for the page preview to finish loading before editing.');return
        if kind=='rotate':operation={'operation':'rotate','angle':90}
        else:
            params={}
            if kind in ('crop','blur','add_text'):
                rect=self.canvas.selection_rect_original
                if not rect:self.set_status('Select an area on the preview first.');return
                normalized=[value/(self.preview_image.width if index%2==0 else self.preview_image.height) for index,value in enumerate(rect)]
                if kind=='add_text':
                    text,ok=QInputDialog.getText(self,'Add text','Text:')
                    if not ok or not text:return
                    params={'text':text,'point':normalized[:2],'font_size_fraction':0.04}
                else:params={'rect':normalized}
                if kind=='blur':params['blur_radius']=12
            elif kind=='brightness_contrast':
                value,ok=QInputDialog.getDouble(self,'Brightness','Brightness multiplier',1.1,0.1,5,2)
                if not ok:return
                params={'brightness':value,'contrast':1.1}
            elif kind=='denoise':params={'strength':10}
            operation={'operation':kind,'params':params}
        self.model.edit(page_id,operation);self.changed()

    def delete_pages(self):
        ids=[item.data(Qt.UserRole) for item in self.pages.selectedItems()]
        if ids:self.model.remove(ids);self.changed()

    def queue_submission(self):
        from services.submission_service import inspect_packet
        packet=inspect_packet(self.model.document)
        if not packet['passed']:
            QMessageBox.information(self,'Submission checklist incomplete','\n'.join(row['name']+': '+row['detail'] for row in packet['checks'] if not row['passed']));return
        if packet['duplicates'] and QMessageBox.question(self,'Duplicate pages',
            'Repeated source pages were found at packet positions '+', '.join(map(str,packet['duplicates']))+'. Continue?')!=QMessageBox.Yes:return
        dialog=WorkflowDialog(self.store,self)
        if dialog.exec()!=dialog.Accepted:return
        if dialog.recipe['max_pages'] and len(self.model.document['pages'])>dialog.recipe['max_pages']:
            QMessageBox.information(self,'Page limit exceeded','Remove pages or increase the page limit before queueing.');return
        from utils.engine_registry import EngineRegistry
        if 'ocr' in dialog.recipe['steps'] and not EngineRegistry.find('tesseract'):
            QMessageBox.information(self,'Enable OCR','Locate Tesseract in Setup, or turn off the OCR step.');return
        directory=QFileDialog.getExistingDirectory(self,'Choose export folder',str(AppConfig.ensure_output_folder()))
        if not directory:return
        self.save_project()
        spec={'document':copy.deepcopy(self.model.document),'recipe':dialog.recipe,'output_directory':directory,'database_path':str(self.store.path)}
        job_id=self.store.enqueue(self.project_name.text() or 'Submission',spec)
        self.status.setText('Queued. Open Jobs to review progress, OCR, and the staged export.')
        self.queue.changed.emit();self.jobQueued.emit(job_id)

    def selected_asset(self):
        page_id=self.selected()
        if not page_id:return None
        page=next(page for page in self.model.document['pages'] if page['id']==page_id)
        return page['asset']

    def assign_role(self):
        from services.submission_service import ROLES
        key=self.selected_asset()
        if not key:return
        roles=list(dict.fromkeys(ROLES+[row['role'] for row in self.model.document.get('requirements',[])]))
        role,ok=QInputDialog.getItem(self,'Document role','Role for this imported document',roles,0,True)
        if ok and role.strip():
            selected={item.data(Qt.UserRole) for item in self.pages.selectedItems()}
            assets={page['asset'] for page in self.model.document['pages'] if page['id'] in selected} or {key}
            self.model.set_many_values([(['assets',asset_id,'role'],role.strip().lower()) for asset_id in assets])
            self.changed()

    def checklist(self):
        from ui.submission_dialogs import ChecklistDialog
        dialog=ChecklistDialog(self.model.document.get('requirements',[]),self)
        if dialog.exec():self.model.set_value(['requirements'],dialog.requirements);self.changed()

    def suggest_order(self):
        from services.submission_service import suggested_order
        self.model.reorder(suggested_order(self.model.document));self.changed()

    def fill_form(self):
        from services.form_service import inspect_fields
        from ui.submission_dialogs import FormFieldsDialog
        key=self.selected_asset()
        if not key:return
        asset=self.model.document['assets'][key]
        def complete(fields):
            if not fields:QMessageBox.information(self,'PDF form','This document has no PDF form fields.');return
            dialog=FormFieldsDialog(fields,asset.get('form_values',{}),self)
            if dialog.exec():self.model.set_value(['assets',key,'form_values'],dialog.values);self.changed()
        run_task(self,inspect_fields,asset['pdf'],on_success=complete,task_title='Reading PDF fields')

    def redact(self):
        from services.privacy_service import selection_to_redaction
        page_id=self.selected()
        if not page_id or self.preview_image is None:return
        rect=self.canvas.selection_rect_original
        if not rect:self.set_status('Select the area to remove, then choose Redact area.');return
        normalized=[value/(self.preview_image.width if index%2==0 else self.preview_image.height) for index,value in enumerate(rect)]
        try:box=selection_to_redaction(self.model.document,page_id,normalized)
        except ValueError as error:QMessageBox.information(self,'Redaction',str(error));return
        self.model.edit(page_id,{'operation':'redact','rect':box});self.changed()
        self.set_status('The selected area will be removed from the exported page. Source snapshots and undo history retain the original.')

    def export_project(self):
        from services.project_archive import export_project
        self.save_project()
        path,_=QFileDialog.getSaveFileName(self,'Export portable project','project.odtproject','Portable project (*.odtproject)')
        from utils.file_dialog_utils import normalize_output_selection
        path=normalize_output_selection(self,path,'.odtproject')
        if path:run_task(self,export_project,str(self.store.path),self.project_id,path,
            on_success=lambda result:QMessageBox.information(self,'Project exported','Original snapshots, history, and recipes saved to:\n'+result),task_title='Exporting portable project')

    def import_project(self):
        from services.project_archive import import_project
        path,_=QFileDialog.getOpenFileName(self,'Import portable project','','Portable project (*.odtproject)')
        if not path:return
        def complete(result):
            self.project_id=result['id'];self.project_name.setText(result['name'])
            self.model=WorkspaceModel(self.store.project(self.project_id));self.changed()
        run_task(self,import_project,str(self.store.path),path,on_success=complete,task_title='Importing project')

    def storage(self):
        from ui.storage_dialog import StorageDialog
        self.save_project();dialog=StorageDialog(self.store,self.queue,self)
        def removed(project_id):
            if self.project_id==project_id:self.new_project()
        dialog.projectDeleted.connect(removed);dialog.exec()

    def shutdown(self):
        self.closing=True
        self.preview_timer.stop()
        cancel_tasks(self)

    def closeEvent(self,event):
        self.shutdown()
        super().closeEvent(event)
