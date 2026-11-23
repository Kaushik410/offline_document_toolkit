from pathlib import Path
import fitz
from services.validation_service import file_hash
from services.workspace_store import WorkspaceStore


def index_documents(paths,database_path=None,progress_callback=None):
    store=WorkspaceStore(database_path);results=[];errors=[]
    for index,path in enumerate(paths):
        try:
            with fitz.open(path) as document:
                if document.needs_pass:raise ValueError('Unlock the PDF before indexing.')
                texts=[page.get_text() for page in document]
            store.index_document(path,file_hash(path),texts);results.append(str(path))
        except Exception as error:errors.append({'path':str(path),'error':str(error)})
        if progress_callback:progress_callback(int((index+1)/len(paths)*100))
    return {'indexed':results,'errors':errors}


def refresh_documents(database_path,progress_callback=None,force=False):
    store=WorkspaceStore(database_path)
    with store.connect() as db:records=[dict(row) for row in db.execute('SELECT path,fingerprint,file_size,modified_ns FROM documents')]
    changed=[];missing=[];errors=[]
    for index,row in enumerate(records):
        path=Path(row['path'])
        if not path.is_file():missing.append(str(path))
        else:
            try:
                stat=path.stat()
                changed_metadata=stat.st_size!=row['file_size'] or stat.st_mtime_ns!=row['modified_ns']
                if (force or changed_metadata) and file_hash(path)!=row['fingerprint']:
                    result=index_documents([path],database_path)
                    changed.extend(result['indexed']);errors.extend(result['errors'])
                elif changed_metadata:
                    with store.connect() as db:db.execute('UPDATE documents SET file_size=?,modified_ns=? WHERE path=?',(stat.st_size,stat.st_mtime_ns,str(path)))
            except Exception as error:errors.append({'path':str(path),'error':str(error)})
        if progress_callback:progress_callback(int((index+1)/max(1,len(records))*100))
    return {'changed':changed,'missing':missing,'errors':errors}


def relink_document(database_path,old_path,new_path):
    store=WorkspaceStore(database_path);new_path=Path(new_path).resolve()
    with store.connect() as db:
        row=db.execute('SELECT fingerprint FROM documents WHERE path=?',(str(Path(old_path).resolve()),)).fetchone()
        if not row:raise KeyError('The library entry no longer exists.')
        if file_hash(new_path)!=row[0]:raise ValueError('The replacement is a different document. Index it as a new file.')
        db.execute('UPDATE documents SET path=? WHERE path=?',(str(new_path),str(Path(old_path).resolve())))
    return str(new_path)
