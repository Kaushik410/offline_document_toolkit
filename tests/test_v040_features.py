import copy
import json
import os
from pathlib import Path
import shutil
import zipfile
from unittest.mock import patch

import fitz
import pytest
from PIL import Image
from services.workspace_model import WorkspaceModel
from services.workspace_store import WorkspaceStore
from services.workspace_service import import_documents,assemble_workspace
from services.submission_service import inspect_packet,suggested_order
from services.form_service import inspect_fields
from services.privacy_service import selection_to_redaction,privacy_checks
from services.workflow_service import DEFAULT_RECIPE,execute_workflow,approve_export
from services.validation_service import ValidationService
from services.project_archive import export_project,import_project,backup_workspace,restore_workspace
from services.storage_service import inspect_storage,cleanup_storage
from services.library_service import index_documents,refresh_documents,relink_document
from services.review_service import prepare_packet_review,render_difference
from tests.conftest import wait_until


def model_for(path,root):
    result=import_documents([path],root/'imports');assert not result['errors']
    model=WorkspaceModel();model.import_assets(result['assets'])
    return model


@pytest.fixture
def form_pdf(tmp_path):
    path=tmp_path/'form.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page(width=400,height=400)
        page.insert_text((30,60),'CONFIDENTIAL SOURCE')
        page.insert_text((30,180),'PUBLIC RECORD')
        widget=fitz.Widget();widget.field_name='applicant';widget.field_value='Before'
        widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT;widget.rect=fitz.Rect(30,250,200,280);page.add_widget(widget)
        checkbox=fitz.Widget();checkbox.field_name='confirmed';checkbox.field_type=fitz.PDF_WIDGET_TYPE_CHECKBOX
        checkbox.rect=fitz.Rect(250,250,270,270);page.add_widget(checkbox)
        page.add_text_annot((300,300),'Private comment')
        pdf.embfile_add('private.txt',b'private attachment');pdf.set_metadata({'author':'Private author'})
        pdf.save(path)
    return path


def test_compact_history_migrates_legacy_and_supports_branches(pdf,tmp_path):
    model=model_for(pdf,tmp_path);initial=copy.deepcopy(model.document)
    model.edit(initial['pages'][0]['id'],{'operation':'rotate','angle':90})
    changed=copy.deepcopy(model.document)
    restored=WorkspaceModel({'history':[initial,changed],'position':0})
    restored.redo();assert restored.document==changed
    restored.undo();restored.set_value(['requirements'],[{'role':'identity','minimum':1}])
    assert restored.position==len(restored.commands)
    roundtrip=WorkspaceModel(restored.serialize());roundtrip.undo();assert roundtrip.document==initial


def test_history_storage_grows_with_edits_instead_of_document_copies():
    model=WorkspaceModel();asset={'name':'large.pdf','source_hash':'hash','pdf_hash':'hash','pdf':'/synthetic.pdf',
        'page_count':2000,'thumbnails':[]}
    model.import_assets([asset]);size=len(json.dumps(model.serialize()))
    key=model.document['pages'][0]['id']
    for _ in range(50):model.edit(key,{'operation':'rotate','angle':90})
    assert len(json.dumps(model.serialize()))<size*1.3
    before=copy.deepcopy(model.document)
    for _ in range(110):model.edit(key,{'operation':'rotate','angle':90})
    saved=WorkspaceModel(model.serialize());assert saved.document==model.document
    assert len(saved.commands)<=100
    for _ in range(100):saved.undo()
    for _ in range(100):saved.redo()
    assert saved.document==model.document


def test_roles_checklists_duplicates_and_suggested_order(pdf,tmp_path):
    model=model_for(pdf,tmp_path);asset=next(iter(model.document['assets']))
    model.set_value(['requirements'],[{'role':'application','minimum':1},{'role':'identity','minimum':1}])
    model.set_value(['assets',asset,'role'],'identity');assert not inspect_packet(model.document)['passed']
    second=import_documents([pdf],tmp_path/'imports');model.import_assets(second['assets'])
    application=model.document['pages'][-1]['asset'];model.set_value(['assets',application,'role'],'application')
    assert inspect_packet(model.document)['passed'] and inspect_packet(model.document)['duplicates']
    model.reorder(suggested_order(model.document))
    assert model.document['pages'][0]['asset']==application
    model.undo();assert model.document['pages'][0]['asset']==asset


