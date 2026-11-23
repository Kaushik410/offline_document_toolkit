"""Saved, validated recipes and a checkpointed submission pipeline."""
from pathlib import Path
import copy
import hashlib
import io
import json
import re
import shutil

import fitz
from PIL import Image

from services.export_service import ExportService
from services.image_service import ImageService
from services.ocr_pipeline import analyze_pdf, apply_review, reviewed_text, write_json
from services.validation_service import ValidationService, file_hash
from services.workspace_service import assemble_workspace, render_workspace_page
from utils.output_utils import atomic_output


STAGES=['clean','ocr','compress','merge','rename','export']
DEFAULT_RECIPE={'version':1,'steps':['ocr','compress','merge','rename','export'],
    'output_name':'submission','format':'pdf','max_bytes':500*1024,'max_pages':0,
    'width':0,'height':0,'min_quality':45,'min_dpi':150,'language':'eng',
    'auto_rotate':True,'deskew':True,'confidence_threshold':65,
    'review_ocr':True,'review_before_export':True,'ocr_dpi':400,'ocr_layout':'auto','adaptive_ocr':True,
    'privacy':{'remove_metadata':False,'remove_comments':False,'remove_attachments':False}}


def validate_recipe(recipe):
    result=copy.deepcopy(DEFAULT_RECIPE);result.update(copy.deepcopy(recipe))
    if result.get('version')!=1:raise ValueError('Unsupported workflow version.')
    steps=result['steps']
    if not isinstance(steps,list) or not steps or steps[-1]!='export' or len(set(steps))!=len(steps):
        raise ValueError('A workflow must end with Export and contain each stage at most once.')
    if any(step not in STAGES for step in steps) or steps!=sorted(steps,key=STAGES.index):
        raise ValueError('Use the stage order: clean, OCR, compress, merge, rename, export.')
    if result['format'] not in ('pdf','png','jpg'):raise ValueError('Choose PDF, PNG, or JPG export.')
    for key,minimum,maximum in [('max_bytes',0,2**40),('max_pages',0,100000),('width',0,20000),('height',0,20000),
                               ('min_quality',10,95),('ocr_dpi',150,600),('min_dpi',72,600),('confidence_threshold',0,100)]:
        value=result[key]
        if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:
            raise ValueError(f'Invalid {key}: use {minimum} to {maximum}.')
    if result['format']=='pdf' and (result['width'] or result['height']):
        raise ValueError('Pixel dimensions apply to image exports. Set them to zero for PDF.')
    if not re.fullmatch(r'[\w .-]{1,80}',result['output_name'],re.UNICODE) or result['output_name'].strip() in ('.','..',''):
        raise ValueError('Use a short output name without path separators.')
    if not re.fullmatch(r'[a-z_]+(?:\+[a-z_]+)*',result['language']):raise ValueError('Invalid OCR language.')
    for key in ('auto_rotate','deskew','review_ocr','review_before_export','adaptive_ocr'):
        if not isinstance(result[key],bool):raise ValueError(f'{key} must be enabled or disabled.')
    from services.privacy_service import validate_privacy
    result['privacy']=validate_privacy(result['privacy'])
    if result['ocr_layout'] not in ('auto','block','columns','sparse'):raise ValueError('Invalid OCR layout.')
    return result


def clean_pdf(input_file,output_file):
    """Clean embedded scan images while retaining PDF text, forms and catalog data."""
    from services.ocr_service import OCRService
    with fitz.open(input_file) as document:
        seen=set()
        for page in document:
            for item in page.get_images(full=True):
                xref,mask=item[:2]
                if xref in seen or mask:continue
                seen.add(xref)
                with Image.open(io.BytesIO(document.extract_image(xref)['image'])) as image:
                    cleaned=OCRService._preprocess(image)
                    page.replace_image(xref,stream=ImageService.encode_image(cleaned,'.png'))
        with atomic_output(output_file) as temporary:document.save(temporary,garbage=4,deflate=True)
    return str(output_file)


