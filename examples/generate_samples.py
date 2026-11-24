"""Generate synthetic documents for demonstrations without personal information."""
import argparse
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont
from docx import Document


def generate(output):
    output.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1200,400),'white')
    font=ImageFont.load_default(size=48)
    ImageDraw.Draw(image).text((60,120),'SYNTHETIC DOCUMENT TOOLKIT DEMO',font=font,fill='black')
    image.save(output/'synthetic-scan.png')
    with fitz.open() as pdf:
        for index in range(3):
            page=pdf.new_page()
            page.insert_text((60,80),f'Synthetic document - page {index+1}',fontsize=20)
        pdf.save(output/'synthetic-pages.pdf')
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_image(fitz.Rect(30,100,565,280),filename=str(output/'synthetic-scan.png'))
        pdf.save(output/'synthetic-scan.pdf')
    word=Document();word.add_heading('Synthetic Example',0)
    paragraph=word.add_paragraph();paragraph.add_run('Hel').bold=True;paragraph.add_run('lo world')
    table=word.add_table(2,2);table.cell(0,0).text='Item';table.cell(0,1).text='Quantity'
    table.cell(1,0).text='Example';table.cell(1,1).text='3'
    word.save(output/'synthetic-example.docx')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('local_data/synthetic_examples'))
    args=parser.parse_args();generate(args.output)
    print('Synthetic examples created.')