def test_incomplete_checklist_blocks_direct_export(pdf,tmp_path):
    model=model_for(pdf,tmp_path);model.set_value(['requirements'],[{'role':'identity','minimum':1}])
    with pytest.raises(ValueError,match='checklist'):
        execute_workflow({'document':model.document,'recipe':dict(DEFAULT_RECIPE,steps=['merge','export']),
            'output_directory':str(tmp_path/'exports')},tmp_path/'job')
    assert not (tmp_path/'exports').exists()


def test_form_changes_survive_export_and_undo_without_modifying_source(form_pdf,tmp_path):
    original=form_pdf.read_bytes();model=model_for(form_pdf,tmp_path);asset=next(iter(model.document['assets']))
    check=next(row for row in inspect_fields(form_pdf) if row['name']=='confirmed')
    model.set_value(['assets',asset,'form_values'],{'applicant':'Reviewed','confirmed':check['on_state']})
    output=assemble_workspace(model.document,tmp_path/'filled.pdf')
    values={row['name'].split('.')[-1]:row['value'] for row in ValidationService.inspect_pdf(output)['fields']}
    assert values['applicant']=='Reviewed' and values['confirmed']==check['on_state']
    model.undo();assemble_workspace(model.document,tmp_path/'original.pdf')
    assert any(row['value']=='Before' for row in ValidationService.inspect_pdf(tmp_path/'original.pdf')['fields'])
    assert form_pdf.read_bytes()==original


@pytest.mark.parametrize('rotation,cropped',[(0,False),(90,False),(270,True)])
def test_redaction_selection_matches_rotated_and_cropped_pdf(form_pdf,tmp_path,rotation,cropped):
    source=tmp_path/'rotated.pdf'
    with fitz.open(form_pdf) as pdf:
        page=pdf[0]
        if cropped:page.set_cropbox(fitz.Rect(10,10,390,390))
        page.set_rotation(rotation);pdf.save(source)
    model=model_for(source,tmp_path);reference=model.document['pages'][0]
    with fitz.open(source) as pdf:
        page=pdf[0];box=page.search_for('CONFIDENTIAL SOURCE')[0]*page.rotation_matrix
        box+=(-2,-2,2,2)
        selection=[box.x0/page.rect.width,box.y0/page.rect.height,box.x1/page.rect.width,box.y1/page.rect.height]
    rect=selection_to_redaction(model.document,reference['id'],selection)
    model.edit(reference['id'],{'operation':'redact','rect':rect})
    output=assemble_workspace(model.document,tmp_path/'redacted.pdf')
    with fitz.open(output) as pdf:
        assert 'CONFIDENTIAL' not in pdf[0].get_text() and 'PUBLIC RECORD' in pdf[0].get_text()
    assert 'CONFIDENTIAL' in ''.join(ValidationService.inspect_pdf(source)['text'])


def test_privacy_policy_is_verified_on_final_export(form_pdf,tmp_path):
    model=model_for(form_pdf,tmp_path);reference=model.document['pages'][0]
    model.edit(reference['id'],{'operation':'redact','rect':[20,35,220,70]})
    recipe=dict(DEFAULT_RECIPE,steps=['compress','merge','export'],max_bytes=0,review_before_export=False,
        privacy={'remove_metadata':True,'remove_comments':True,'remove_attachments':True})
    result=execute_workflow({'document':model.document,'recipe':recipe,'output_directory':str(tmp_path/'exports')},tmp_path/'job')
    assert result['state']=='succeeded'
    checks=privacy_checks(result['outputs'][0],recipe['privacy']);assert all(row['passed'] for row in checks)
    assert all(row['passed'] for row in result['reports'])
    assert not ValidationService.inspect_pdf(result['outputs'][0])['attachments']


def test_redaction_removes_overlapping_form_values_and_comments(form_pdf,tmp_path):
    model=model_for(form_pdf,tmp_path);key=model.document['pages'][0]['id']
    model.edit(key,{'operation':'redact','rect':[20,230,320,340]})
    output=assemble_workspace(model.document,tmp_path/'redacted-fields.pdf')
    with fitz.open(output) as document:
        assert not list(document[0].widgets() or []) and not list(document[0].annots() or [])


