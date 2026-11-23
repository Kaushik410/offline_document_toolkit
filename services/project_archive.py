"""Portable projects and workspace backups with checked, bounded ZIP extraction."""
from pathlib import Path,PurePosixPath
import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile

from services.workspace_model import WorkspaceModel
from services.workspace_store import WorkspaceStore
from services.validation_service import file_hash
from services.workflow_service import validate_recipe
from utils.output_utils import atomic_output

MAX_BYTES=8*1024**3
MAX_FILES=100000


def asset_records(value):
    if isinstance(value,dict):
        if {'pdf','pdf_hash','name','page_count'}<=set(value):yield value
        for child in value.values():yield from asset_records(child)
    elif isinstance(value,list):
        for child in value:yield from asset_records(child)


def map_paths(value,mapping):
    if isinstance(value,dict):return {key:map_paths(child,mapping) for key,child in value.items()}
    if isinstance(value,list):return [map_paths(child,mapping) for child in value]
    return mapping.get(value,value) if isinstance(value,str) else value


def checked_manifest(archive,kind):
    entries=archive.infolist()
    if len(entries)>MAX_FILES or sum(item.file_size for item in entries)>MAX_BYTES:
        raise ValueError('Archive exceeds the supported workspace size.')
    names=set()
    for item in entries:
        path=PurePosixPath(item.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename or item.filename in names:
            raise ValueError('Unsafe or duplicate archive path.')
        if (item.external_attr>>16)&0o170000==0o120000:
            raise ValueError('Symbolic links are not supported in project archives.')
        names.add(item.filename)
    if archive.getinfo('manifest.json').file_size>32*1024**2:raise ValueError('Archive manifest is too large.')
    manifest=json.loads(archive.read('manifest.json'))
    if manifest.get('kind')!=kind or manifest.get('version')!=1:
        raise ValueError('Unsupported archive type or version.')
    if set(manifest['files'])|{'manifest.json'}!=names:
        raise ValueError('Archive contents do not match its manifest.')
    return manifest


def extract_checked(archive,manifest,destination):
    for name,expected in manifest['files'].items():
        target=destination/PurePosixPath(name)
        target.parent.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256()
        with archive.open(name) as source,target.open('wb') as output:
            for block in iter(lambda:source.read(1024*1024),b''):
                digest.update(block);output.write(block)
        if digest.hexdigest()!=expected:raise ValueError('Archive checksum mismatch: '+name)


def export_project(database_path,project_id,output_file):
    store=WorkspaceStore(database_path)
    with store.connect() as db:
        row=db.execute('SELECT name,document FROM projects WHERE id=?',(project_id,)).fetchone()
    if not row:raise KeyError('Project no longer exists.')
    saved=json.loads(row['document']);mapping={};files={}
    for asset in asset_records(saved):
        paths=[asset['pdf'],*asset.get('thumbnails',[])]
        if asset.get('original'):paths.append(asset['original'])
        for raw in paths:
            if raw in mapping:continue
            source=Path(raw)
            if not source.is_file():raise FileNotFoundError('A project snapshot is missing: '+source.name)
            digest=file_hash(source);name='payload/'+digest+source.suffix.lower()
            mapping[raw]=name;files[name]=(source,digest)
        # Original absolute source locations are not needed by a portable project.
        asset['source']=asset['name']
    manifest={'kind':'project','version':1,'name':row['name'],'project':map_paths(saved,mapping),
              'workflows':store.workflows(),'files':{name:digest for name,(_,digest) in files.items()}}
    with atomic_output(output_file) as temporary:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,(source,_) in files.items():archive.write(source,name)
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
    return str(output_file)


def import_project(database_path,input_file):
    store=WorkspaceStore(database_path);root=store.path.parent/'imports/portable';root.mkdir(parents=True,exist_ok=True)
    final=root/uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='odt-project-',dir=root) as directory:
        staging=Path(directory)
        with zipfile.ZipFile(input_file) as archive:
            manifest=checked_manifest(archive,'project');extract_checked(archive,manifest,staging)
        mapping={name:str(final/PurePosixPath(name)) for name in manifest['files']}
        project=map_paths(manifest['project'],mapping)
        model=WorkspaceModel(project)
        for asset in asset_records(project):
            if asset['pdf'] not in mapping.values() or file_hash(staging/Path(asset['pdf']).relative_to(final))!=asset['pdf_hash']:
                raise ValueError('Project snapshot integrity check failed.')
        for workflow in manifest.get('workflows',[]):validate_recipe(workflow['recipe'])
        shutil.move(str(staging),str(final))
    try:
        project_id=store.save_project(manifest['name'],model.serialize())
        existing={row['name'] for row in store.workflows()}
        for workflow in manifest.get('workflows',[]):
            if workflow['name'] not in existing:store.save_workflow(workflow['name'],workflow['recipe'])
    except Exception:
        shutil.rmtree(final,ignore_errors=True)
        raise
    return {'id':project_id,'name':manifest['name']}


