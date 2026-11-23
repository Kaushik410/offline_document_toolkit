"""Inspect actual exported content before publishing a successful result."""
from pathlib import Path
from collections import Counter
import hashlib
import fitz
from PIL import Image


def file_hash(path):
    digest=hashlib.sha256()
    with open(path,'rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


class ValidationService:
    @staticmethod
    def inspect_pdf(path):
        path=Path(path)
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError('Unlock encrypted PDFs before preparing a submission.')
            text=[];fields=[];readable=[];geometry=[]
            for page in document:
                text.append(page.get_text())
                fields.extend({'name':widget.field_name,'value':widget.field_value or ''} for widget in page.widgets() or [])
                pix=page.get_pixmap(matrix=fitz.Matrix(0.2,0.2),alpha=False)
                readable.append(pix.width>0 and pix.height>0)
                del pix
                fitz.TOOLS.store_shrink(100)
                geometry.append({'media': [round(value,3) for value in page.mediabox],
                                 'crop': [round(value,3) for value in page.cropbox], 'rotation':page.rotation})
            attachments={name:hashlib.sha256(document.embfile_get(name)).hexdigest() for name in document.embfile_names()}
            return {'pages':len(document),'bytes':path.stat().st_size,'text':text,'fields':fields,
                    'attachments':attachments,'renderable':all(readable),'geometry':geometry,
                    'title':document.metadata.get('title','')}

    @staticmethod
    def validate_pdf(path, expected_pages=None, baseline=None, max_bytes=0, max_pages=0):
        actual=ValidationService.inspect_pdf(path)
        checks=[]
        def add(name,passed,detail):checks.append({'name':name,'passed':bool(passed),'detail':detail})
        add('PDF opens and renders', actual['renderable'] and actual['pages']>0, f"{actual['pages']} pages rendered successfully")
        if expected_pages is not None:add('Page count',actual['pages']==expected_pages,f"Expected {expected_pages}; found {actual['pages']}")
        if max_pages:add('Page limit',actual['pages']<=max_pages,f"Limit {max_pages}; found {actual['pages']}")
        if max_bytes:add('File size',actual['bytes']<=max_bytes,f"Limit {max_bytes} bytes; found {actual['bytes']}")
        if baseline:
            before=sorted((str(field['name']),str(field['value'])) for field in baseline.get('fields',[]))
            after=sorted((str(field['name']),str(field['value'])) for field in actual['fields'])
            add('Form fields',before==after,f'{len(before)} expected; {len(after)} preserved')
            before_attachments=baseline.get('attachments',{})
            add('Attachments',all(actual['attachments'].get(name)==digest for name,digest in before_attachments.items()),
                f"{len(before_attachments)} expected; {len(actual['attachments'])} found")
            # Required selectable text must survive compression and OCR.
            missing=Counter()
            for index,text in enumerate(baseline.get('text',[])):
                output_text=actual['text'][index] if index<len(actual['text']) else ''
                missing.update(Counter(text.split())-Counter(output_text.split()))
            add('Selectable text',not missing,f'{sum(missing.values())} required text tokens missing')
            if 'geometry' in baseline:
                add('Page geometry',baseline['geometry']==actual['geometry'],'Page boxes and rotations must be preserved')
        return {'passed':all(check['passed'] for check in checks),'checks':checks,
                'summary':f"{actual['pages']} pages • {actual['bytes']/1024:.1f} KB",'actual':actual}

    @staticmethod
    def validate_image(path, width=0, height=0, max_bytes=0):
        with Image.open(path) as image:
            image.load();size=image.size
        checks=[{'name':'Readable image','passed':True,'detail':f'{size[0]} × {size[1]} pixels'}]
        for name,target,actual in [('Width',width,size[0]),('Height',height,size[1]),('File size',max_bytes,Path(path).stat().st_size)]:
            if target:
                passed=actual<=target if name=='File size' else actual==target
                checks.append({'name':name,'passed':passed,'detail':f'Required {target}; found {actual}'})
        return {'passed':all(row['passed'] for row in checks),'checks':checks,
                'summary':f'{size[0]} × {size[1]} • {Path(path).stat().st_size/1024:.1f} KB'}