def test_portable_project_restores_snapshots_history_and_presets(pdf,tmp_path):
    first=WorkspaceStore(tmp_path/'first/state.sqlite');model=model_for(pdf,first.path.parent)
    model.edit(model.document['pages'][0]['id'],{'operation':'rotate','angle':90})
    project=first.save_project('Portable',model.serialize());first.save_workflow('Saved recipe',DEFAULT_RECIPE)
    archive=export_project(first.path,project,tmp_path/'project.odtproject')
    shutil.rmtree(first.path.parent/'imports')
    second=WorkspaceStore(tmp_path/'second/state.sqlite');result=import_project(second.path,archive)
    loaded=WorkspaceModel(second.project(result['id']));loaded.undo()
    assert loaded.document['pages'][0]['rotation']==0
    assert Path(next(iter(loaded.document['assets'].values()))['pdf']).is_file()
    assert second.workflows()[0]['name']=='Saved recipe'
    assemble_workspace(loaded.document,tmp_path/'restored.pdf')


def test_project_archive_rejects_traversal_and_checksum_changes(pdf,tmp_path):
    store=WorkspaceStore(tmp_path/'state.sqlite');model=model_for(pdf,tmp_path)
    project=store.save_project('Example',model.serialize());good=export_project(store.path,project,tmp_path/'good.odtproject')
    with zipfile.ZipFile(good) as source:records={name:source.read(name) for name in source.namelist()}
    for extra in ['../escape.pdf', 'payload/../../escape.pdf']:
        broken=tmp_path/'unsafe.odtproject'
        with zipfile.ZipFile(broken,'w') as archive:
            for name,data in records.items():archive.writestr(name,data)
            archive.writestr(extra,b'not allowed')
        with pytest.raises(ValueError,match='Unsafe'):import_project(store.path,broken)
    payload=next(name for name in records if name.startswith('payload/'));records[payload]=b'changed'
    with zipfile.ZipFile(tmp_path/'corrupt.odtproject','w') as archive:
        for name,data in records.items():archive.writestr(name,data)
    with pytest.raises(ValueError,match='checksum'):import_project(store.path,tmp_path/'corrupt.odtproject')


def test_workspace_backup_restores_review_checkpoints_and_paths(pdf,tmp_path):
    first=WorkspaceStore(tmp_path/'first/workspace.sqlite3');model=model_for(pdf,first.path.parent)
    first.save_project('Example',model.serialize())
    index_documents([next(iter(model.document['assets'].values()))['pdf']],first.path)
    spec={'document':model.document,'recipe':dict(DEFAULT_RECIPE,steps=['merge','export'],max_bytes=0),
          'output_directory':str(tmp_path/'exports'),'database_path':str(first.path)}
    job_id=first.enqueue('Example',spec);work=first.path.parent/'jobs'/job_id
    result=execute_workflow(spec,work);first.update_job(job_id,state='needs_review',result=result)
    backup=backup_workspace(first.path,tmp_path/'workspace.odtbackup')
    restored=Path(restore_workspace(backup,tmp_path/'restored'));second=WorkspaceStore(restored/'workspace.sqlite3')
    loaded=second.job(job_id);assert loaded['state']=='needs_review'
    assert loaded['spec']['database_path']==str(second.path)
    library=second.search('TOOLKIT');assert library and library[0]['path'].startswith(str(restored))
    assert next(iter(loaded['spec']['document']['assets'].values()))['pdf'].startswith(str(restored))
    shutil.rmtree(first.path.parent/'imports')
    approve_export(restored/'jobs'/job_id)
    complete=execute_workflow(loaded['spec'],restored/'jobs'/job_id)
    assert complete['state']=='succeeded' and 'assemble' in complete['reused_stages']
    with pytest.raises(ValueError,match='empty'):restore_workspace(backup,restored)


def test_backup_refuses_running_jobs_and_restores_queued_jobs_as_paused(pdf,tmp_path):
    store=WorkspaceStore(tmp_path/'data/workspace.sqlite3');job=store.enqueue('Example',{'example':1})
    store.update_job(job,state='running')
    with pytest.raises(ValueError,match='Pause'):backup_workspace(store.path,tmp_path/'backup.odtbackup')
    store.update_job(job,state='queued');backup_workspace(store.path,tmp_path/'backup.odtbackup')
    restored=restore_workspace(tmp_path/'backup.odtbackup',tmp_path/'restored')
    assert WorkspaceStore(Path(restored)/'workspace.sqlite3').job(job)['state']=='paused'