def backup_workspace(database_path,output_file):
    store=WorkspaceStore(database_path);root=store.path.parent.resolve()
    output=Path(output_file).resolve()
    if output==root or root in output.parents:raise ValueError('Save the backup outside the workspace data folder.')
    with tempfile.TemporaryDirectory(prefix='odt-backup-') as scratch:
        snapshot=Path(scratch)/'workspace.sqlite3'
        with store.connect() as lock:
            lock.execute('BEGIN IMMEDIATE')
            if lock.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                raise ValueError('Pause running jobs before creating a workspace backup.')
            with sqlite3.connect(store.path) as source,sqlite3.connect(snapshot) as destination:source.backup(destination)
            files={'workspace.sqlite3':snapshot}
            for name in ['imports','jobs']:
                if (root/name).is_symlink():continue
                for path in (root/name).rglob('*'):
                    if path.is_file() and not path.is_symlink() and not path.name.startswith('.odt-'):
                        files[path.relative_to(root).as_posix()]=path
            manifest={'kind':'workspace','version':1,'data_root':str(root),'database_name':store.path.name,
                      'files':{name:file_hash(path) for name,path in files.items()}}
            with atomic_output(output_file) as temporary:
                with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
                    for name,path in files.items():archive.write(path,name)
                    archive.writestr('manifest.json',json.dumps(manifest))
    return str(output_file)


def restore_workspace(input_file,destination):
    destination=Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):raise ValueError('Choose a new or empty folder for restoration.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='odt-restore-',dir=destination.parent) as directory:
        staging=Path(directory)
        with zipfile.ZipFile(input_file) as archive:
            manifest=checked_manifest(archive,'workspace');extract_checked(archive,manifest,staging)
        if 'workspace.sqlite3' not in manifest['files']:raise ValueError('The workspace database is missing.')
        old=manifest['data_root']
        mapping={old+'/'+name:str(destination/PurePosixPath(name)) for name in manifest['files']}
        mapping.update({old+'\\'+name.replace('/','\\'):str(destination/PurePosixPath(name)) for name in manifest['files']})
        # Job directories, database filenames and output folders also appear in state.
        for name in manifest['files']:
            for parent in PurePosixPath(name).parents:
                if str(parent)!='.':
                    mapping[old+'/'+str(parent)]=str(destination/parent)
                    mapping[old+'\\'+str(parent).replace('/','\\')]=str(destination/parent)
        mapping[old+'/'+manifest.get('database_name','workspace.sqlite3')]=str(destination/'workspace.sqlite3')
        mapping[old+'\\'+manifest.get('database_name','workspace.sqlite3')]=str(destination/'workspace.sqlite3')
        with sqlite3.connect(staging/'workspace.sqlite3') as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup database is corrupt.')
            for table,column in [('projects','document'),('jobs','spec'),('jobs','result')]:
                for row_id,raw in db.execute(f'SELECT id,{column} FROM {table} WHERE {column} IS NOT NULL').fetchall():
                    db.execute(f'UPDATE {table} SET {column}=? WHERE id=?',(json.dumps(map_paths(json.loads(raw),mapping)),row_id))
            for doc_id,path in db.execute('SELECT id,path FROM documents').fetchall():
                if path in mapping:db.execute('UPDATE documents SET path=? WHERE id=?',(mapping[path],doc_id))
            db.execute('DELETE FROM lease')
            db.execute("UPDATE jobs SET owner=NULL,state='paused' WHERE state IN ('running','queued')")
            jobs={row[0]:json.loads(row[1]) for row in db.execute('SELECT id,spec FROM jobs')}
        for path in (staging/'jobs').rglob('*.json'):
            value=map_paths(json.loads(path.read_text(encoding='utf-8')),mapping)
            if path.name=='checkpoint.json' and path.parent.name in jobs:
                value['signature']=hashlib.sha256(json.dumps(jobs[path.parent.name],sort_keys=True).encode()).hexdigest()
            path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        destination.mkdir(exist_ok=True)
        for path in staging.iterdir():shutil.move(str(path),str(destination/path.name))
    return str(destination)
