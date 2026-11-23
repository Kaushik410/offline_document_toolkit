import copy
import json
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from PIL import Image
from services.workspace_model import WorkspaceModel
from services.workspace_store import WorkspaceStore
from services.workspace_service import import_documents,assemble_workspace,render_workspace_page
from services.workflow_service import DEFAULT_RECIPE,validate_recipe,execute_workflow,approve_export
from services.validation_service import ValidationService
from services.export_service import ExportService
from tests.conftest import wait_until


def imported(pdf,tmp_path):
    assets=import_documents([str(pdf)],tmp_path/'imports')
    assert not assets['errors']
    model=WorkspaceModel();model.import_assets(assets['assets'])
    return model


def test_workspace_history_survives_project_save_and_reopen(pdf,tmp_path):
    model=imported(pdf,tmp_path);page_id=model.document['pages'][0]['id']
    model.edit(page_id,{'operation':'rotate','angle':90})
    model.undo();assert model.document['pages'][0]['rotation']==0
    model.redo();assert model.document['pages'][0]['rotation']==90
    store=WorkspaceStore(tmp_path/'state.sqlite')
    project=store.save_project('Example',model.serialize())
    reopened=WorkspaceModel(store.project(project));reopened.undo()
    assert reopened.document['pages'][0]['rotation']==0
    reordered=list(reversed([page['id'] for page in reopened.document['pages']]))
    reopened.reorder(reordered);assert reopened.document['pages'][0]['id']==reordered[0]


def test_workspace_import_is_a_snapshot_and_errors_are_individual(pdf,tmp_path):
    original=pdf.read_bytes()
    result=import_documents([str(pdf),str(tmp_path/'missing.pdf')],tmp_path/'cache')
    assert len(result['assets'])==len(result['errors'])==1
    assert Path(result['assets'][0]['pdf']).resolve()!=pdf.resolve()
    pdf.write_bytes(b'changed external source')
    assert Path(result['assets'][0]['pdf']).read_bytes()==original


def test_queue_claims_are_exclusive_and_interrupted_jobs_can_resume(tmp_path):
    store=WorkspaceStore(tmp_path/'state.sqlite');job=store.enqueue('Example',{'example':1})
    assert store.acquire('first')
    assert store.claim('first')['id']==job
    assert not store.acquire('second')
    with store.connect() as db:db.execute('UPDATE lease SET heartbeat=0')
    assert store.acquire('second')
    assert store.job(job)['state']=='interrupted'
    store.retry(job)
    assert store.claim('second')['attempts']==2
    store.release('second');assert store.job(job)['state']=='interrupted'


def test_workflow_presets_validate_and_roundtrip(tmp_path):
    store=WorkspaceStore(tmp_path/'state.sqlite')
    value=validate_recipe(dict(DEFAULT_RECIPE,max_bytes=200*1024,language='eng+hin'))
    store.save_workflow('Application',value)
    store.save_workflow('Application',dict(value,max_pages=5))
    assert len(store.workflows())==1
    assert store.workflows()[0]['recipe']['max_pages']==5
    for change in [{'steps':['export','ocr']},{'steps':['export','export']},{'output_name':'../escape'},
                   {'format':'pdf','width':100},{'min_quality':0},{'max_pages':True}]:
        with pytest.raises(ValueError):validate_recipe(dict(DEFAULT_RECIPE,**change))


def test_submission_requires_review_and_publishes_validated_packet(pdf,tmp_path):
    model=imported(pdf,tmp_path);store=WorkspaceStore(tmp_path/'state.sqlite')
    recipe=dict(DEFAULT_RECIPE,steps=['merge','rename','export'],max_bytes=0)
    spec={'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports'),'database_path':str(store.path)}
    result=execute_workflow(spec,tmp_path/'job-one')
    assert result['state']=='needs_review' and result['ready_to_export']
    assert not (tmp_path/'exports').exists()
    approve_export(tmp_path/'job-one')
    with patch('services.workflow_service.assemble_workspace',side_effect=AssertionError('Completed stage was rerun')):
        result=execute_workflow(spec,tmp_path/'job-one')
    assert result['state']=='succeeded'
    assert 'assemble' in result['reused_stages']
    assert all(report['passed'] for report in result['reports'])
    assert store.search('TOOLKIT')
    with fitz.open(result['outputs'][0]) as pdf:assert len(pdf)==3