def test_cache_cleanup_protects_undo_snapshots_and_job_specs(pdf,tmp_path):
    store=WorkspaceStore(tmp_path/'data/workspace.sqlite3');model=model_for(pdf,store.path.parent)
    project=store.save_project('Saved',model.serialize())
    asset=next(iter(model.document['assets'].values()));cached=Path(asset['pdf'])
    orphan=store.path.parent/'imports/orphan.pdf';orphan.write_bytes(b'unused')
    for path in (cached,orphan):os.utime(path,(0,0))
    job=store.enqueue('Queued',{'document':model.document});model.undo();store.save_project('Saved',model.serialize(),project)
    cleaned=cleanup_storage(store.path)
    assert cleaned['files']==1 and not orphan.exists() and cached.exists()
    store.delete_project(project)
    store.update_job(job,state='cancelled');store.delete_job(job)
    cleanup_storage(store.path);assert not cached.exists() and pdf.exists()


def test_library_labels_duplicates_reindex_and_relink(pdf,tmp_path):
    store=WorkspaceStore(tmp_path/'state.sqlite');copy=tmp_path/'copy.pdf';shutil.copyfile(pdf,copy)
    index_documents([pdf,copy],store.path);store.set_labels(pdf,['application','important'],'Submissions')
    assert len(store.duplicate_documents())==2
    assert store.search('TOOLKIT',tag='important',collection='Submissions')[0]['path']==str(pdf)
    moved=tmp_path/'moved.pdf';pdf.rename(moved);relink_document(store.path,pdf,moved)
    assert store.search('',tag='important')[0]['path']==str(moved)
    with fitz.open() as document:document.new_page().insert_text((30,40),'UPDATED CONTENT');document.save(moved)
    result=refresh_documents(store.path,force=True)
    assert str(moved) in result['changed'] and store.search('UPDATED',tag='important')
    assert not store.search('TOOLKIT',tag='important')
    copy.unlink();assert str(copy) in refresh_documents(store.path)['missing']


def test_comparison_detects_visual_and_text_changes_and_has_overlay(pdf,tmp_path):
    model=model_for(pdf,tmp_path);reference=model.document['pages'][0]
    model.edit(reference['id'],{'operation':'rotate','angle':90})
    output=assemble_workspace(model.document,tmp_path/'changed.pdf')
    comparison=prepare_packet_review(model.document,[output],tmp_path/'review')
    assert comparison['pages'][0]['visual_changed'] and comparison['pages'][0]['geometry_changed']
    image=render_difference(comparison['before'],comparison['after'],0)
    assert image.width>0 and any(r>g+20 for r,g,b in image.getdata())
    with patch('services.review_service.assemble_workspace',side_effect=AssertionError('Unchanged review reran')):
        assert prepare_packet_review(model.document,[output],tmp_path/'review')['signature']==comparison['signature']


def test_embedded_viewer_navigation_search_and_ocr_controls(qapp,pdf,tmp_path):
    from ui.document_review_dialog import DocumentReviewDialog
    dialog=DocumentReviewDialog(pdf,pdf,initial_page=1,query='TOOLKIT');dialog.show()
    qapp.processEvents();dialog.search()
    assert dialog.page.value()==2 and all(pdf.pageCount()==3 for pdf in dialog.documents)
    assert all(model.searchString()=='TOOLKIT' for model in dialog.models)
    dialog.tabs.setCurrentIndex(1)
    wait_until(qapp,lambda:dialog.difference.pixmap() is not None,timeout=20)
    dialog.close()


def test_form_and_checklist_dialogs_save_user_choices(qapp,form_pdf):
    from ui.submission_dialogs import FormFieldsDialog,ChecklistDialog
    fields=FormFieldsDialog(inspect_fields(form_pdf));fields.controls['applicant'].setText('Entered in app');fields.save()
    assert fields.values['applicant']=='Entered in app'
    checklist=ChecklistDialog([]);checklist.profile.setCurrentText('Application packet');checklist.save()
    assert {'application','identity','certificate'}=={row['role'] for row in checklist.requirements}
    fields.close();checklist.close()


def test_multi_document_role_assignment_undoes_as_one_action(pdf,tmp_path):
    model=model_for(pdf,tmp_path);model.import_assets(import_documents([pdf],tmp_path/'imports')['assets'])
    model.set_many_values([(['assets',key,'role'],'identity') for key in model.document['assets']])
    assert all(asset['role']=='identity' for asset in model.document['assets'].values())
    model.undo();assert all(asset['role']=='unassigned' for asset in model.document['assets'].values())
    model.redo();assert all(asset['role']=='identity' for asset in model.document['assets'].values())


