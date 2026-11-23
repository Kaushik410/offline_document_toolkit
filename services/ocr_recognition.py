"""Bounded OCR retries selected by confidence and retained text coverage."""
import math
from collections import defaultdict
import numpy as np
import cv2
import pytesseract
from PIL import Image,ImageOps,ImageFilter

LAYOUTS={'auto':3,'block':6,'columns':4,'sparse':11}
KEYS=('text','conf','left','top','width','height','block_num','par_num','line_num')


def word_rows(data,offset=(0,0),line=None):
    rows=[]
    for index,text in enumerate(data['text']):
        if not text.strip():continue
        row={key:data[key][index] for key in KEYS}
        row['text']=text.strip();row['conf']=float(row['conf'])
        for key in ('left','top','width','height','block_num','par_num','line_num'):row[key]=int(row[key])
        row['left']+=offset[0];row['top']+=offset[1]
        if line:
            row.update(zip(('block_num','par_num','line_num'),line))
        rows.append(row)
    return rows


def confidence(rows):
    weight=sum(len(row['text']) for row in rows)
    return sum(max(0,row['conf'])*len(row['text']) for row in rows)/max(1,weight)


def choose(candidates):
    longest=max((sum(len(row['text']) for row in rows) for rows,_ in candidates),default=1)
    def score(candidate):
        rows,_=candidate
        coverage=sum(len(row['text']) for row in rows)/max(1,longest)
        return confidence(rows)+8*coverage-40*max(0,.7-coverage)
    return max(candidates,key=score)


def recognize(image,lang,dpi,layout='auto',adaptive=True,threshold=65,status_callback=None):
    if layout not in LAYOUTS:raise ValueError('Choose auto, block, columns, or sparse OCR layout.')
    def run(candidate,psm,extra='',offset=(0,0),line=None,resolution=None):
        data=pytesseract.image_to_data(candidate,lang=lang,output_type=pytesseract.Output.DICT,
            config=f'--dpi {resolution or dpi} --psm {psm} {extra}',timeout=120)
        return word_rows(data,offset,line)
    base=run(image,LAYOUTS[layout]);attempts=[{'method':'original','confidence':confidence(base)}]
    selected=base
    uncertain=lambda rows:any(row['conf']<min(threshold,80) for row in rows)
    if adaptive and (not base or uncertain(base)):
        if status_callback:status_callback('Comparing OCR preprocessing and page layout')
        gray=ImageOps.autocontrast(image.convert('L'))
        sharpened=gray.filter(ImageFilter.UnsharpMask(radius=1,percent=125,threshold=3))
        choices=[(base,'original')]
        settings=[(sharpened,LAYOUTS[layout],'sharpened',''),
                  (gray,6 if layout=='auto' else LAYOUTS[layout],'adaptive threshold','-c thresholding_method=2')]
        if layout=='auto':settings.append((gray,11,'sparse text',''))
        for variant,psm,label,extra in settings:
            rows=run(variant,psm,extra)
            choices.append((rows,label));attempts.append({'method':label,'confidence':confidence(rows)})
        if dpi<400 and confidence(base)<85:
            scale=400/dpi
            enlarged=image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS)
            rows=run(enlarged,LAYOUTS[layout],resolution=400)
            for row in rows:
                for key in ('left','top','width','height'):row[key]=round(row[key]/scale)
            choices.append((rows,'higher recognition resolution'))
            attempts.append({'method':'higher recognition resolution','confidence':confidence(rows)})
        selected,method=choose(choices)
        # Retry complete uncertain lines with single-line segmentation. Retain
        # each candidate's word boxes, rebased to the original recognition image.
        groups=defaultdict(list)
        for row in selected:groups[tuple(row[key] for key in ('block_num','par_num','line_num'))].append(row)
        revised=[];retried=0
        line_bounds={line:(min(row['top'] for row in rows),max(row['top']+row['height'] for row in rows)) for line,rows in groups.items()}
        for line,rows in groups.items():
            if uncertain(rows) and retried<10:
                margin=max(5,round(max(row['height'] for row in rows)*.35))
                x0=max(0,min(row['left'] for row in rows)-margin)
                y0=max(0,min(row['top'] for row in rows)-margin)
                x1=min(image.width,max(row['left']+row['width'] for row in rows)+margin)
                y1=min(image.height,max(row['top']+row['height'] for row in rows)+margin)
                top,bottom=line_bounds[line]
                preceding=[bound[1] for key,bound in line_bounds.items() if key!=line and bound[1]<=top]
                following=[bound[0] for key,bound in line_bounds.items() if key!=line and bound[0]>=bottom]
                if preceding:y0=max(y0,(max(preceding)+top)//2)
                if following:y1=min(y1,(min(following)+bottom)//2)
                crop=image.crop((x0,y0,x1,y1))
                alternatives=[(rows,'existing line')]
                for variant,label in [(crop,'line'),(ImageOps.autocontrast(crop.convert('L')),'line threshold')]:
                    extra='-c thresholding_method=2' if label=='line threshold' else ''
                    candidate=run(variant,7,extra,(x0,y0),line)
                    # A crop can expose a fragment from an adjacent line.
                    # Reject retries that invent or omit whole words.
                    if len(candidate)==len(rows):alternatives.append((candidate,label))
                rows,_=choose(alternatives);retried+=1
            revised.extend(rows)
        selected=revised
        attempts.append({'method':f'{retried} uncertain line retries','confidence':confidence(selected)})
    else:method='original'
    data={key:[row[key] for row in selected] for key in KEYS}
    return data,{'method':method,'attempts':attempts,'confidence':confidence(selected)}