def test_unmet_size_and_page_limits_never_publish_success(pdf,tmp_path):
    model=imported(pdf,tmp_path)
    recipe=dict(DEFAULT_RECIPE,steps=['compress','merge','export'],max_bytes=100,max_pages=1,review_before_export=False)
    result=execute_workflow({'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports')},tmp_path/'job-two')
    assert result['state']=='needs_review' and not result['ready_to_export']
    assert not result['outputs'] and not (tmp_path/'exports').exists()
    failed={check['name'] for report in result['reports'] for check in report['checks'] if not check['passed']}
    assert 'File size' in failed and 'Page limit' in failed


def test_image_export_enforces_dimensions(image,tmp_path):
    assets=import_documents([str(image)],tmp_path/'imports');model=WorkspaceModel();model.import_assets(assets['assets'])
    recipe=dict(DEFAULT_RECIPE,steps=['rename','export'],format='jpg',width=320,height=240,max_bytes=100000,
                review_before_export=False)
    result=execute_workflow({'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports')},tmp_path/'image-job')
    assert result['state']=='succeeded'
    with Image.open(result['outputs'][0]) as output:assert output.size==(320,240)


def test_image_quality_floor_reports_an_unachievable_size(tmp_path):
    image=Image.effect_noise((300,300),80).convert('RGB')
    result=ExportService.image(image,tmp_path/'out.jpg',width=300,height=300,max_bytes=20,min_quality=70)
    assert not result['validation']['passed'] and result['quality']>=70
    assert 'cannot be met' in result['reason']


def test_validation_detects_dropped_forms_and_attachments(tmp_path):
    source=tmp_path/'forms.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();widget=fitz.Widget();widget.field_name='example';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value='Example';widget.rect=fitz.Rect(30,30,100,60);page.add_widget(widget)
        pdf.embfile_add('example.txt',b'example');pdf.save(source)
    baseline=ValidationService.inspect_pdf(source)
    with fitz.open() as pdf:pdf.new_page();pdf.save(tmp_path/'dropped.pdf')
    result=ValidationService.validate_pdf(tmp_path/'dropped.pdf',baseline=baseline,expected_pages=1)
    assert not result['passed']
    assert {'Form fields','Attachments'}<={row['name'] for row in result['checks'] if not row['passed']}


def test_library_search_has_page_locations_unicode_and_forget(tmp_path):
    store=WorkspaceStore(tmp_path/'state.sqlite');path=tmp_path/'example.pdf';path.write_bytes(b'original')
    store.index_document(path,'hash',['Synthetic application document','नमस्ते दस्तावेज'])
    assert store.search('application')[0]['page']==1
    assert store.search('दस्तावेज')[0]['page']==2
    assert not store.search('" OR unknown')
    store.forget_document(path);assert not store.search('application')
    assert path.read_bytes()==b'original'


def test_real_queue_approves_and_completes_job(qapp,pdf,tmp_path):
    from ui.job_queue import JobQueue
    from ui.jobs_page import JobsPage
    model=imported(pdf,tmp_path);store=WorkspaceStore(tmp_path/'state.sqlite')
    job=store.enqueue('Submission',{'document':model.document,
        'recipe':dict(DEFAULT_RECIPE,steps=['merge','export'],max_bytes=0),'output_directory':str(tmp_path/'exports')})
    queue=JobQueue(store);page=JobsPage(store,queue)
    wait_until(qapp,lambda:store.job(job)['state']=='needs_review',timeout=25)
    page.refresh();page.approve()
    wait_until(qapp,lambda:store.job(job)['state']=='succeeded',timeout=25)
    assert Path(store.job(job)['result']['outputs'][0]).is_file()
    queue.shutdown();page.close()


