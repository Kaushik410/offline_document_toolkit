"""Bounded page comparison and cached originals for the embedded review UI."""
from pathlib import Path
import copy
import io
import json
import hashlib
from collections import Counter
import fitz
import numpy as np
from PIL import Image,ImageChops,ImageDraw
from pypdf import PdfReader,PdfWriter
from services.workspace_service import assemble_workspace
from services.validation_service import file_hash
from services.ocr_pipeline import write_json
from utils.output_utils import atomic_output


def _image(page,dpi=60):
    pix=page.get_pixmap(dpi=dpi,colorspace=fitz.csRGB,alpha=False)
    return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)


def prepare_packet_review(document,outputs,directory,progress_callback=None):
    work=Path(directory);work.mkdir(parents=True,exist_ok=True)
    signature=hashlib.sha256(json.dumps(['v040-display',document,[file_hash(path) for path in outputs]],sort_keys=True).encode()).hexdigest()
    checkpoint=work/'comparison.json'
    if checkpoint.exists():
        saved=json.loads(checkpoint.read_text())
        if saved.get('signature')==signature and Path(saved['before']).exists() and Path(saved['after']).exists():return saved
    original=copy.deepcopy(document)
    for asset in original['assets'].values():asset.pop('form_values',None)
    for page in original['pages']:
        page.update(edits=[],rotation=0,crop=None,redactions=[])
    before=assemble_workspace(original,work/'original.pdf')
    if len(outputs)==1 and Path(outputs[0]).suffix.lower()=='.pdf':after=str(outputs[0])
    else:
        writer=PdfWriter()
        for path in outputs:
            if Path(path).suffix.lower()=='.pdf':writer.append(PdfReader(path),import_outline=False)
            else:
                with Image.open(path) as image:
                    with fitz.open() as pdf:
                        page=pdf.new_page(width=image.width*72/150,height=image.height*72/150)
                        buffer=io.BytesIO();image.convert('RGB').save(buffer,format='PNG')
                        page.insert_image(page.rect,stream=buffer.getvalue())
                        writer.append(PdfReader(io.BytesIO(pdf.tobytes())),import_outline=False)
        after=str(work/'export-preview.pdf')
        with atomic_output(after) as temporary:writer.write(temporary)
    rows=[]
    with fitz.open(before) as a,fitz.open(after) as b:
        for index in range(max(len(a),len(b))):
            row={'page':index,'visual_changed':True,'text_changed':True,'bounds':None}
            if index<len(a) and index<len(b):
                left,right=_image(a[index]),_image(b[index])
                width,height=max(left.width,right.width),max(left.height,right.height)
                canvases=[]
                for image in (left,right):
                    canvas=Image.new('RGB',(width,height),'white');canvas.paste(image,(0,0));canvases.append(canvas)
                delta=ImageChops.difference(*canvases).convert('L').point(lambda value:255 if value>16 else 0)
                changed=np.asarray(delta)>0
                box=delta.getbbox();fraction=float(changed.mean())
                row.update(visual_changed=fraction>.0001,text_changed=Counter(a[index].get_text().split())!=Counter(b[index].get_text().split()),
                    fraction=fraction,bounds=[box[0]/width,box[1]/height,box[2]/width,box[3]/height] if box else None,
                    geometry_changed=list(a[index].rect)!=list(b[index].rect))
                del left,right,canvases,delta,changed
                fitz.TOOLS.store_shrink(100)
            rows.append(row)
            if progress_callback:progress_callback(int((index+1)/max(len(a),len(b))*100))
    result={'signature':signature,'before':before,'after':after,'pages':rows,
            'viewer_before':prepare_view_copy(before,work/'display'),'viewer_after':prepare_view_copy(after,work/'display')}
    write_json(checkpoint,result)
    return result


def render_difference(before,after,page_number,dpi=120):
    with fitz.open(before) as a,fitz.open(after) as b:
        images=[]
        for pdf in (a,b):
            images.append(_image(pdf[page_number],dpi) if page_number<len(pdf) else Image.new('RGB',(600,800),'white'))
        width,height=max(image.width for image in images),max(image.height for image in images)
        canvases=[]
        for image in images:
            canvas=Image.new('RGB',(width,height),'white');canvas.paste(image,(0,0));canvases.append(canvas)
        mask=ImageChops.difference(*canvases).convert('L').point(lambda value:110 if value>16 else 0)
        result=canvases[1].convert('RGBA')
        overlay=Image.new('RGBA',result.size,(220,38,38,0));overlay.putalpha(mask)
        result=Image.alpha_composite(result,overlay).convert('RGB')
        box=mask.getbbox()
        if box:ImageDraw.Draw(result).rectangle(box,outline='#dc2626',width=3)
    fitz.TOOLS.store_shrink(100)
    return result


def prepare_view_copy(path,directory):
    """QPdfView omits widget/annotation appearances; bake a display-only copy."""
    path=Path(path);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with fitz.open(path) as pdf:
        needs_copy=any(page.first_widget or page.first_annot for page in pdf)
        if not needs_copy:return str(path)
        output=directory/(file_hash(path)+'.display.pdf')
        if not output.exists():
            pdf.bake(annots=True,widgets=True)
            with atomic_output(output) as temporary:pdf.save(temporary,garbage=4,deflate=True)
    fitz.TOOLS.store_shrink(100)
    return str(output)
