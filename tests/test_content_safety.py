"""Regression coverage for silent overwrites, dropped content, and invisible PDF edits."""
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from docx import Document
from docx.oxml import OxmlElement
from PIL import Image, TiffImagePlugin
from pypdf import PdfReader
from PySide6.QtWidgets import QMessageBox

from services.image_service import ImageService
from services.pdf_service import PDFService
from services.word_service import WordService
from tests.conftest import wait_until
from utils.app_config import AppConfig


@pytest.fixture
def multipage_tiff(tmp_path):
    frames = []
    for size, color, dpi in [((80,100), 'red', 300), ((120,90), 'blue', 150)]:
        frame = Image.new('RGB', size, color)
        frame.tag_v2 = TiffImagePlugin.ImageFileDirectory_v2()
        frame.tag_v2[282] = dpi
        frame.tag_v2[283] = dpi
        frame.tag_v2[296] = 2
        frames.append(frame)
    path = tmp_path / 'two-pages.tiff'
    frames[0].save(path, save_all=True, append_images=frames[1:])
    return path


@pytest.mark.parametrize('operation', ['compress', 'convert'])
def test_tiff_retains_all_pages_pixels_and_resolution(multipage_tiff, tmp_path, operation):
    if operation == 'compress':
        output, original_size, new_size = ImageService.compress_image(multipage_tiff, tmp_path/'output.tiff')
        assert original_size == multipage_tiff.stat().st_size
        assert new_size == Path(output).stat().st_size
    else:
        output = ImageService.convert_format(multipage_tiff, tmp_path/'output.tiff', 'tiff')
    with Image.open(multipage_tiff) as original, Image.open(output) as result:
        assert original.n_frames == result.n_frames == 2
        for index in range(2):
            original.seek(index); result.seek(index)
            assert original.size == result.size
            assert original.tobytes() == result.tobytes()
            assert original.info['dpi'] == result.info['dpi']


def test_multiframe_single_page_conversion_cannot_drop_pages(multipage_tiff, tmp_path):
    output = tmp_path/'output.png'; output.write_bytes(b'existing')
    with pytest.raises(ValueError, match='multiple pages'):
        ImageService.convert_format(multipage_tiff, output, 'png')
    assert output.read_bytes() == b'existing'
    with pytest.raises(ValueError, match='multi-page TIFF'):
        ImageService.load_image(multipage_tiff)


def test_conversion_rejects_overwrite_of_a_different_normalized_path(image, tmp_path):
    output = tmp_path/'important.jpg'; output.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        ImageService.convert_format(image, tmp_path/'important.png', 'jpg')
    assert output.read_bytes() == b'existing'


@pytest.mark.parametrize('answer', [QMessageBox.No, QMessageBox.Yes])
def test_gui_confirms_the_actual_normalized_filename(qapp, image, tmp_path, monkeypatch, answer):
    from ui.image_editor_dialog import ImageEditorDialog
    monkeypatch.setattr(AppConfig, 'CONFIG_FILE', tmp_path/'settings.json')
    monkeypatch.setattr(AppConfig, 'DEFAULT_CONFIG', {'default_output_folder': str(tmp_path)})
    dialog = ImageEditorDialog(str(image), 'convert_format')
    wait_until(qapp, lambda: dialog._task_controller.worker is None)
    dialog.widgets['output_format'].setCurrentText('jpg')
    chosen = tmp_path/'important.png'; chosen.write_bytes(b'chosen file')
    actual = tmp_path/'important.jpg'; actual.write_bytes(b'actual existing file')
    with patch('ui.image_editor_dialog.QFileDialog.getSaveFileName', return_value=(str(chosen), '')), \
         patch('ui.image_editor_dialog.QMessageBox.question', return_value=answer) as question, \
         patch('ui.image_editor_dialog.QMessageBox.information'):
        dialog.save_output()
        wait_until(qapp, lambda: dialog._task_controller.worker is None)
    question.assert_called_once()
    assert str(actual) in question.call_args.args[2]
    assert chosen.read_bytes() == b'chosen file'
    if answer == QMessageBox.No:
        assert actual.read_bytes() == b'actual existing file'
    else:
        with Image.open(actual) as result:
            assert result.format == 'JPEG'
    dialog.close()