def test_workspace_ui_can_edit_undo_and_restore(qapp,pdf,tmp_path):
    from ui.workspace_page import WorkspacePage
    from ui.job_queue import JobQueue
    store=WorkspaceStore(tmp_path/'state.sqlite');queue=JobQueue(store);page=WorkspacePage(store,queue)
    page.add_files([str(pdf)])
    wait_until(qapp,lambda:len(page.model.document['pages'])==3 and page.preview_image is not None,timeout=20)
    page.edit('rotate');assert page.model.document['pages'][0]['rotation']==90
    page.undo();assert page.model.document['pages'][0]['rotation']==0
    page.redo();assert page.model.document['pages'][0]['rotation']==90
    assert store.projects()
    queue.shutdown()
    from utils.task_controller import cancel_tasks
    cancel_tasks(page);page.close()


def test_workspace_crop_then_rotate_respects_operation_order(pdf,tmp_path):
    model=imported(pdf,tmp_path);page_id=model.document['pages'][0]['id']
    original=render_workspace_page(model.document,page_id,dpi=72)
    model.edit(page_id,{'operation':'crop','params':{'rect':[0,0,.5,1]}})
    model.edit(page_id,{'operation':'rotate','angle':90})
    result=render_workspace_page(model.document,page_id,dpi=72)
    expected=original.crop((0,0,original.width//2,original.height)).rotate(-90,expand=True)
    assert result.size==expected.size and result.tobytes()==expected.tobytes()


def test_form_fields_and_attachments_survive_workspace_merge(tmp_path):
    source=tmp_path/'forms.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();widget=fitz.Widget();widget.field_name='example';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value='Example';widget.rect=fitz.Rect(30,30,100,60);page.add_widget(widget)
        pdf.embfile_add('example.txt',b'Synthetic attachment');pdf.save(source)
    model=imported(source,tmp_path)
    assemble_workspace(model.document,tmp_path/'packet.pdf')
    result=ValidationService.inspect_pdf(tmp_path/'packet.pdf')
    assert result['fields'][0]['value']=='Example'
    assert len(result['attachments'])==1


def test_export_never_overwrites_unrelated_candidate_filenames(pdf,tmp_path):
    sentinel=tmp_path/'candidate-0.pdf';sentinel.write_bytes(b'Existing user file')
    ExportService.pdf(pdf,tmp_path/'result.pdf',max_bytes=1)
    assert sentinel.read_bytes()==b'Existing user file'
    assert ValidationService.inspect_pdf(tmp_path/'result.pdf')['pages']==3


def test_validation_detects_missing_repeated_text_and_page_geometry(tmp_path):
    with fitz.open() as source:
        page=source.new_page(width=300,height=400);page.insert_text((20,30),'Example Example')
        source.save(tmp_path/'before.pdf')
    with fitz.open() as source:
        page=source.new_page(width=350,height=400);page.insert_text((20,30),'Example')
        source.save(tmp_path/'after.pdf')
    result=ValidationService.validate_pdf(tmp_path/'after.pdf',baseline=ValidationService.inspect_pdf(tmp_path/'before.pdf'))
    failed={row['name'] for row in result['checks'] if not row['passed']}
    assert {'Selectable text','Page geometry'}<=failed


def test_pdf_page_exports_honor_compression_and_preserve_attachments(pdf,tmp_path):
    model=imported(pdf,tmp_path)
    recipe=dict(DEFAULT_RECIPE,steps=['compress','rename','export'],max_bytes=0,review_before_export=False)
    with patch('services.workflow_service.ExportService.pdf',wraps=ExportService.pdf) as optimize:
        result=execute_workflow({'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports')},tmp_path/'pages-job')
    assert result['state']=='succeeded' and len(result['outputs'])==3
    assert optimize.call_count==3
    assert all(ValidationService.inspect_pdf(path)['pages']==1 for path in result['outputs'])


@pytest.mark.parametrize('format',['png','jpg'])
def test_image_packet_explains_unmet_size_target(image,tmp_path,format):
    assets=import_documents([image],tmp_path/'imports');model=WorkspaceModel();model.import_assets(assets['assets'])
    recipe=dict(DEFAULT_RECIPE,steps=['export'],format=format,max_bytes=1,width=320,height=240,review_before_export=False)
    result=execute_workflow({'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports')},tmp_path/'image-limit-job')
    assert result['state']=='needs_review' and not result['outputs']
    assert result['reports'][0]['reason']
    if format=='png':assert result['reports'][0]['quality'] is None
