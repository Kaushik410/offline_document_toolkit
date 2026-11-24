"""Release checks fail closed and distinguish real upgrades from reinstallation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from unittest.mock import patch
import pytest

from scripts.build_previous_release import unpack_baseline
from scripts.verify_installer import ensure_upgrade,prepare_fixture,preserved,native_check
from scripts.sign_release import sign

ROOT=Path(__file__).parents[1]


def test_audited_previous_source_is_real_version_and_excludes_user_data(tmp_path):
    import tomllib
    source,manifest=unpack_baseline(tmp_path/'baseline')
    assert manifest['version']=='0.4.0'
    assert tomllib.loads((source/'pyproject.toml').read_text())['project']['version']=='0.4.0'
    assert (source/'utils/self_test.py').is_file()
    assert not (source/'local_data').exists()
    assert not (source/'app_settings.json').exists()


def test_baseline_checksum_is_checked_before_extraction(tmp_path):
    archive=tmp_path/'changed.zip';archive.write_bytes(b'not the audited source')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'file':archive.name,'sha256':'0'*64}))
    with pytest.raises(ValueError,match='checksum'):unpack_baseline(tmp_path/'destination',manifest)
    assert not (tmp_path/'destination').exists()


@pytest.mark.parametrize('old,new,accepted',[('0.4.0','0.4.1',True),('0.4.1','0.4.1',False),('0.5.0','0.4.1',False)])
def test_windows_upgrade_requires_a_strictly_older_package(old,new,accepted):
    with patch('scripts.verify_installer.installer_version',side_effect=[old,new]):
        if accepted:assert ensure_upgrade('previous.exe','current.exe','Windows')=={'from':old,'to':new}
        else:
            with pytest.raises(ValueError,match='older'):ensure_upgrade('previous.exe','current.exe','Windows')


def test_required_libreoffice_does_not_skip_when_missing(tmp_path,monkeypatch):
    from tests.test_documents import test_real_docx_to_pdf
    monkeypatch.setenv('ODT_REQUIRE_LIBREOFFICE','1')
    with patch('utils.engine_registry.EngineRegistry.find',return_value=None):
        with pytest.raises(pytest.fail.Exception,match='required'):test_real_docx_to_pdf(tmp_path)


def test_native_acceptance_requires_a_frozen_runtime(tmp_path):
    report=tmp_path/'report.json';report.write_text(json.dumps({'passed':True,'runtime':{'frozen':False}}))
    with patch('scripts.verify_installer.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
        with pytest.raises(RuntimeError,match='bundled'):native_check('launcher',report)


def test_native_required_libreoffice_cannot_be_omitted(tmp_path):
    report=tmp_path/'report.json';report.write_text(json.dumps({'passed':True,'runtime':{'frozen':True},'libreoffice':{'verified':False}}))
    with patch('scripts.verify_installer.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as command:
        with pytest.raises(RuntimeError,match='LibreOffice'):native_check('launcher',report,require_libreoffice=True)
    assert '--require-libreoffice' in command.call_args.args[0]


def test_native_acceptance_rejects_cleanup_error_even_with_success_flag(tmp_path):
    report=tmp_path/'report.json'
    report.write_text(json.dumps({'passed':True,'runtime':{'frozen':True},'error':'Preview file still locked'}))
    with patch('scripts.verify_installer.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
        with pytest.raises(RuntimeError,match='Preview file still locked'):
            native_check('launcher',report)


def test_cloud_signing_requires_the_action_before_verification(tmp_path):
    artifact=tmp_path/'app.exe';artifact.write_bytes(b'synthetic')
    with patch('scripts.sign_release.platform.system',return_value='Windows'):
        with pytest.raises(RuntimeError,match='action first'):sign(artifact,provider='azure')
        with patch('scripts.sign_release.verify_signature',return_value={'authenticode_status':'Valid','timestamp_subject':'Timestamp CA'}):
            result=sign(artifact,required=True,provider='azure',verify_only=True)
            assert result['status']=='signed-and-verified' and result['provider']=='azure'


def test_failed_authenticode_verification_never_reports_success(tmp_path):
    artifact=tmp_path/'app.exe';artifact.write_bytes(b'synthetic')
    with patch('scripts.sign_release.platform.system',return_value='Windows'),patch('scripts.sign_release.verify_signature',side_effect=RuntimeError('bad signature')):
        with pytest.raises(RuntimeError,match='bad signature'):sign(artifact,provider='azure',verify_only=True)


def test_native_gui_probe_reopens_and_preserves_legacy_project(tmp_path):
    fixture=prepare_fixture(tmp_path/'profile/workspace',tmp_path/'exports',tmp_path/'input.pdf')
    report=tmp_path/'probe.json'
    result=subprocess.run([sys.executable,str(ROOT/'main.py'),'--probe-workspace',fixture['data'],'--probe-report',str(report)],
        cwd=ROOT,env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=80)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(report.read_text())['passed']
    preserved(fixture)


def test_backup_and_restore_release_every_database_handle(tmp_path,monkeypatch):
    import sqlite3
    from services.project_archive import backup_workspace,restore_workspace
    from services.workspace_store import WorkspaceStore
    original=sqlite3.connect;opened=set()
    class TrackedConnection(sqlite3.Connection):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);opened.add(self)
        def close(self):
            try:super().close()
            finally:opened.discard(self)
    def connect(*args,**kwargs):return original(*args,**dict(kwargs,factory=TrackedConnection))
    monkeypatch.setattr(sqlite3,'connect',connect)
    try:
        store=WorkspaceStore(tmp_path/'data/workspace.sqlite3')
        store.enqueue('Synthetic job',{})
        backup=backup_workspace(store.path,tmp_path/'workspace.odtbackup')
        assert not opened,'Backup retained SQLite handles'
        restore_workspace(backup,tmp_path/'restored')
        assert not opened,'Restore retained SQLite handles'
    finally:
        for connection in list(opened):connection.close()


def test_upgrade_checks_fresh_install_before_existing_user_data(tmp_path,monkeypatch):
    from scripts import verify_installer as verifier
    current=tmp_path/'current.deb';current.touch()
    previous=tmp_path/'previous.deb';previous.touch()
    profile=tmp_path/'profile'
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('CI','true')
    monkeypatch.setattr(verifier.platform,'system',lambda:'Linux')
    monkeypatch.setattr(verifier,'profile_folder',lambda system:profile)
    monkeypatch.setattr(Path,'home',staticmethod(lambda:tmp_path/'home'))
    monkeypatch.setattr(verifier,'ensure_upgrade',lambda *args:{'from':'0.4.0','to':'0.4.1'})
    installed=None;checks=[]
    def command(args,**kwargs):
        nonlocal installed
        if args[:4]==['sudo','-n','apt-get','install']:
            installed=Path(args[-1])
        elif args[:4]==['sudo','-n','apt-get','remove']:
            assert installed==current
            installed=None
        elif '--probe-report' in args:
            assert installed==current and (profile/'workspace/workspace.sqlite3').exists()
            Path(args[args.index('--probe-report')+1]).write_text(json.dumps({'passed':True,'runtime':{'frozen':True}}))
        else:raise AssertionError('Unexpected external command: '+str(args))
        return subprocess.CompletedProcess(args,0)
    def acceptance(executable,report,*args):
        assert installed==current
        checks.append((profile/'workspace/workspace.sqlite3').exists())
        return {'passed':True,'runtime':{'frozen':True}}
    monkeypatch.setattr(verifier.subprocess,'run',command)
    monkeypatch.setattr(verifier,'native_check',acceptance)
    report=verifier.verify(current,tmp_path/'reports',previous,system_install=True)
    assert checks==[False,True] # A clean install, then the real seeded upgrade fixture.
    assert report['passed'] and report['user_data_preserved'] and report['uninstall']
    assert installed is None


def test_release_matrices_exclude_macos_and_keep_required_checks():
    # These are release acceptance requirements rather than an assertion about
    # a particular YAML parser (YAML 1.1 also treats "on" as a boolean).
    ci=(ROOT/'.github/workflows/ci.yml').read_text()
    release=(ROOT/'.github/workflows/installers.yml').read_text()
    assert 'macos-' not in ci+release and "'Darwin'" not in release
    assert 'ODT_REQUIRE_LIBREOFFICE' in ci+release
    assert '--require-libreoffice' in release and '--system-install' in release
    assert 'build_previous_release.py' in release
    assert 'azure/artifact-signing-action@v2' in release
    assert '--gui-platform xcb' in release and "'--gui-platform','windows'" in release


def test_system_engine_environment_restores_user_library_paths_without_mutating_parent(monkeypatch,tmp_path):
    import sys
    from utils.external_process import system_environment
    bundle=tmp_path/'bundle';bundle.mkdir()
    monkeypatch.setattr(sys,'frozen',True,raising=False);monkeypatch.setattr(sys,'_MEIPASS',str(bundle),raising=False)
    environment={'LD_LIBRARY_PATH':str(bundle),'LD_LIBRARY_PATH_ORIG':'/usr/local/lib',
        'PATH':str(bundle/'tools')+os.pathsep+'/usr/bin','QT_PLUGIN_PATH':str(bundle/'Qt/plugins')}
    sanitized=system_environment(environment)
    if os.name=='posix':assert sanitized['LD_LIBRARY_PATH']=='/usr/local/lib'
    else:assert sanitized['LD_LIBRARY_PATH']==environment['LD_LIBRARY_PATH']
    assert sanitized['PATH']=='/usr/bin'
    assert 'QT_PLUGIN_PATH' not in sanitized and environment['LD_LIBRARY_PATH']==str(bundle)


def test_unfrozen_external_tools_keep_the_callers_environment():
    from utils.external_process import system_environment
    environment={'PATH':'custom','LD_LIBRARY_PATH':'custom-libraries'}
    assert system_environment(environment)==environment


def test_pdf_viewer_can_close_during_queued_search_and_rendering(pdf):
    program='''
import sys,gc,shutil
from pathlib import Path
from ui.document_review_dialog import DocumentReviewDialog
from utils.qt_runtime import configure_qt_plugins
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtTest import QTest
from shiboken6 import isValid
configure_qt_plugins()
app=QApplication([])
app.setQuitOnLastWindowClosed(False)
for index in range(40):
    preview=Path(sys.argv[1]).with_name(f'preview-{index}.pdf')
    shutil.copyfile(sys.argv[1],preview)
    owner=QWidget()
    dialog=DocumentReviewDialog(preview,preview,query='TOOLKIT',parent=owner)
    dialog.show()
    app.processEvents()
    if index%2==0:
        views=list(dialog.views);models=list(dialog.models);documents=list(dialog.documents)
        dialog.close()
        assert all(not isValid(view) for view in views)
        assert all(not isValid(model) for model in models)
        assert all(not isValid(pdf) for pdf in documents)
        preview.unlink()  # Windows rejects this if QPdfDocument owns an open QFile.
        dialog.search()
        dialog.deleteLater()
    # Also cover parent-driven destruction, which does not call done().
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    preview.unlink(missing_ok=True)
    QTest.qWait(10)
    del dialog,owner
    gc.collect()
QTest.qWait(150)
print('Forty asynchronous PDF viewer closes passed')
'''
    result=subprocess.run([sys.executable,'-c',program,str(pdf)],cwd=ROOT,
        env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'Forty asynchronous PDF viewer closes passed' in result.stdout
    assert 'Traceback' not in result.stderr
