"""Search export quality within an explicit readability floor; never claim an unmet target."""
from pathlib import Path
import io
import shutil
import tempfile
import fitz
from PIL import Image, ImageOps

from services.image_service import ImageService
from services.validation_service import ValidationService
from utils.output_utils import atomic_output


class ExportService:
    @staticmethod
    def pdf(input_file, output_file, max_bytes=0, min_quality=45, min_dpi=150,
            progress_callback=None,status_callback=None):
        baseline=ValidationService.inspect_pdf(input_file)
        output=Path(output_file)
        candidates=[(None,None)]+[(quality,dpi) for dpi in sorted({max(200,min_dpi),min_dpi},reverse=True)
                                for quality in sorted({85,70,55,min_quality},reverse=True) if quality>=min_quality]
        best=None;best_size=None;attempts=[]
        with tempfile.TemporaryDirectory(prefix='odt-export-') as scratch:
            for index,(quality,dpi) in enumerate(candidates):
                if status_callback:status_callback('Checking lossless export' if quality is None else f'Trying quality {quality}, {dpi} DPI')
                with fitz.open(input_file) as document:
                    if quality is not None:
                        seen=set()
                        for page in document:
                            for image_info in page.get_images(full=True):
                                xref,mask=image_info[:2]
                                if xref in seen or mask:continue
                                seen.add(xref)
                                try:
                                    source=document.extract_image(xref)
                                    with Image.open(io.BytesIO(source['image'])) as image:
                                        if image.mode not in ('RGB','L','CMYK'):continue
                                        image=image.convert('RGB')
                                        rects=page.get_image_rects(xref)
                                        if not rects:continue
                                        width=max(rect.width for rect in rects)*dpi/72
                                        height=max(rect.height for rect in rects)*dpi/72
                                        image.thumbnail((max(1,round(width)),max(1,round(height))),Image.Resampling.LANCZOS)
                                        data=ImageService.encode_image(image,'.jpg',quality)
                                    if len(data)<len(source['image']):page.replace_image(xref,stream=data)
                                except (ValueError,OSError):continue
                    candidate=Path(scratch)/f'candidate-{index}.pdf'
                    with atomic_output(candidate) as temporary:document.save(temporary,garbage=4,deflate=True)
                report=ValidationService.validate_pdf(candidate,baseline=baseline,expected_pages=baseline['pages'])
                size=candidate.stat().st_size
                attempts.append({'quality':quality,'dpi':dpi,'bytes':size,'preserved':report['passed']})
                if report['passed'] and (best_size is None or size<best_size):
                    best_size=size;best=(candidate,quality,dpi)
                if report['passed'] and (not max_bytes or size<=max_bytes):
                    best=(candidate,quality,dpi);break
                if progress_callback:progress_callback(int((index+1)/len(candidates)*100))
            if best is None:raise ValueError('No export candidate preserved the required document content.')
            chosen,quality,dpi=best
            with atomic_output(output) as temporary:shutil.copyfile(chosen,temporary)
        report=ValidationService.validate_pdf(output,baseline=baseline,expected_pages=baseline['pages'],max_bytes=max_bytes)
        return {'path':str(output),'validation':report,'quality':quality,'dpi':dpi,'attempts':attempts,
                'reason':'' if report['passed'] else 'No tested export met the size target within the selected quality and resolution limits.'}

    @staticmethod
    def image(image,output_file,width=0,height=0,max_bytes=0,min_quality=45):
        if width and height:image=ImageOps.pad(image,(width,height),color='white')
        elif width:image=ImageOps.contain(image,(width,max(1,round(image.height*width/image.width))))
        elif height:image=ImageOps.contain(image,(max(1,round(image.width*height/image.height)),height))
        output=Path(output_file);best=None;quality=None
        for value in sorted({95,85,70,55,min_quality},reverse=True):
            if value<min_quality:continue
            data=ImageService.encode_image(image,output.suffix,value)
            if best is None or len(data)<len(best):best=data;quality=value
            if not max_bytes or len(data)<=max_bytes:best=data;quality=value;break
        with atomic_output(output) as temporary:temporary.write_bytes(best)
        report=ValidationService.validate_image(output,width,height,max_bytes)
        return {'path':str(output),'validation':report,'quality':quality,
                'reason':'' if report['passed'] else 'The target cannot be met at the selected dimensions and quality floor.'}
