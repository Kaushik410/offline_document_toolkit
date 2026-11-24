"""Synthetic acceptance checks runnable from the installed native application."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time


def run(report_file=None,require_libreoffice=False):
    from utils.version import VERSION
    report={'version':VERSION,'passed':False,'checks':[],
        'runtime':{'frozen':bool(getattr(sys,'frozen',False)),'executable':sys.executable},
        'libreoffice':{'required':require_libreoffice,'verified':False}}
    try:
        with tempfile.TemporaryDirectory(prefix='odt-self-test-') as directory:
            root=Path(directory)
            os.environ.update(ODT_DATA_DIR=str(root/'data'),ODT_CONFIG_DIR=str(root/'config'),
                              ODT_OUTPUT_DIR=str(root/'exports'),ODT_NO_SETUP='1')
            os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
            from utils.qt_runtime import configure_qt_plugins
            configure_qt_plugins()
            import fitz
            from PySide6.QtWidgets import QApplication
            from services.workspace_model import WorkspaceModel
            from services.workspace_service import import_documents,render_workspace_page
            from services.workspace_store import WorkspaceStore
            from services.workflow_service import DEFAULT_RECIPE,execute_workflow,approve_export
            from services.project_archive import export_project,import_project,backup_workspace,restore_workspace
            from services.validation_service import ValidationService
            from services.review_service import prepare_packet_review
            from ui.document_review_dialog import DocumentReviewDialog
            from utils.task_controller import shutdown_tasks
            app=QApplication.instance() or QApplication([])
            source=root/'synthetic.pdf'
            with fitz.open() as pdf:
                page=pdf.new_page(width=400,height=400)
                page.insert_text((30,50),'SYNTHETIC PRIVATE VALUE')
                page.insert_text((30,220),'Public submission document')
                widget=fitz.Widget();widget.field_name='applicant';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
                widget.field_value='Before';widget.rect=fitz.Rect(30,260,250,290);page.add_widget(widget)
                pdf.embfile_add('example.txt',b'Synthetic attachment');pdf.set_metadata({'author':'Synthetic author'});pdf.save(source)
            store=WorkspaceStore(root/'data/workspace.sqlite3');model=WorkspaceModel()
            imported=import_documents([source],root/'data/imports')
            assert not imported['errors'];model.import_assets(imported['assets'])
            asset_id=next(iter(model.document['assets']));page_id=model.document['pages'][0]['id']
            model.set_value(['assets',asset_id,'role'],'application')
            model.set_value(['assets',asset_id,'form_values'],{'applicant':'Reviewed'})
            model.set_value(['requirements'],[{'role':'application','minimum':1}])
            model.edit(page_id,{'operation':'redact','rect':[20,30,340,70]})
            project=store.save_project('Acceptance',model.serialize())
            bundle=export_project(store.path,project,root/'project.odtproject')
            portable=import_project(store.path,bundle)
            assert WorkspaceModel(store.project(portable['id'])).document['pages']
            report['checks'].append('Portable project and compact history')
            from PySide6.QtCore import QThreadPool
            from utils.task_worker import TaskWorker
            previews=[];errors=[]
            worker=TaskWorker(render_workspace_page,model.document,page_id)
            worker.signals.finished.connect(previews.append);worker.signals.error.connect(errors.append)
            QThreadPool.globalInstance().start(worker)
            deadline=time.monotonic()+30
            while not previews and not errors and time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            if not previews:
                worker.cancel()
                raise RuntimeError('; '.join(errors) if errors else 'Background preview process did not complete')
            report['checks'].append('Isolated background preview process')
            spec={'document':model.document,'recipe':dict(DEFAULT_RECIPE,steps=['compress','merge','rename','export'],
                max_bytes=0,privacy={'remove_metadata':True,'remove_comments':True,'remove_attachments':True}),
                'output_directory':str(root/'exports'),'database_path':str(store.path)}
            job=root/'data/jobs/acceptance';review=execute_workflow(spec,job)
            assert review['state']=='needs_review' and review['ready_to_export']
            comparison=prepare_packet_review(model.document,review['staged'],job/'review')
            viewer=DocumentReviewDialog(comparison['before'],comparison['after'],comparison['pages'],
                viewer_before=comparison['viewer_before'],viewer_after=comparison['viewer_after'])
            try:
                viewer.show();app.processEvents()
                assert all(pdf.pageCount()==1 for pdf in viewer.documents)
                with fitz.open(comparison['viewer_after']) as display:assert 'Reviewed' in display[0].get_text()
                viewer.query.setText('Public');viewer.search();app.processEvents()
            finally:
                viewer.close()
            report['checks'].append('Embedded PDF comparison, search and review')
            approve_export(job);result=execute_workflow(spec,job)
            assert result['state']=='succeeded'
            actual=ValidationService.inspect_pdf(result['outputs'][0])
            assert 'PRIVATE' not in ''.join(actual['text']) and 'Public' in ''.join(actual['text'])
            assert actual['fields'][0]['value']=='Reviewed' and not actual['attachments']
            assert all(item['passed'] for item in result['reports'])
            assert store.search('Public')
            report['checks'].append('Checklist, form filling, redaction, privacy validation and library indexing')
            backup=backup_workspace(store.path,root/'backup.odtbackup')
            restored=restore_workspace(backup,root/'restored')
            assert WorkspaceStore(Path(restored)/'workspace.sqlite3').projects()
            report['checks'].append('Workspace backup and restore')
            if require_libreoffice:
                from docx import Document
                from services.word_service import WordService
                docx=root/'libreoffice-check.docx'
                document=Document();document.add_paragraph('LIBREOFFICE NATIVE ACCEPTANCE CHECK');document.save(docx)
                converted=WordService.docx_to_pdf(docx,root/'libreoffice-output')
                with fitz.open(converted) as pdf:
                    assert len(pdf)==1 and 'LIBREOFFICE NATIVE ACCEPTANCE CHECK' in pdf[0].get_text()
                report['libreoffice']['verified']=True
                report['checks'].append('Required real LibreOffice DOCX conversion')
            shutdown_tasks()
        report['passed']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    if report_file:
        target=Path(report_file);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if sys.stdout:print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1
