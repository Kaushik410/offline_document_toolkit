from pathlib import Path
import json
import shutil
from unittest.mock import patch
import fitz
import numpy as np
import pytest
from PIL import Image,ImageDraw,ImageFont
from services.ocr_pipeline import correct_scan,analyze_pdf,apply_review,write_json
from services.workflow_service import execute_workflow,DEFAULT_RECIPE,approve_export
from services.workspace_service import import_documents
from services.workspace_model import WorkspaceModel
from tests.conftest import wait_until


def test_scan_deskew_estimates_a_known_angle():
    image=Image.new('RGB',(600,400),'white');draw=ImageDraw.Draw(image)
    for y in range(50,350,30):draw.line((40,y,560,y),fill='black',width=3)
    rotated=image.rotate(6,expand=True,fillcolor='white')
    corrected,matrix,report=correct_scan(rotated,auto_rotate=False,deskew=True)
    assert abs(abs(report['deskew_degrees'])-6)<1
    assert np.allclose(np.linalg.inv(matrix)@matrix,np.eye(3))


@pytest.mark.integration
def test_mixed_content_ocr_keeps_visible_pixels_and_existing_text(image,tmp_path):
    if not shutil.which('tesseract'):pytest.skip('Tesseract unavailable')
    source=tmp_path/'mixed.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=400);page.insert_text((25,35),'Existing header')
        page.insert_image(fitz.Rect(25,80,475,180),filename=str(image));pdf.save(source)
    review=analyze_pdf(source,tmp_path/'ocr',dpi=200,auto_rotate=False,deskew=False,preprocess=False)
    assert 'TOOLKIT' in ' '.join(word['text'] for word in review['pages'][0]['words'])
    output=apply_review(source,tmp_path/'searchable.pdf',review)
    with fitz.open(source) as before,fitz.open(output) as after:
        text=after[0].get_text()
        assert text.count('Existing header')==1 and 'TOOLKIT' in text
        assert before[0].get_pixmap().samples==after[0].get_pixmap().samples


@pytest.mark.integration
def test_ocr_checkpoints_skip_completed_pages_and_apply_unicode_corrections(image,tmp_path):
    if not shutil.which('tesseract'):pytest.skip('Tesseract unavailable')
    source=tmp_path/'scan.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=300);page.insert_image(fitz.Rect(20,40,480,150),filename=str(image));pdf.save(source)
    review=analyze_pdf(source,tmp_path/'ocr',dpi=150,auto_rotate=False,deskew=False,preprocess=False)
    assert review['pages'][0]['words']
    with patch('pytesseract.image_to_data',side_effect=AssertionError('Completed OCR page was rerun')):
        second=analyze_pdf(source,tmp_path/'ocr',dpi=150,auto_rotate=False,deskew=False,preprocess=False)
    second['pages'][0]['words'][0]['text']='सुरक्षित'
    output=apply_review(source,tmp_path/'corrected.pdf',second)
    with fitz.open(output) as pdf:assert 'सुरक्षित' in pdf[0].get_text()


@pytest.mark.integration
def test_ocr_review_ui_persists_edits_and_approval(qapp,image,tmp_path):
    if not shutil.which('tesseract'):pytest.skip('Tesseract unavailable')
    from ui.ocr_review_dialog import OCRReviewDialog
    source=tmp_path/'scan.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=300);page.insert_image(fitz.Rect(20,40,480,150),filename=str(image));pdf.save(source)
    review=analyze_pdf(source,tmp_path/'ocr',dpi=150,auto_rotate=False,deskew=False,preprocess=False)
    review['pages'][0]['words'][0]['uncertain']=True;write_json(tmp_path/'ocr/review.json',review)
    dialog=OCRReviewDialog(tmp_path/'ocr/review.json');dialog.words.item(0,0).setText('REVIEWED');dialog.approve()
    saved=json.loads((tmp_path/'ocr/review.json').read_text())
    assert saved['approved'] and saved['pages'][0]['words'][0]['text']=='REVIEWED'
    dialog.close()


def test_optional_ocrmypdf_backend_reports_missing_engine(tmp_path):
    from services.ocrmypdf_backend import convert
    with patch('services.ocrmypdf_backend.EngineRegistry.find',return_value=None):
        with pytest.raises(RuntimeError,match='not installed'):convert('input.pdf',tmp_path/'out.pdf')


def test_quality_metrics_use_unicode_and_word_ground_truth():
    from scripts.benchmark_documents import error_rates
    assert error_rates('नमस्ते दुनिया','नमस्ते दुनिया')['character_error_rate']==0
    result=error_rates('one two','one three')
    assert result['word_error_rate']==.5 and result['character_error_rate']>0


@pytest.mark.integration
def test_submission_ocr_review_exports_corrected_searchable_packet(image,tmp_path):
    from services.workspace_store import WorkspaceStore
    if not shutil.which('tesseract'):pytest.skip('Tesseract unavailable')
    source=tmp_path/'scan.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=300);page.insert_text((20,25),'Existing header')
        page.insert_image(fitz.Rect(20,40,480,150),filename=str(image));pdf.save(source)
    assets=import_documents([source],tmp_path/'imports');model=WorkspaceModel();model.import_assets(assets['assets'])
    store=WorkspaceStore(tmp_path/'state.sqlite')
    spec={'document':model.document,'recipe':dict(DEFAULT_RECIPE,steps=['ocr','merge','export'],max_bytes=0,
        auto_rotate=False,deskew=False,confidence_threshold=100),'output_directory':str(tmp_path/'exports'),'database_path':str(store.path)}
    result=execute_workflow(spec,tmp_path/'ocr-job')
    assert result['state']=='needs_review' and not result['ready_to_export']
    assert not (tmp_path/'exports').exists()
    review=json.loads(Path(result['review_file']).read_text())
    review['pages'][0]['words'][0]['text']='सुरक्षित';review['approved']=True
    write_json(result['review_file'],review);approve_export(tmp_path/'ocr-job')
    with patch('pytesseract.image_to_data',side_effect=AssertionError('OCR recognition was rerun')):
        result=execute_workflow(spec,tmp_path/'ocr-job')
    assert result['state']=='succeeded'
    with fitz.open(result['outputs'][0]) as output,fitz.open(source) as original:
        assert 'सुरक्षित' in output[0].get_text() and output[0].get_text().count('Existing header')==1
        assert output[0].get_pixmap().samples==original[0].get_pixmap().samples
    assert store.search('सुरक्षित')