def test_preview_cache_reuses_identical_edits_and_changes_with_form_values(form_pdf,tmp_path):
    from services.workspace_service import cached_workspace_preview
    model=model_for(form_pdf,tmp_path);reference=model.document['pages'][0]
    first=cached_workspace_preview(model.document,reference['id'])
    with patch('services.workspace_service.render_workspace_page',side_effect=AssertionError('Cache miss')):
        cached=cached_workspace_preview(model.document,reference['id'])
    assert first.tobytes()==cached.tobytes()
    model.set_value(['assets',reference['asset'],'form_values'],{'applicant':'New value'})
    changed=cached_workspace_preview(model.document,reference['id'])
    assert first.tobytes()!=changed.tobytes()


def test_export_report_omits_internal_staging_paths(pdf,tmp_path):
    model=model_for(pdf,tmp_path)
    result=execute_workflow({'document':model.document,'recipe':dict(DEFAULT_RECIPE,steps=['merge','export'],
        max_bytes=0,review_before_export=False),'output_directory':str(tmp_path/'exports')},tmp_path/'job')
    report=json.loads((Path(result['outputs'][0]).parent/'export-report.json').read_text())
    assert 'staged' not in report and 'review_file' not in report
    assert all(Path(name).name==name for name in report['outputs'])


def test_missing_signing_credentials_are_reported_and_required_signing_fails(tmp_path):
    from scripts.sign_release import sign
    executable=tmp_path/'application.exe';executable.write_bytes(b'synthetic')
    with patch('scripts.sign_release.platform.system',return_value='Windows'),patch.dict(os.environ,{'ODT_WINDOWS_CERT_SHA1':''}):
        assert sign(executable)['status']=='unsigned'
        with pytest.raises(RuntimeError,match='identity'):sign(executable,required=True)


def test_installer_system_changes_are_restricted_to_disposable_ci(tmp_path,monkeypatch):
    from scripts.verify_installer import verify
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    with pytest.raises(RuntimeError,match='disposable'):
        verify(tmp_path/'application.deb',tmp_path/'reports',system_install=True)


def test_app_and_package_versions_match():
    import tomllib
    from utils.version import VERSION
    project=tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())
    assert VERSION==project['project']['version']


def test_embedded_review_includes_field_appearances_without_flattening_export(form_pdf,tmp_path):
    model=model_for(form_pdf,tmp_path);asset=next(iter(model.document['assets']))
    model.set_value(['assets',asset,'form_values'],{'applicant':'Visible form value'})
    output=assemble_workspace(model.document,tmp_path/'output.pdf')
    comparison=prepare_packet_review(model.document,[output],tmp_path/'review')
    with fitz.open(comparison['viewer_after']) as display:
        assert 'Visible form value' in display[0].get_text()
    assert any(field['value']=='Visible form value' for field in ValidationService.inspect_pdf(output)['fields'])


def test_uncertain_line_retry_does_not_invent_an_extra_word():
    from services.ocr_recognition import recognize
    def response(words,confidence):
        count=len(words)
        return {'text':words,'conf':[confidence]*count,'left':[10+50*i for i in range(count)],
            'top':[10]*count,'width':[40]*count,'height':[20]*count,'block_num':[1]*count,'par_num':[1]*count,'line_num':[1]*count}
    def fake(image,**kwargs):
        return response(['original','words','invented'],99) if '--psm 7' in kwargs['config'] else response(['original','words'],50)
    with patch('pytesseract.image_to_data',side_effect=fake):
        data,report=recognize(Image.new('RGB',(400,100),'white'),'eng',400)
    assert data['text']==['original','words']
    assert any('line retries' in row['method'] for row in report['attempts'])


def test_low_confidence_ocr_retry_retains_text_coverage():
    from services.ocr_recognition import choose
    complete=[{'text':'example','conf':70} for _ in range(10)]
    partial=[{'text':'example','conf':99}]
    assert choose([(complete,'complete'),(partial,'partial')])[1]=='complete'


def test_cleanup_protects_library_files_inside_managed_cache(pdf,tmp_path):
    store=WorkspaceStore(tmp_path/'data/workspace.sqlite3');model=model_for(pdf,store.path.parent)
    source=Path(next(iter(model.document['assets'].values()))['pdf'])
    index_documents([source],store.path);os.utime(source,(0,0))
    cleanup_storage(store.path)
    assert source.is_file() and store.search('TOOLKIT')
