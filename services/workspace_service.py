"""Import snapshots and render reversible workspace edits using the existing engines."""
from pathlib import Path
import io
import shutil
import tempfile
import fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject,TextStringObject

from services.image_service import ImageService
from services.pdf_service import PDFService
from services.validation_service import file_hash
from services.workspace_store import data_directory
from utils.output_utils import atomic_output


def import_documents(paths, cache_directory=None, progress_callback=None):
    cache=Path(cache_directory) if cache_directory else data_directory()/'imports'
    cache.mkdir(parents=True,exist_ok=True)
    assets=[];errors=[]
    for number,path in enumerate(paths):
        path=Path(path).resolve()
        try:
            digest=file_hash(path)
            original=cache/f'{digest}-original{path.suffix.lower()}' if path.suffix.lower()!='.pdf' else cache/f'{digest}.pdf'
            if path.suffix.lower()!='.pdf' and not original.exists():
                with atomic_output(original) as temporary:shutil.copyfile(path,temporary)
            normalized=cache/f'{digest}.pdf'
            if not normalized.exists():
                if path.suffix.lower()=='.pdf':
                    with atomic_output(normalized) as temporary:shutil.copyfile(path,temporary)
                elif path.suffix.lower()=='.docx':
                    from services.word_service import WordService
                    WordService.docx_to_pdf(path,cache,output_file=normalized)
                elif path.suffix.lower() in ImageService.SUPPORTED_INPUTS:
                    PDFService.images_to_pdf([str(path)],str(normalized))
                else:raise ValueError('Use PDF, DOCX, or a supported image format.')
            with fitz.open(normalized) as document:
                if document.needs_pass:raise ValueError('Unlock encrypted PDFs before importing.')
                thumbs=[]
                for index,page in enumerate(document):
                    thumb=cache/f'{digest}-{index}.png'
                    if not thumb.exists():
                        with atomic_output(thumb) as temporary:page.get_pixmap(dpi=35,alpha=False).save(temporary)
                    thumbs.append(str(thumb))
                assets.append({'name':path.name,'source':str(path),'source_hash':digest,
                    'pdf':str(normalized),'pdf_hash':file_hash(normalized),'original':str(original),'page_count':len(document),'thumbnails':thumbs})
        except Exception as error:errors.append({'path':str(path),'error':str(error)})
        if progress_callback:progress_callback(int((number+1)/len(paths)*100))
    return {'assets':assets,'errors':errors}


def render_workspace_page(document, page_id, dpi=120):
    reference=next(page for page in document['pages'] if page['id']==page_id)
    asset=document['assets'][reference['asset']]
    with fitz.open(asset['pdf']) as pdf:
        page=pdf[reference['page']]
        from services.form_service import fill_page
        from services.privacy_service import apply_redactions
        fill_page(page,asset.get('form_values',{}))
        apply_redactions(page,reference.get('redactions',[]))
        if reference.get('crop'):
            rect=page.rect
            box=fitz.Rect(reference['crop'])
            page.set_cropbox(fitz.Rect(rect.width*box.x0,rect.height*box.y0,rect.width*box.x1,rect.height*box.y1))
        page.set_rotation((page.rotation+reference['rotation'])%360)
        pix=page.get_pixmap(dpi=dpi,colorspace=fitz.csRGB,alpha=False)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    for edit in reference['edits']:
        params=dict(edit['params'])
        # Region edits are stored as fractions of the preview at that stage.
        if 'rect' in params:
            params['rect']=tuple(round(value*(image.width if index%2==0 else image.height)) for index,value in enumerate(params['rect']))
        if 'point' in params:
            x,y=params.pop('point');params.update(x=round(x*image.width),y=round(y*image.height))
        if 'font_size_fraction' in params:
            params['font_size']=max(8,round(params.pop('font_size_fraction')*image.height))
        image=ImageService.edit_image(image,edit['operation'],**params)
    fitz.TOOLS.store_shrink(100)
    return image


