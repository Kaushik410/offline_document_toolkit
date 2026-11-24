"""Mixed-content OCR, geometric scan correction, and editable confidence review."""
from pathlib import Path
import copy
import io
import json
import math
import hashlib

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from utils.engine_registry import EngineRegistry
from utils.output_utils import atomic_output


def write_json(path, value):
    with atomic_output(path) as temporary:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def correct_scan(image, auto_rotate=True, deskew=True):
    array=np.array(image.convert('RGB')); transform=np.eye(3); rotation=0; skew=0.0; notes=[]
    if auto_rotate:
        try:
            osd=pytesseract.image_to_osd(image,output_type=pytesseract.Output.DICT,timeout=30)
            rotation=int(osd.get('rotate',0))%360
            if float(osd.get('orientation_conf',0))<2:
                rotation=0;notes.append('Orientation confidence was low; original orientation retained.')
        except (RuntimeError,pytesseract.TesseractError) as error:
            notes.append('Orientation could not be determined; original orientation retained.')
        height,width=array.shape[:2]
        if rotation==90:
            array=cv2.rotate(array,cv2.ROTATE_90_CLOCKWISE)
            transform=np.array([[0,-1,height],[1,0,0],[0,0,1]],float)
        elif rotation==180:
            array=cv2.rotate(array,cv2.ROTATE_180)
            transform=np.array([[-1,0,width],[0,-1,height],[0,0,1]],float)
        elif rotation==270:
            array=cv2.rotate(array,cv2.ROTATE_90_COUNTERCLOCKWISE)
            transform=np.array([[0,1,0],[-1,0,width],[0,0,1]],float)
    if deskew:
        gray=cv2.cvtColor(array,cv2.COLOR_RGB2GRAY)
        edges=cv2.Canny(gray,50,150)
        lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=40,
            minLineLength=max(30,array.shape[1]//8),maxLineGap=20)
        angles=[]
        if lines is not None:
            for x1,y1,x2,y2 in lines[:,0]:
                angle=math.degrees(math.atan2(y2-y1,x2-x1))
                if abs(angle)<=15: angles.append(angle)
        if len(angles)>=3:
            skew=float(np.median(angles))
            if abs(skew)>=0.3:
                height,width=array.shape[:2]
                matrix=cv2.getRotationMatrix2D((width/2,height/2),skew,1)
                corners=np.array([[0,0,1],[width,0,1],[width,height,1],[0,height,1]],float).T
                transformed=matrix@corners
                minimum=transformed.min(axis=1);maximum=transformed.max(axis=1)
                matrix[:,2]-=minimum
                array=cv2.warpAffine(array,matrix,tuple(np.ceil(maximum-minimum).astype(int)),
                                     flags=cv2.INTER_CUBIC,borderValue=(255,255,255))
                transform=np.vstack([matrix,[0,0,1]])@transform
            else: skew=0.0
    return Image.fromarray(array),transform,{'rotation':rotation,'deskew_degrees':skew,'notes':notes}


def _mapped_bbox(box, inverse):
    x,y,w,h=box
    corners=np.array([[x,y,1],[x+w,y,1],[x+w,y+h,1],[x,y+h,1]],float).T
    points=inverse@corners
    return [float(points[0].min()),float(points[1].min()),float(points[0].max()),float(points[1].max())]


def analyze_pdf(input_file, directory, lang='eng', dpi=400, preprocess=True,
                auto_rotate=True, deskew=True, confidence_threshold=65,
                progress_callback=None,status_callback=None,layout='auto',adaptive=True):
    EngineRegistry.configure()
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    pages=[]
    from services.validation_service import file_hash
    signature = hashlib.sha256(json.dumps([file_hash(input_file),lang,dpi,preprocess,auto_rotate,deskew,confidence_threshold,layout,adaptive,'v040']).encode()).hexdigest()
    with fitz.open(input_file) as document:
        if document.needs_pass:raise ValueError('Unlock the PDF before OCR.')
        for index,page in enumerate(document):
            page_checkpoint=directory/f"page-{index+1}.json"
            try:cached=json.loads(page_checkpoint.read_text())
            except (OSError,ValueError):cached=None
            if cached and cached.get("signature")==signature and Path(cached["record"]["image"]).is_file() and (
                not cached["record"].get("font_template") or Path(cached["record"]["font_template"]).is_file()):
                pages.append(cached["record"])
                if progress_callback:progress_callback(int((index+1)/len(document)*100))
                continue
            if status_callback:status_callback(f'Recognizing page {index+1}/{len(document)}')
            rotation=page.rotation;page.set_rotation(0)
            try:
                pix=page.get_pixmap(dpi=dpi,colorspace=fitz.csRGB,alpha=False)
                image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                sx,sy=pix.width/page.rect.width,pix.height/page.rect.height
                # OCR only the non-text regions, including mixed text/scan pages.
                draw=ImageDraw.Draw(image)
                for word in page.get_text('words'):
                    draw.rectangle((max(0,int(word[0]*sx)-2),max(0,int(word[1]*sy)-2),
                                    min(pix.width,int(word[2]*sx)+2),min(pix.height,int(word[3]*sy)+2)),fill='white')
            finally:page.set_rotation(rotation)
            corrected,transform,corrections=correct_scan(image,auto_rotate,deskew)
            if preprocess:
                from services.ocr_service import OCRService
                corrected=OCRService._preprocess(corrected)
            preview=directory/f'page-{index+1}.png'
            with atomic_output(preview) as temporary:corrected.save(temporary)
            from services.ocr_recognition import recognize
            data,recognition=recognize(corrected,lang,dpi,layout=layout,adaptive=adaptive,
                                       threshold=confidence_threshold,status_callback=status_callback)
            words=[];inverse=np.linalg.inv(transform)
            for number,text in enumerate(data['text']):
                text=text.strip()
                if not text:continue
                confidence=float(data['conf'][number])
                box=[int(data[key][number]) for key in ('left','top','width','height')]
                words.append({'text':text,'original_text':text,'confidence':confidence,
                    'uncertain':confidence<confidence_threshold,'bbox':box,
                    'source_bbox':_mapped_bbox(box,inverse),
                    'line':[int(data[key][number]) for key in ('block_num','par_num','line_num')]})
            template=None
            if words:
                template=directory/f'font-{index+1}.pdf'
                pdf=pytesseract.image_to_pdf_or_hocr(corrected,lang=lang,extension='pdf',
                    config=f'--dpi {dpi} -c textonly_pdf=1',timeout=120)
                with atomic_output(template) as temporary:temporary.write_bytes(pdf)
            pages.append({'page':index,'words':words,'image':str(preview),'pixel_size':[pix.width,pix.height],
                          'font_template':str(template) if template else None,'corrections':corrections,'recognition':recognition})
            write_json(page_checkpoint,{'signature':signature,'record':pages[-1]})
            del image,corrected,pix
            fitz.TOOLS.store_shrink(100)
            if progress_callback:progress_callback(int((index+1)/len(document)*100))
    result={'version':1,'source':str(Path(input_file).resolve()),'language':lang,'dpi':dpi,
            'approved':False,'pages':pages,'uncertain_words':sum(word['uncertain'] for p in pages for word in p['words'])}
    write_json(directory/'review.json',result)
    return result


def reviewed_text(review):
    pages=[]
    for page in review['pages']:
        lines=[];previous=None
        for word in page['words']:
            line=tuple(word['line'])
            if line!=previous:lines.append([]);previous=line
            lines[-1].append(word['text'])
        pages.append('\n'.join(' '.join(line) for line in lines))
    return pages


def apply_review(input_file, output_file, review):
    """Use Tesseract's Unicode glyphless font for corrected invisible OCR text."""
    reader=PdfReader(input_file);writer=PdfWriter(clone_from=reader)
    for record in review['pages']:
        if not record['words']:continue
        template=PdfReader(record['font_template'])
        font=next(iter(template.pages[0]['/Resources']['/Font'].values()))
        page=writer.pages[record['page']]
        width,height=float(page.cropbox.width),float(page.cropbox.height)
        left,top=float(page.cropbox.left),float(page.cropbox.top)
        sx,sy=width/record['pixel_size'][0],height/record['pixel_size'][1]
        layer_writer=PdfWriter();layer=layer_writer.add_blank_page(width=float(page.mediabox.width),height=float(page.mediabox.height))
        copied_font=font.get_object().clone(layer_writer)
        layer[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/OCR'):copied_font.indirect_reference})})
        commands=[]
        for word in record['words']:
            text=word['text']
            if not text:continue
            x0,y0,x1,y1=word['source_bbox']
            x0,x1=max(0,x0),min(record['pixel_size'][0],x1)
            y0,y1=max(0,y0),min(record['pixel_size'][1],y1)
            h=max(1,(y1-y0)*sy);w=max(1,(x1-x0)*sx)
            encoded=(text+' ').encode('utf-16-be').hex()
            units=len((text+' ').encode('utf-16-be'))//2
            commands.append(f'BT /OCR {h:.6f} Tf 3 Tr {100*w/max(0.5*units*h,0.001):.6f} Tz '
                f'1 0 0 1 {left+x0*sx:.6f} {top-y1*sy:.6f} Tm <{encoded}> Tj ET')
        stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
        layer[NameObject('/Contents')]=layer_writer._add_object(stream)
        buffer=io.BytesIO();layer_writer.write(buffer);buffer.seek(0)
        page.merge_page(PdfReader(buffer).pages[0])
    with atomic_output(output_file) as temporary:
        writer.write(temporary)
    return str(output_file)