def test_gui_compresses_every_tiff_page(qapp, multipage_tiff, tmp_path, monkeypatch):
    from ui.image_editor_dialog import ImageEditorDialog
    monkeypatch.setattr(AppConfig, 'CONFIG_FILE', tmp_path/'settings.json')
    monkeypatch.setattr(AppConfig, 'DEFAULT_CONFIG', {'default_output_folder': str(tmp_path)})
    dialog = ImageEditorDialog(str(multipage_tiff), 'compress')
    wait_until(qapp, lambda: dialog._task_controller.worker is None)
    assert '2 pages' in dialog.info_label.text()
    output = tmp_path/'compressed.tiff'
    with patch('ui.image_editor_dialog.QFileDialog.getSaveFileName', return_value=(str(output), '')), \
         patch('ui.image_editor_dialog.QMessageBox.information'):
        dialog.save_output()
        wait_until(qapp, lambda: dialog._task_controller.worker is None)
    with Image.open(output) as result:
        assert result.n_frames == 2
    assert f'{output.stat().st_size / 1024:.2f} KB' in dialog.widgets['estimated_size'].text()
    dialog.close()


def test_gui_preserves_previous_blur_and_undo(qapp, tmp_path):
    from ui.image_editor_dialog import ImageEditorDialog
    original = Image.effect_noise((300,200), 80).convert('RGB')
    source = tmp_path/'noise.png'; original.save(source)
    dialog = ImageEditorDialog(str(source), 'blur')
    wait_until(qapp, lambda: dialog._task_controller.worker is None)
    first_area, second_area = (0,0,100,200), (200,0,300,200)
    dialog.preview_canvas.selection_rect_original = first_area
    dialog.update_preview(); wait_until(qapp, lambda: dialog._task_controller.worker is None)
    first_blur = dialog.preview_image.crop(first_area).tobytes()
    assert first_blur != original.crop(first_area).tobytes()
    dialog.preview_canvas.selection_rect_original = second_area
    dialog.update_preview(); wait_until(qapp, lambda: dialog._task_controller.worker is None)
    assert dialog.preview_image.crop(first_area).tobytes() == first_blur
    assert dialog.preview_image.crop(second_area).tobytes() != original.crop(second_area).tobytes()
    dialog.undo_preview()
    assert dialog.preview_image.tobytes() == original.tobytes()
    dialog.close()


def test_gui_second_crop_uses_current_preview_coordinates(qapp, tmp_path):
    from ui.image_editor_dialog import ImageEditorDialog
    original = Image.effect_noise((300,200), 80).convert('RGB')
    source = tmp_path/'noise.png'; original.save(source)
    dialog = ImageEditorDialog(str(source), 'crop')
    wait_until(qapp, lambda: dialog._task_controller.worker is None)
    for area in [(100,0,300,200), (0,0,50,50)]:
        dialog.preview_canvas.selection_rect_original = area
        dialog.update_preview(); wait_until(qapp, lambda: dialog._task_controller.worker is None)
    assert dialog.preview_image.size == (50,50)
    assert dialog.preview_image.tobytes() == original.crop((100,0,150,50)).tobytes()
    dialog.close()


def test_replacement_keeps_drawings_fields_and_run_styles(image, tmp_path):
    source = tmp_path/'source.docx'
    document = Document()
    run = document.add_paragraph().add_run('Hello '); run.bold = True
    run.add_picture(str(image)); run.add_text('Hello')
    begin = OxmlElement('w:fldChar'); begin.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType','begin')
    run._r.append(begin)
    instruction = OxmlElement('w:instrText'); instruction.text = ' PAGE '
    run._r.append(instruction)
    end = OxmlElement('w:fldChar'); end.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType','end')
    run._r.append(end)
    document.save(source)
    output = WordService.find_replace_docx(source, tmp_path/'result.docx', 'Hello', 'Hi')
    result = Document(output)
    assert len(result.inline_shapes) == 1
    assert result.paragraphs[0].text == 'Hi Hi'
    assert result.paragraphs[0].runs[0].bold
    assert len(result.element.xpath('.//w:fldChar')) == 2
    assert result.element.xpath('.//w:instrText')[0].text == ' PAGE '