def _assemble_workspace(document, output_file, scratch, progress_callback=None):
    if not document['pages']:raise ValueError('Add at least one page to the workspace.')
    writer=PdfWriter();readers={};attachments=set();metadata_copied=False
    used={page["asset"] for page in document["pages"]}
    for asset_id,asset in document['assets'].items():
        if asset_id not in used:continue
        if file_hash(asset['pdf'])!=asset['pdf_hash']:
            raise ValueError(f"The imported snapshot for {asset['name']} changed. Import it again.")
        input_file=asset['pdf']
        references=[page for page in document['pages'] if page['asset']==asset_id]
        if asset.get('form_values') or any(page.get('redactions') for page in references):
            from services.form_service import fill_document
            from services.privacy_service import apply_redactions
            modified=Path(scratch)/(asset_id+'.pdf')
            with fitz.open(input_file) as pdf:
                fill_document(pdf,asset.get('form_values',{}))
                for reference in references:
                    apply_redactions(pdf[reference['page']],reference.get('redactions',[]))
                pdf.save(modified,garbage=4,deflate=True)
            input_file=modified
        reader=PdfReader(input_file)
        # Prefix existing top-level fields without allocating reader objects.
        # add_form_topname() can reuse an unresolved object's ID in pypdf 6.10.
        form=reader.trailer['/Root'].get('/AcroForm')
        if form:
            for number,field in enumerate(form.get_object().get('/Fields',[])):
                field=field.get_object()
                field[NameObject('/T')]=TextStringObject(f"{asset_id[:8]}.{field.get('/T',number)}")
        readers[asset_id]=reader
    for index,reference in enumerate(document['pages']):
        asset=document['assets'][reference['asset']];reader=readers[reference['asset']]
        if reference['edits']:
            with fitz.open(asset['pdf']) as original:
                original_page=original[reference['page']]
                if list(original_page.widgets() or []):
                    raise ValueError('Image effects would flatten form fields. Remove the image effect from this form page.')
                width,height=original_page.rect.width,original_page.rect.height
            image=render_workspace_page(document,reference['id'],dpi=150)
            # Match physical page geometry after rotations/crops/raster edits.
            with fitz.open() as raster:
                page=raster.new_page(width=image.width*72/150,height=image.height*72/150)
                buffer=io.BytesIO();image.save(buffer,format='PNG')
                page.insert_image(page.rect,stream=buffer.getvalue())
                temporary_reader=PdfReader(io.BytesIO(raster.tobytes()))
                writer.append(temporary_reader,import_outline=False)
        else:
            writer.append(reader,pages=[reference['page']],import_outline=True)
            page=writer.pages[-1]
            if reference.get('crop'):
                box=reference['crop'];left,bottom=float(page.cropbox.left),float(page.cropbox.bottom)
                width,height=float(page.cropbox.width),float(page.cropbox.height)
                page.cropbox.lower_left=(left+box[0]*width,bottom+(1-box[3])*height)
                page.cropbox.upper_right=(left+box[2]*width,bottom+(1-box[1])*height)
            if reference['rotation']:page.rotate(reference['rotation'])
        if progress_callback:progress_callback(int((index+1)/len(document['pages'])*100))
    used={page['asset'] for page in document['pages']}
    for asset_id in used:
        reader=readers[asset_id]
        if reader.metadata and not metadata_copied:
            metadata_copied=True
            writer.add_metadata({str(key):str(value) for key,value in reader.metadata.items() if isinstance(value,str)})
        for name,contents in reader.attachments.items():
            for number,data in enumerate(contents):
                final=name;counter=2
                while final in attachments:
                    final=f'{Path(name).stem}_{counter}{Path(name).suffix}';counter+=1
                writer.add_attachment(final,data);attachments.add(final)
    with atomic_output(output_file) as temporary:writer.write(temporary)
    return str(output_file)


def assemble_workspace(document,output_file,progress_callback=None):
    with tempfile.TemporaryDirectory(prefix='odt-assemble-') as scratch:
        return _assemble_workspace(document,output_file,scratch,progress_callback)


def cached_workspace_preview(document,page_id,dpi=120):
    import hashlib,json,os
    reference=next(page for page in document['pages'] if page['id']==page_id)
    asset=document['assets'][reference['asset']]
    key=hashlib.sha256(json.dumps([asset['pdf_hash'],asset.get('form_values',{}),reference,dpi],sort_keys=True).encode()).hexdigest()
    directory=data_directory()/'previews';directory.mkdir(parents=True,exist_ok=True)
    cache=directory/(key+'.png')
    if cache.is_file():
        try:
            with Image.open(cache) as stored:image=stored.copy()
            os.utime(cache,None)
            return image
        except (OSError,ValueError):cache.unlink(missing_ok=True)
    image=render_workspace_page(document,page_id,dpi)
    with atomic_output(cache) as temporary:image.save(temporary,format='PNG')
    entries=[]
    for path in directory.glob('*.png'):
        if path.is_symlink():continue
        try:entries.append((path.stat().st_mtime,path.stat().st_size,path))
        except FileNotFoundError:pass
    total=sum(row[1] for row in entries);count=len(entries)
    for _,size,path in sorted(entries):
        if count<=128 and total<=128*1024**2:break
        if path!=cache:path.unlink(missing_ok=True);total-=size;count-=1
    return image
