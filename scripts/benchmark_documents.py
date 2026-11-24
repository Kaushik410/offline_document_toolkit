"""Synthetic, ground-truth quality benchmarks; one isolated process per measurement."""
import argparse
import csv
import json
import multiprocessing as mp
from pathlib import Path
import sys
import time
import unicodedata

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1):new.append(min(new[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]


def error_rates(reference,text):
    a=' '.join(unicodedata.normalize('NFC',reference).split())
    b=' '.join(unicodedata.normalize('NFC',text).split())
    return {'character_error_rate':distance(a,b)/max(1,len(a)),
            'word_error_rate':distance(a.split(),b.split())/max(1,len(a.split()))}


def generate_corpus(root,large_pages=50):
    import fitz
    from PIL import Image,ImageDraw,ImageFont
    root.mkdir(parents=True,exist_ok=True)
    text='DOCUMENT TOOLKIT QUALITY TEST\nSynthetic records remain private and readable.\nAll pages must survive every export.'
    try:font=ImageFont.truetype('DejaVuSans.ttf',34)
    except OSError:font=ImageFont.load_default(size=34)
    image=Image.new('RGB',(1100,400),'white');ImageDraw.Draw(image).multiline_text((35,50),text,font=font,fill='black',spacing=20)
    cases=[]
    for name,angle in [('scan',0),('skewed',6),('rotated',90)]:
        scan=image.rotate(angle,expand=True,fillcolor='white')
        path=root/(name+'.pdf')
        with fitz.open() as pdf:
            page=pdf.new_page(width=scan.width*72/150,height=scan.height*72/150)
            import io
            buffer=io.BytesIO();scan.save(buffer,format='PNG');page.insert_image(page.rect,stream=buffer.getvalue());pdf.save(path)
        cases.append({'name':name,'path':str(path),'kind':'ocr','reference':text,'language':'eng'})
    path=root/'mixed.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();page.insert_text((30,35),'Existing header')
        import io
        buffer=io.BytesIO();image.save(buffer,format='PNG');page.insert_image(fitz.Rect(30,70,565,270),stream=buffer.getvalue())
        pdf.save(path)
    cases.append({'name':'mixed','path':str(path),'kind':'ocr','reference':'Existing header\n'+text,'language':'eng'})
    hindi_font=Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf')
    hindi_text='यह एक उदाहरण दस्तावेज है\nसभी पृष्ठ सुरक्षित रहने चाहिए'
    if hindi_font.exists():
        image_hi=Image.new('RGB',(1000,300),'white')
        ImageDraw.Draw(image_hi).multiline_text((30,35),hindi_text,font=ImageFont.truetype(str(hindi_font),44),fill='black',spacing=25)
        path=root/'hindi.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page(width=500,height=150);buffer=io.BytesIO();image_hi.save(buffer,format='PNG')
            page.insert_image(page.rect,stream=buffer.getvalue());pdf.save(path)
        cases.append({'name':'hindi','path':str(path),'kind':'ocr','reference':hindi_text,'language':'hin'})
    else:cases.append({'name':'hindi','kind':'unavailable','reason':'Install Noto Sans Devanagari to render the synthetic Hindi fixture.'})
    path=root/'forms-tables.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();page.insert_text((30,40),'Synthetic form and table')
        widget=fitz.Widget();widget.field_name='example';widget.field_value='Example';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect=fitz.Rect(30,70,230,100);page.add_widget(widget)
        for x in (30,200,400):page.draw_line((x,140),(x,260))
        for y in (140,180,220,260):page.draw_line((30,y),(400,y))
        page.insert_text((40,165),'Synthetic table')
        pdf.set_metadata({'title':'Synthetic benchmark'});pdf.set_toc([[1,'Example',1]])
        pdf.embfile_add('example.txt',b'Synthetic attachment');pdf.save(path)
    cases.append({'name':'forms-tables','path':str(path),'kind':'preserve'})
    path=root/'large.pdf'
    with fitz.open() as pdf:
        for index in range(large_pages):pdf.new_page().insert_text((30,40),f'Synthetic large document page {index+1}')
        pdf.save(path)
    cases.append({'name':'large','path':str(path),'kind':'preserve'})
    # A many-page text PDF is small in bytes. Exercise a separate, image-heavy
    # packet as well, with deterministic sensor noise and unique page images.
    import numpy as np
    generator=np.random.default_rng(2026)
    path=root/'large-scans.pdf'
    with fitz.open() as pdf:
        for index in range(large_pages):
            pixels=np.clip(generator.normal(225,35,(2200,1700)),0,255).astype('uint8')
            scan=Image.fromarray(pixels)
            ImageDraw.Draw(scan).multiline_text((80,80),f'Synthetic scanned packet page {index+1}\n'+text,
                                                font=font,fill='black',spacing=35)
            buffer=io.BytesIO();scan.save(buffer,format='JPEG',quality=90)
            page=pdf.new_page(width=612,height=792);page.insert_image(page.rect,stream=buffer.getvalue())
        pdf.save(path)
    cases.append({'name':'large-scans','path':str(path),'kind':'preserve'})
    (root/'corpus.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
    return cases


def peak_memory():
    try:
        import resource
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform=='darwin' else value*1024)
    except ImportError:
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
                ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
        data=Counters();data.cb=ctypes.sizeof(data)
        ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        handle=ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(data),data.cb)
        return data.PeakWorkingSetSize


def run_case(case,directory,connection,backend='native',max_cer=.12,max_wer=.35):
    started=time.perf_counter();result={'name':case['name'],'backend':backend}
    try:
        import fitz
        from services.validation_service import ValidationService
        from services.export_service import ExportService
        from utils.engine_registry import EngineRegistry
        work=Path(directory);work.mkdir(parents=True,exist_ok=True)
        if case['kind']=='unavailable':result.update(status='skipped',reason=case['reason'])
        else:
            baseline=ValidationService.inspect_pdf(case['path']);output=work/'output.pdf'
            if case['kind']=='ocr':
                if not EngineRegistry.find('tesseract'):raise RuntimeError('Tesseract is not installed')
                if backend=='ocrmypdf':
                    if not EngineRegistry.find('ocrmypdf'):
                        result.update(status='skipped',reason='Optional OCRmyPDF backend is not installed')
                        connection.send(result);return
                    from services.ocrmypdf_backend import convert
                    convert(case['path'],output,case['language'])
                else:
                    from services.ocr_pipeline import analyze_pdf,apply_review
                    review=analyze_pdf(case['path'],work/'ocr',lang=case['language'],dpi=400,preprocess=False)
                    apply_review(case['path'],output,review)
                with fitz.open(output) as pdf:text='\n'.join(page.get_text() for page in pdf)
                result.update(error_rates(case['reference'],text))
            else:ExportService.pdf(case['path'],output)
            report=ValidationService.validate_pdf(output,expected_pages=baseline['pages'],baseline=baseline)
            with fitz.open(case['path']) as original,fitz.open(output) as exported:
                result['visual_preservation']=True
                for a,b in zip(original,exported):
                    before=a.get_pixmap(matrix=fitz.Matrix(.4,.4)).samples
                    after=b.get_pixmap(matrix=fitz.Matrix(.4,.4)).samples
                    result['visual_preservation'] &= before==after
                    del before,after
                    fitz.TOOLS.store_shrink(100)
            result.update(status='passed' if report['passed'] and result.get('character_error_rate',0)<=max_cer and result.get('word_error_rate',0)<=max_wer and result['visual_preservation'] else 'failed',
                          validation=report['checks'],input_bytes=baseline['bytes'],output_bytes=output.stat().st_size,pages=baseline['pages'])
    except Exception as error:result.update(status='failed',error=str(error))
    result.update(seconds=round(time.perf_counter()-started,4),peak_worker_rss_bytes=peak_memory())
    if case['name']=='large-scans' and result.get('status')=='passed':
        result['memory_budget_bytes']=256*1024**2
        if result['peak_worker_rss_bytes']>result['memory_budget_bytes']:
            result.update(status='failed',error='Scan-packet worker exceeded the 256 MiB memory budget')
    connection.send(result);connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/benchmarks'))
    parser.add_argument('--large-pages',type=int,default=50)
    parser.add_argument('--compare-ocrmypdf',action='store_true')
    parser.add_argument('--max-cer',type=float,default=.12)
    parser.add_argument('--max-wer',type=float,default=.35)
    parser.add_argument('--strict',action='store_true',help='Exit nonzero if any case fails')
    args=parser.parse_args()
    if not 0<=args.max_cer<=1 or not 0<=args.max_wer<=1:parser.error('Error-rate limits must be from zero to one')
    if args.large_pages<1:parser.error('--large-pages must be positive')
    results=[]
    context=mp.get_context('spawn')
    # Keep fixture-generation allocations outside the measurement parent.
    # On Linux, a spawned child's RSS high-water mark can include the parent's
    # resident pages before exec, which otherwise inflates small measurements.
    generator=context.Process(target=generate_corpus,args=(args.output/'corpus',args.large_pages))
    generator.start();generator.join(300)
    if generator.is_alive():generator.kill();generator.join();raise SystemExit('Corpus generation timed out')
    if generator.exitcode:raise SystemExit('Corpus generation failed')
    cases=json.loads((args.output/'corpus/corpus.json').read_text(encoding='utf-8'))
    for case in cases:
        backends=['native','ocrmypdf'] if args.compare_ocrmypdf and case['kind']=='ocr' else ['native']
        for backend in backends:
            receiver,sender=context.Pipe(False)
            process=context.Process(target=run_case,args=(case,str(args.output/(case['name']+'-'+backend)),sender,backend,args.max_cer,args.max_wer));process.start();sender.close()
            if receiver.poll(300):
                try:result=receiver.recv()
                except EOFError:result={'name':case['name'],'backend':backend,'status':'failed','error':'Worker exited unexpectedly'}
            else:
                process.terminate();result={'name':case['name'],'backend':backend,'status':'failed','error':'Timed out'}
            process.join(5)
            if process.is_alive():process.kill();process.join()
            receiver.close();results.append(result);print(case['name'],backend,result['status'],flush=True)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    keys=['name','backend','status','seconds','peak_worker_rss_bytes','pages','input_bytes','output_bytes','character_error_rate','word_error_rate','visual_preservation']
    with open(args.output/'report.csv','w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(results)
    if args.strict and any(result['status']=='failed' for result in results):raise SystemExit(1)


if __name__=='__main__':main()