def test_replacement_does_not_span_a_drawing(image, tmp_path):
    source = tmp_path/'source.docx'; document = Document()
    run = document.add_paragraph().add_run('Hel'); run.add_picture(str(image)); run.add_text('lo')
    document.save(source)
    result = Document(WordService.find_replace_docx(source, tmp_path/'out.docx', 'Hello', 'Hi'))
    assert result.paragraphs[0].text == 'Hello'
    assert len(result.inline_shapes) == 1


def test_replacement_handles_tabs_and_newlines_without_removing_pictures(image, tmp_path):
    source = tmp_path/'source.docx'; document = Document()
    run = document.add_paragraph().add_run('Hello'); run.add_picture(str(image))
    document.save(source)
    result = Document(WordService.find_replace_docx(source, tmp_path/'out.docx', 'Hello', 'one\ttwo\nthree'))
    assert result.paragraphs[0].text == 'one\ttwo\nthree'
    assert len(result.inline_shapes) == 1
    assert len(result.element.xpath('.//w:tab')) == len(result.element.xpath('.//w:br')) == 1


def test_protect_and_unlock_keep_complete_pdf_structure(tmp_path):
    source = tmp_path/'source.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((30,40), 'Synthetic PDF')
        widget = fitz.Widget(); widget.field_name = 'sample_name'
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT; widget.field_value = 'Example'
        widget.rect = fitz.Rect(30,60,250,90); page.add_widget(widget)
        page.add_text_annot((30,110), 'Synthetic note')
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(30,130,200,150), 'uri':'https://example.invalid'})
        document.set_metadata({'title':'Synthetic title', 'author':'Synthetic author'})
        document.set_toc([[1, 'Synthetic bookmark', 1]])
        document.embfile_add('synthetic.txt', b'Synthetic attachment')
        document.save(source)
    protected = PDFService.protect_pdf(source, tmp_path/'protected.pdf', 'test-password')
    unlocked = PDFService.unlock_pdf(protected, tmp_path/'unlocked.pdf', 'test-password')
    for output in [protected, unlocked]:
        reader = PdfReader(output)
        if reader.is_encrypted:
            assert reader.decrypt('test-password')
        assert reader.get_fields()['sample_name']['/V'] == 'Example'
        assert reader.metadata.title == 'Synthetic title'
        assert reader.metadata.author == 'Synthetic author'
        with fitz.open(output) as document:
            if document.needs_pass:
                document.authenticate('test-password')
            assert document.get_toc() == [[1, 'Synthetic bookmark', 1]]
            assert document.embfile_get('synthetic.txt') == b'Synthetic attachment'
            assert len(list(document[0].annots())) == len(document[0].get_links()) == 1


@pytest.mark.parametrize('style', ['horizontal','diagonal'])
@pytest.mark.parametrize('rotation', [0,90,180,270])
def test_watermark_visible_above_full_page_scan(tmp_path, style, rotation):
    image = tmp_path/'scan.png'; Image.new('RGB',(600,300),'white').save(image)
    source = tmp_path/'scan.pdf'
    with fitz.open() as document:
        page = document.new_page(width=600,height=300)
        page.insert_image(page.rect,filename=str(image)); page.set_cropbox(fitz.Rect(10,10,590,290))
        page.set_rotation(rotation); document.save(source)
    output = PDFService.add_watermark(source, tmp_path/'marked.pdf', 'CONFIDENTIAL', style)
    with fitz.open(source) as original, fitz.open(output) as result:
        assert original[0].get_pixmap().samples != result[0].get_pixmap().samples
        assert original[0].rotation == result[0].rotation
        assert original[0].cropbox == result[0].cropbox


