"""Inventory and conservative cleanup of unreferenced managed cache files."""
from pathlib import Path
import json
import shutil
import time
from contextlib import nullcontext
from services.workspace_store import WorkspaceStore


def referenced_paths(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        for child in value.values():yield from referenced_paths(child)
    elif isinstance(value,list):
        for child in value:yield from referenced_paths(child)


def inspect_storage(database_path,min_age_hours=24,_store=None,_db=None):
    store=_store or WorkspaceStore(database_path);root=store.path.parent.resolve();references=set();jobs=set()
    with (nullcontext(_db) if _db is not None else store.connect()) as db:
        for row in db.execute('SELECT document FROM projects'):
            references.update(referenced_paths(json.loads(row[0])))
        references.update(row[0] for row in db.execute('SELECT path FROM documents'))
        for job_id,spec in db.execute('SELECT id,spec FROM jobs'):
            jobs.add(job_id);references.update(referenced_paths(json.loads(spec)))
    cutoff=time.time()-min_age_hours*3600
    total=0;candidates=[]
    for folder in ['imports','jobs','previews']:
        base=root/folder
        if base.is_symlink():continue
        for path in base.rglob('*'):
            if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=root):continue
            size=path.stat().st_size;total+=size
            if path.stat().st_mtime>cutoff:continue
            relative=path.relative_to(root)
            if str(path.resolve()) in references:continue
            if folder=='jobs' and len(relative.parts)>1 and relative.parts[1] in jobs:continue
            candidates.append({'path':str(path),'bytes':size})
    return {'managed_bytes':total,'reclaimable_bytes':sum(row['bytes'] for row in candidates),
            'candidates':candidates,'database_bytes':sum(path.stat().st_size for path in root.glob(store.path.name+'*') if path.is_file())}


def cleanup_storage(database_path,min_age_hours=24):
    store=WorkspaceStore(database_path)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Recompute the live reference set under the same write lock used by
        # project saves and queue claims, including the entire undo history.
        report=inspect_storage(database_path,min_age_hours,_store=store,_db=db)
        deleted=0
        for row in report['candidates']:
            path=Path(row['path'])
            if path.is_file() and not path.is_symlink():
                try:path.unlink(missing_ok=True);deleted+=row['bytes']
                except (PermissionError,OSError):continue
    return {'deleted_bytes':deleted,'files':len(report['candidates'])}