def execute_workflow(spec,job_directory,progress_callback=None,status_callback=None):
    recipe=validate_recipe(spec['recipe']);document=spec['document']
    from services.submission_service import inspect_packet
    packet=inspect_packet(document)
    if not packet['passed']:
        raise ValueError('Submission checklist is incomplete: '+', '.join(row['name'] for row in packet['checks'] if not row['passed']))
    work=Path(job_directory);work.mkdir(parents=True,exist_ok=True)
    signature=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    for orphan in work.rglob('.odt-*'):
        if orphan.is_file():orphan.unlink(missing_ok=True)
    checkpoint_file=work/'checkpoint.json'
    try:checkpoint=json.loads(checkpoint_file.read_text())
    except (OSError,ValueError):checkpoint={}
    if checkpoint.get('signature')!=signature:checkpoint={'signature':signature,'completed':{}}
    completed=checkpoint['completed']; reused=[]
    def save():write_json(checkpoint_file,checkpoint)
    def stage(name,path,operation):
        entry=completed.get(name)
        if entry and Path(entry['path']).is_file() and file_hash(entry['path'])==entry['hash']:
            reused.append(name);return Path(entry['path'])
        if status_callback:status_callback(f'Preparing {name}')
        operation(path)
        completed[name]={'path':str(path),'hash':file_hash(path)};save()
        return path
    assembled=stage('assemble',work/'assembled.pdf',lambda path:assemble_workspace(document,path))
    current=assembled
    if any(recipe['privacy'].values()):
        from services.privacy_service import sanitize_pdf
        current=stage('privacy',work/'private.pdf',lambda path:sanitize_pdf(current,path,recipe['privacy']))
    baseline=ValidationService.inspect_pdf(current)
    if progress_callback:progress_callback(15)
    if 'clean' in recipe['steps']:
        current=stage('clean',work/'cleaned.pdf',lambda path:clean_pdf(current,path))
    review_file=None;review=None
    if 'ocr' in recipe['steps']:
        review_directory=work/'ocr'
        review_file=review_directory/'review.json'
        expected_hash=file_hash(current)
        try:review=json.loads(review_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):review=None
        if not review or review.get('input_hash')!=expected_hash:
            review=analyze_pdf(current,review_directory,lang=recipe['language'],dpi=recipe['ocr_dpi'],
                preprocess='clean' in recipe['steps'],auto_rotate=recipe['auto_rotate'],deskew=recipe['deskew'],
                confidence_threshold=recipe['confidence_threshold'],status_callback=status_callback,
                layout=recipe['ocr_layout'],adaptive=recipe['adaptive_ocr'])
            review['input_hash']=expected_hash;write_json(review_file,review)
        ocr_output=work/'searchable.pdf'
        apply_review(current,ocr_output,review)
        current=ocr_output
        if any(recipe['privacy'].values()):
            from services.privacy_service import sanitize_pdf
            sanitize_pdf(current,work/'private-searchable.pdf',recipe['privacy'])
            current=work/'private-searchable.pdf'
    if progress_callback:progress_callback(55)
    # Final PDF content is validated against the assembled packet, not against a degraded candidate.
    name=recipe['output_name'].strip().rstrip('.') if 'rename' in recipe['steps'] else 'document'
    cache=checkpoint.get('export_cache',{})
    input_hash=file_hash(current)
    if cache.get('input_hash')==input_hash and all(Path(row['path']).is_file() and file_hash(row['path'])==row['hash'] for row in cache.get('files',[])) and cache.get('files'):
        reports=copy.deepcopy(cache['reports']);staged=[Path(row['path']) for row in cache['files']]
        reused.append('export')
    else:
        reports=[];staged=[]
        name=recipe['output_name'].strip().rstrip('.') if 'rename' in recipe['steps'] else 'document'
        if recipe['format']=='pdf' and 'merge' in recipe['steps']:
            output=work/(name+'.pdf')
            if 'compress' in recipe['steps']:
                optimized=ExportService.pdf(current,output,max_bytes=recipe['max_bytes'],min_quality=recipe['min_quality'],
                    min_dpi=recipe['min_dpi'],status_callback=status_callback)
            else:
                with atomic_output(output) as temporary:shutil.copyfile(current,temporary)
                optimized={'quality':None,'dpi':None,'reason':''}
            report=ValidationService.validate_pdf(output,expected_pages=len(document['pages']),baseline=baseline,
                                                  max_bytes=recipe['max_bytes'],max_pages=recipe['max_pages'])
            reports.append({**report,'quality':optimized['quality'],'dpi':optimized['dpi'],'reason':optimized['reason']})
            staged.append(output)
        else:
            with fitz.open(current) as pdf:
                for index,page in enumerate(pdf):
                    output=work/f'{name}-{index+1:03d}.{recipe["format"]}'
                    if recipe['format']=='pdf':
                        # Keep full structures for each single-page export by selecting in a full copy.
                        raw=work/f'page-{index+1:03d}-raw.pdf'
                        with fitz.open(current) as single:
                            single.select([index])
                            with atomic_output(raw) as temporary:single.save(temporary,garbage=4,deflate=True)
                        before=ValidationService.inspect_pdf(raw)
                        if 'compress' in recipe['steps']:
                            optimized=ExportService.pdf(raw,output,max_bytes=recipe['max_bytes'],
                                min_quality=recipe['min_quality'],min_dpi=recipe['min_dpi'],status_callback=status_callback)
                        else:
                            with atomic_output(output) as temporary:shutil.copyfile(raw,temporary)
                            optimized={'quality':None,'dpi':None,'reason':''}
                        report=ValidationService.validate_pdf(output,expected_pages=1,baseline=before,max_bytes=recipe['max_bytes'])
                        report.update(quality=optimized['quality'],dpi=optimized['dpi'],reason=optimized['reason'])
                    else:
                        pix=page.get_pixmap(dpi=recipe['min_dpi'],colorspace=fitz.csRGB,alpha=False)
                        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                        optimized=ExportService.image(image,output,width=recipe['width'],height=recipe['height'],
                            max_bytes=recipe['max_bytes'],min_quality=recipe['min_quality'])
                        report=dict(optimized['validation'],reason=optimized['reason'],dpi=recipe['min_dpi'],
                                    quality=optimized['quality'] if recipe['format']=='jpg' else None)
                    reports.append(report);staged.append(output)
        checkpoint['export_cache']={'input_hash':input_hash,'reports':reports,
            'files':[{'path':str(path),'hash':file_hash(path)} for path in staged]}
        save()
    if recipe['max_pages'] and len(document['pages'])>recipe['max_pages']:
        reports[0]['passed']=False
        reports[0]['checks'].append({'name':'Packet page limit','passed':False,
            'detail':f"{len(document['pages'])} pages exceeds {recipe['max_pages']}; remove pages in the workspace."})
    if recipe['format']=='pdf' and any(recipe['privacy'].values()):
        from services.privacy_service import privacy_checks
        for path,report in zip(staged,reports):
            checks=privacy_checks(path,recipe['privacy'])
            names={row['name'] for row in checks}
            report['checks']=[row for row in report['checks'] if row['name'] not in names]+checks
            report['passed'] &= all(row['passed'] for row in checks)
    checks_pass=all(report['passed'] for report in reports)
    uncertain=bool(review and review['uncertain_words'] and recipe['review_ocr'] and not review.get('approved'))
    approved=not recipe['review_before_export'] or checkpoint.get('export_approved',False)
    result={'state':'needs_review','outputs':[],'staged':[str(path) for path in staged],
            'reports':reports,'review_file':str(review_file) if review_file else None,
            'reused_stages':reused,'ready_to_export':checks_pass and not uncertain,
            'message':'Review the staged packet and approve export.'}
    if not checks_pass:result['message']='Export requirements were not met. Inspect validation results and adjust the workflow.'
    elif uncertain:result['message']='OCR contains uncertain words. Review them before exporting.'
    elif approved:
        destination=Path(spec['output_directory']).expanduser().resolve()/(name+'-'+work.name[:8])
        destination.mkdir(parents=True,exist_ok=True)
        outputs=[]
        for path in staged:
            final=destination/path.name
            if final.exists() and file_hash(final)!=file_hash(path):
                raise FileExistsError(f'An existing export changed outside the app: {final}')
            if not final.exists():
                with atomic_output(final) as temporary:shutil.copyfile(path,temporary)
            outputs.append(str(final))
        if review:
            text='\n\n'.join(reviewed_text(review))
            with atomic_output(destination/'reviewed-text.txt') as temporary:temporary.write_text(text,encoding='utf-8')
        result.update(state='succeeded',outputs=outputs,message='Validated export completed.')
        if spec.get('database_path') and recipe['format']=='pdf':
            from services.library_service import index_documents
            result['library'] = index_documents(outputs,spec['database_path'])
        public=copy.deepcopy(result)
        public.pop('staged',None);public.pop('review_file',None)
        public['outputs']=[Path(path).name for path in outputs]
        public.pop('library',None)
        write_json(destination/'export-report.json',public)
    save();write_json(work/'result.json',result)
    if progress_callback:progress_callback(100)
    return result


def approve_export(job_directory):
    path=Path(job_directory)/'checkpoint.json'
    checkpoint=json.loads(path.read_text());checkpoint['export_approved']=True
    write_json(path,checkpoint)