@pytest.mark.parametrize('position', ['bottom-left','bottom-center','bottom-right'])
@pytest.mark.parametrize('rotation', [0,90,180,270])
def test_page_numbers_visible_at_requested_position(tmp_path, position, rotation):
    source = tmp_path/'rotated.pdf'
    with fitz.open() as document:
        page = document.new_page(width=600,height=300)
        page.insert_text((30,60),'Synthetic page')
        page.set_cropbox(fitz.Rect(10,10,590,290)); page.set_rotation(rotation)
        document.save(source)
    output = PDFService.add_page_numbers(source, tmp_path/'numbered.pdf', position)
    with fitz.open(source) as original, fitz.open(output) as result:
        page = result[0]
        assert original[0].get_pixmap().samples != page.get_pixmap().samples
        word = next(word for word in page.get_text('words') if word[4] == '1')
        visible = fitz.Rect(word[:4]) * page.rotation_matrix
        assert page.rect.height - 40 <= visible.y0 < visible.y1 <= page.rect.height
        if position == 'bottom-center':
            assert abs((visible.x0 + visible.x1) / 2 - page.rect.width / 2) < 1
        elif position == 'bottom-left':
            assert 0 < visible.x0 < page.rect.width / 3
        else:
            assert page.rect.width * 2 / 3 < visible.x1 < page.rect.width


@pytest.mark.parametrize('mode', ['RGBA','LA','P'])
def test_transparent_images_have_white_pdf_background(tmp_path, mode):
    if mode == 'RGBA':
        image = Image.new(mode,(60,60),(0,0,0,0))
    elif mode == 'LA':
        image = Image.new(mode,(60,60),(0,0))
    else:
        image = Image.new(mode,(60,60),0)
        image.putpalette([0,0,0]*256); image.info['transparency'] = 0
    source = tmp_path/'transparent.png'; image.save(source)
    output = PDFService.images_to_pdf([source],tmp_path/'result.pdf')
    with fitz.open(output) as result:
        assert result[0].get_pixmap().pixel(20,20) == (255,255,255)


def test_pdf_conversion_keeps_every_tiff_page(multipage_tiff, tmp_path):
    output = PDFService.images_to_pdf([multipage_tiff], tmp_path/'pages.pdf')
    with fitz.open(output) as result:
        assert len(result) == 2


def test_cmyk_jpeg_converts_to_png_and_loads_for_preview(tmp_path):
    source = tmp_path/'cmyk.jpg'; Image.new('CMYK',(60,40),(0,200,100,0)).save(source)
    output = ImageService.convert_format(source,tmp_path/'converted.png','png')
    with Image.open(source) as original, Image.open(output) as result:
        assert result.mode == 'RGB'
        assert result.tobytes() == original.convert('RGB').tobytes()
    assert ImageService.load_image(source).mode == 'RGB'


@pytest.mark.parametrize('suffix', ['.pdf', '.docx', '.txt'])
def test_shared_save_normalizer_confirms_real_output(qapp, tmp_path, suffix):
    from utils.file_dialog_utils import normalize_output_selection
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    selected = tmp_path/'important.other'
    actual = selected.with_suffix(suffix); actual.write_bytes(b'original')
    with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.No):
        assert normalize_output_selection(parent, str(selected), suffix) == ''
    assert actual.read_bytes() == b'original'
    with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.Yes):
        assert normalize_output_selection(parent, str(selected), suffix) == str(actual)
    parent.close()


def test_ocr_save_cannot_overwrite_a_different_unconfirmed_file(qapp, tmp_path, monkeypatch):
    from ui.ocr_tools_page import OCRResultDialog
    monkeypatch.setattr(AppConfig, 'CONFIG_FILE', tmp_path/'settings.json')
    monkeypatch.setattr(AppConfig, 'DEFAULT_CONFIG', {'default_output_folder': str(tmp_path)})
    actual = tmp_path/'important.docx'; actual.write_bytes(b'original')
    dialog = OCRResultDialog('Synthetic text')
    with patch('ui.ocr_tools_page.QFileDialog.getSaveFileName', return_value=(str(tmp_path/'important.txt'), '')), \
         patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.No), \
         patch('ui.ocr_tools_page.run_task') as run:
        dialog.save_as_docx()
    run.assert_not_called()
    assert actual.read_bytes() == b'original'
    dialog.close()
