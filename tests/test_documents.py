import io
from pathlib import Path
import shutil
import zipfile

import fitz
import pytest
from docx import Document
from pypdf import PdfReader
from services.pdf_service import PDFService
from services.ocr_service import OCRService
from services.word_service import WordService


def test_core_pdf_operations(pdf,tmp_path):
    assert len(PdfReader(PDFService.merge_pdfs([pdf,pdf],tmp_path/'merged.pdf')).pages)==6
    assert len(PDFService.split_pdf(pdf,tmp_path/'split'))==3
    assert len(PdfReader(PDFService.extract_pages(pdf,'1,3',tmp_path/'extracted.pdf')).pages)==2
    assert len(PdfReader(PDFService.delete_pages(pdf,'2',tmp_path/'deleted.pdf')).pages)==2
    assert PdfReader(PDFService.rotate_pages(pdf,'2',90,tmp_path/'rotated.pdf')).pages[1].rotation==90
    protected=PDFService.protect_pdf(pdf,tmp_path/'protected.pdf','test-password')
    assert PdfReader(protected).is_encrypted
    assert not PdfReader(PDFService.unlock_pdf(protected,tmp_path/'unlocked.pdf','test-password')).is_encrypted
    assert len(PdfReader(PDFService.save_organized_pdf(pdf,tmp_path/'organized.pdf',[2,0],{2:90})).pages)==2


def test_appearance_docx_preserves_page_sizes_and_page_images(pdf,tmp_path):
    output=WordService.pdf_to_docx(pdf,tmp_path/'appearance.docx')
    document=Document(output)
    assert len(document.sections)==3
    assert all(abs(s.page_width.pt-400)<0.1 and abs(s.page_height.pt-500)<0.1 for s in document.sections)
    with zipfile.ZipFile(output) as archive:
        assert len([name for name in archive.namelist() if name.startswith('word/media/')])==3
        xml=archive.read('word/document.xml')
        assert xml.count(b'<wp:anchor ')==3
    editable=WordService.pdf_to_docx(pdf,tmp_path/'editable.docx',mode='editable')
    assert 'DOCUMENT TOOLKIT TEST' in '\n'.join(p.text for p in Document(editable).paragraphs)


@pytest.mark.integration
@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_searchable_pdf_preserves_original_page_and_structure(image,tmp_path,rotation):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is not installed')
    source=tmp_path/'scan.pdf'
    with fitz.open() as document:
        page=document.new_page(width=500,height=600)
        page.insert_image(fitz.Rect(20,40,480,145),filename=str(image))
        page.add_text_annot((30,170),'Synthetic annotation')
        page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(20,180,150,200),'uri':'https://example.invalid'})
        page.set_rotation(rotation)
        page.set_cropbox(fitz.Rect(10,20,490,580))
        document.set_metadata({'title':'Synthetic metadata'})
        document.set_toc([[1,'Synthetic bookmark',1]])
        document.save(source)
    output=OCRService.pdf_to_searchable_pdf(source,tmp_path/'searchable.pdf',dpi=150,preprocess=False)
    with fitz.open(source) as original, fitz.open(output) as searchable:
        a,b=original[0],searchable[0]
        assert a.rect == b.rect and a.mediabox == b.mediabox and a.cropbox == b.cropbox
        assert b.rotation==rotation
        assert a.get_pixmap().samples == b.get_pixmap().samples
        assert searchable.metadata['title']=='Synthetic metadata'
        assert original.get_toc()==searchable.get_toc()
        assert len(list(b.annots()))==1 and len(b.get_links())==1
        assert 'TOOLKIT' in b.get_text().upper()
        # OCR word rectangles must map back into the visible scan rectangle.
        words=[word for word in b.get_text('words') if 'TOOLKIT' in word[4].upper()]
        assert words
        assert 25 <= words[0][1] <= 145


@pytest.mark.integration
def test_real_image_ocr(image):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is not installed')
    assert 'TOOLKIT' in OCRService.image_to_text(image,preprocess=False)


@pytest.mark.integration
def test_real_pdf_compression(pdf,tmp_path):
    if not (shutil.which('gs') or shutil.which('gswin64c')):
        pytest.skip('Ghostscript is not installed')
    output,original,new=PDFService.compress_pdf(pdf,tmp_path/'compressed.pdf')
    assert original==pdf.stat().st_size and new==Path(output).stat().st_size
    assert len(PdfReader(output).pages)==3


@pytest.mark.integration
def test_real_docx_to_pdf(tmp_path):
    import os, socket
    from utils.engine_registry import EngineRegistry
    required=os.environ.get('ODT_REQUIRE_LIBREOFFICE')=='1'
    if not EngineRegistry.find('libreoffice'):
        if required:pytest.fail('LibreOffice is required by this release check but was not found')
        pytest.skip('LibreOffice is not installed')
    if os.name == 'posix':
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.bind(str(tmp_path/'ipc-probe'))
                probe.listen(1)
        except PermissionError:
            if required:pytest.fail('Required LibreOffice verification cannot run: local IPC is blocked')
            pytest.skip('This execution sandbox blocks the local IPC sockets required by LibreOffice')
        finally:
            (tmp_path/'ipc-probe').unlink(missing_ok=True)
    source=tmp_path/'synthetic.docx';document=Document();document.add_paragraph('SYNTHETIC TOOLKIT CHECK');document.save(source)
    output=WordService.docx_to_pdf(source,tmp_path/'output')
    with fitz.open(output) as pdf:
        assert len(pdf)==1
        assert 'SYNTHETIC TOOLKIT CHECK' in pdf[0].get_text()


@pytest.mark.integration
def test_searchable_blank_page_remains_blank(tmp_path):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is not installed')
    source=tmp_path/'blank.pdf'
    with fitz.open() as document:
        document.new_page(width=400,height=500)
        document.save(source)
    output=OCRService.pdf_to_searchable_pdf(source,tmp_path/'blank-searchable.pdf',dpi=100)
    with fitz.open(output) as result:
        assert len(result)==1 and not result[0].get_text().strip()


def test_editable_docx_reconstructs_styles_tables_and_images(image,tmp_path):
    source=tmp_path/'layout.pdf'
    with fitz.open() as document:
        page=document.new_page(width=400,height=500)
        page.insert_text((40,60),'Styled heading',fontname='hebo',fontsize=20,color=(1,0,0))
        page.insert_image(fitz.Rect(40,80,320,140),filename=str(image))
        for x in (40,180,320):page.draw_line((x,160),(x,240))
        for y in (160,200,240):page.draw_line((40,y),(320,y))
        for x,y,text in [(50,185,'Item'),(190,185,'Qty'),(50,225,'Sample'),(190,225,'3')]:
            page.insert_text((x,y),text)
        document.save(source)
    output=WordService.pdf_to_docx(source,tmp_path/'editable.docx',mode='editable')
    result=Document(output)
    heading=next(p for p in result.paragraphs if 'Styled heading' in p.text)
    assert heading.runs[0].bold and abs(heading.runs[0].font.size.pt-20)<0.1
    assert str(heading.runs[0].font.color.rgb)=='FF0000'
    assert len(result.tables)==1
    assert result.tables[0].cell(1,0).text=='Sample'
    assert len(result.inline_shapes)==1
    assert abs(result.sections[0].page_width.pt-400)<0.1
