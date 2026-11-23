"""Linux/Windows installer checks with a real saved project and native GUI migration probe."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

FIXTURE_ID='upgrade-fixture'


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_environment(gui_platform='offscreen'):
    env=dict(os.environ,QT_QPA_PLATFORM=gui_platform,ODT_NO_SETUP='1')
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    import sys
    python_directories={Path(sys.executable).parent.resolve(),Path(sys.prefix).resolve(),
                        (Path(sys.prefix)/'Scripts').resolve(),(Path(sys.prefix)/'bin').resolve()}
    env['PATH']=os.pathsep.join(item for item in env.get('PATH','').split(os.pathsep)
        if item and Path(item).resolve() not in python_directories)
    return env


def native_check(executable,report,require_libreoffice=False,gui_platform='offscreen'):
    command=[str(executable),'--self-test','--self-test-report',str(report)]
    if require_libreoffice:command.append('--require-libreoffice')
    result=subprocess.run(command,cwd=report.parent,env=native_environment(gui_platform),timeout=240)
    if result.returncode or not report.is_file():raise RuntimeError('Installed application self-test failed.')
    data=json.loads(report.read_text())
    if not data.get('passed'):raise RuntimeError(data.get('error','Native acceptance checks failed.'))
    if not data.get('runtime',{}).get('frozen'):raise RuntimeError('The installer must run its bundled Python runtime.')
    if require_libreoffice and not data.get('libreoffice',{}).get('verified'):
        raise RuntimeError('The required native LibreOffice conversion was not verified.')
    return data


def prepare_fixture(data,output,original):
    import fitz
    data=Path(data);output=Path(output);original=Path(original)
    data.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True);original.parent.mkdir(parents=True,exist_ok=True)
    with fitz.open() as pdf:
        pdf.new_page(width=400,height=500).insert_text((30,50),'UPGRADE FIXTURE: original content')
        pdf.save(original)
    snapshots=data/'imports';snapshots.mkdir()
    snapshot=snapshots/'upgrade-fixture.pdf';shutil.copyfile(original,snapshot)
    exported=output/'preserved-export.pdf';shutil.copyfile(original,exported)
    asset={'name':'upgrade-fixture.pdf','source':str(original),'source_hash':file_digest(original),
        'pdf':str(snapshot),'pdf_hash':file_digest(snapshot),'page_count':1,'thumbnails':[]}
    base={'assets':{'fixture-asset':asset},'pages':[{'id':'fixture-page','asset':'fixture-asset','page':0,'rotation':0,'crop':None,'edits':[]}]}
    edited=copy.deepcopy(base);edited['pages'][0]['rotation']=90
    saved={'history':[base,edited],'position':1}
    with sqlite3.connect(data/'workspace.sqlite3') as db:
        db.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,document TEXT NOT NULL,updated REAL NOT NULL)')
        db.execute('INSERT INTO projects VALUES(?,?,?,?)',(FIXTURE_ID,'Preserved upgrade project',json.dumps(saved),0))
        db.execute('PRAGMA user_version=1')
    (data/'keep-me.txt').write_text('Preserve user workspace',encoding='utf-8')
    (data.parent/'settings.json').write_text(json.dumps({'last_project':FIXTURE_ID,'setup_complete':True,
        'default_output_folder':str(output)}),encoding='utf-8')
    return {'data':str(data),'snapshot':str(snapshot),'original':str(original),'export':str(exported),'hash':file_digest(original)}


def preserved(fixture):
    from services.workspace_model import WorkspaceModel
    data=Path(fixture['data'])
    if (data/'keep-me.txt').read_text()!='Preserve user workspace':raise RuntimeError('User workspace marker was modified.')
    for key in ('snapshot','original','export'):
        if file_digest(fixture[key])!=fixture['hash']:raise RuntimeError('A user document changed during installation: '+key)
    with sqlite3.connect(data/'workspace.sqlite3') as db:
        row=db.execute('SELECT name,document FROM projects WHERE id=?',(FIXTURE_ID,)).fetchone()
    if not row or row[0]!='Preserved upgrade project':raise RuntimeError('The saved user project was lost.')
    model=WorkspaceModel(json.loads(row[1]))
    if model.document['pages'][0]['rotation']!=90:raise RuntimeError('The saved edit was lost.')
    model.undo()
    if model.document['pages'][0]['rotation']!=0:raise RuntimeError('User undo history was lost.')


def installer_version(path,system):
    if system=='Linux':
        return subprocess.check_output(['dpkg-deb','--field',str(path),'Version'],text=True).strip()
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:raise RuntimeError('PowerShell is required to inspect the Windows installer version.')
    # Pass the filename through an environment variable, never interpolate it
    # into PowerShell source code.
    env=dict(os.environ,ODT_INSTALLER_VERSION_PATH=str(Path(path).resolve()))
    return subprocess.check_output([shell,'-NoProfile','-NonInteractive','-Command',
        '[System.Diagnostics.FileVersionInfo]::GetVersionInfo($env:ODT_INSTALLER_VERSION_PATH).ProductVersion'],
        text=True,env=env).strip()


def ensure_upgrade(previous,current,system):
    old,new=installer_version(previous,system),installer_version(current,system)
    if system=='Linux':
        if subprocess.run(['dpkg','--compare-versions',old,'lt',new]).returncode:
            raise ValueError(f'Upgrade verification requires an older package version; found {old} → {new}.')
    else:
        def parts(value):
            if not re.fullmatch(r'\d+(?:\.\d+){1,3}',value):raise ValueError('Unrecognized Windows installer version: '+value)
            values=tuple(map(int,value.split('.')));return values+(0,)*(4-len(values))
        if parts(old)>=parts(new):raise ValueError(f'Upgrade verification requires an older package version; found {old} → {new}.')
    return {'from':old,'to':new}


def profile_folder(system):
    base=Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming')) if system=='Windows' else Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
    return base/'offline-document-toolkit'


def verify(package,output,previous=None,system_install=False,require_libreoffice=False,gui_platform='offscreen'):
    package=Path(package).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    system=platform.system()
    report={'platform':system,'package':package.name,'system_install':system_install,'gui_platform':gui_platform,'passed':False,'stages':[]}
    profile=None;published=None
    def stage(name):report['stages'].append(name)
    try:
        if system not in ('Linux','Windows'):raise RuntimeError('Native installer verification supports Linux and Windows.')
        if system_install and not (os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('CI')=='true'):
            raise RuntimeError('System installation checks require a disposable GitHub Actions runner.')
        if previous and not system_install:raise RuntimeError('A previous-release upgrade check requires system-install mode.')
        if not package.is_file():raise FileNotFoundError(package)
        version_change=ensure_upgrade(Path(previous).resolve(),package,system) if previous else None
        with tempfile.TemporaryDirectory(prefix='odt-install-check-') as directory:
            scratch=Path(directory)
            if system_install:
                profile=profile_folder(system)
                if profile.exists():profile=None;raise RuntimeError('An existing app profile was found; use a clean disposable runner.')
                published=Path.home()/'Documents/Offline Document Toolkit'
                if published.exists():profile=None;published=None;raise RuntimeError('Existing exported documents were found; use a clean disposable runner.')
                data=profile/'workspace';exports=published
            else:data=scratch/'profile/workspace';exports=scratch/'published'
            # Install the real previous release before generating its user state.
            target=scratch/'application'
            if system=='Linux':
                def install(path):subprocess.run(['sudo','-n','apt-get','install','-y',str(path)],check=True)
                executable=Path('/opt/offline-document-toolkit/OfflineDocumentToolkit')
            else:
                def install(path):subprocess.run([str(path),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={target}'],check=True)
                executable=target/'OfflineDocumentToolkit.exe'
            def uninstall():
                if system=='Linux':subprocess.run(['sudo','-n','apt-get','remove','-y','offline-document-toolkit'],check=True)
                else:
                    uninstaller=next(target.glob('unins*.exe'))
                    subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True)
                if executable.exists():raise RuntimeError('The installed application remained after uninstallation.')
            if system_install and previous:
                # Verify the current package on an empty machine independently
                # of upgrading an installed predecessor.
                install(package);stage('Fresh current application installed')
                report['fresh_native']=native_check(executable,output/'fresh-native-self-test.json',require_libreoffice,gui_platform)
                uninstall();stage('Fresh installation verified and uninstalled')
                install(Path(previous).resolve());stage('Previous application installed')
            fixture=prepare_fixture(data,exports,scratch/'original-input.pdf');preserved(fixture)
            if system_install:
                install(package);stage('Current application installed');preserved(fixture)
            elif system=='Linux':
                payload=scratch/'payload';subprocess.run(['dpkg-deb','--extract',str(package),str(payload)],check=True)
                executable=payload/'opt/offline-document-toolkit/OfflineDocumentToolkit';stage('Payload extracted; system installation not run')
            else:raise RuntimeError('Windows installation checks require the disposable CI system-install mode.')
            report['native']=native_check(executable,output/'native-self-test.json',require_libreoffice,gui_platform)
            stage('Bundled runtime and native acceptance tests passed')
            probe_file=output/'workspace-upgrade-probe.json'
            result=subprocess.run([str(executable),'--probe-workspace',str(data),'--probe-report',str(probe_file)],
                cwd=scratch,env=native_environment(gui_platform),timeout=120)
            if result.returncode or not probe_file.is_file():raise RuntimeError('The installed GUI could not reopen the saved user project.')
            probe=json.loads(probe_file.read_text())
            if not probe.get('passed') or not probe.get('runtime',{}).get('frozen'):
                raise RuntimeError('Native saved-project migration verification failed: '+str(probe.get('error','')))
            report['workspace_probe']=probe;preserved(fixture);stage('Installed GUI reopened, edited and exported the preserved project')
            if system_install:
                if not previous:install(package);preserved(fixture);stage('Same-version reinstall passed')
                uninstall()
                preserved(fixture)
                stage('Uninstallation preserved project history, original inputs and published exports')
            report.update(passed=True,user_data_preserved=True,user_data_check='default-app-profile' if system_install else 'isolated-native-migration-fixture',
                upgrade=version_change or ('current-version-reinstall' if system_install else 'system-upgrade-not-run'),uninstall=system_install)
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        (output/'installer-validation.json').write_text(json.dumps(report,indent=2)+'\n')
        # Only paths created after verifying that no user profile already exists
        # are removed. System mode is restricted to disposable CI runners.
        if profile and profile.exists():shutil.rmtree(profile)
        if published and published.exists():shutil.rmtree(published)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    parser.add_argument('--output',type=Path,default=Path('release/installer-validation'))
    parser.add_argument('--previous',type=Path);parser.add_argument('--system-install',action='store_true')
    parser.add_argument('--require-libreoffice',action='store_true')
    parser.add_argument('--gui-platform',choices=['offscreen','xcb','windows'],default='offscreen')
    args=parser.parse_args();print(json.dumps(verify(args.package,args.output,args.previous,args.system_install,args.require_libreoffice,args.gui_platform)))
