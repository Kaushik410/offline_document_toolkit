from pathlib import Path
import pytest
from PIL import Image
from docx import Document
from docx.shared import Pt
from services.image_service import ImageService
from services.ocr_service import OCRService
from services.batch_service import BatchService
from services.word_service import WordService
from utils.output_utils import atomic_output


def test_ocr_preserves_existing_enhanced_sibling(image, monkeypatch):
    sibling = image.with_name('sample_enhanced.png')
    sibling.write_bytes(b'important existing file')
    original = image.read_bytes()
    monkeypatch.setattr('pytesseract.image_to_string', lambda *a, **kw: 'recognized')
    assert OCRService.image_to_text(image) == 'recognized'
    assert sibling.read_bytes() == b'important existing file'
    assert image.read_bytes() == original
    assert sorted(p.name for p in image.parent.iterdir()) == ['sample.png', 'sample_enhanced.png']


def test_ocr_failure_does_not_touch_source_directory(image, monkeypatch):
    before = set(image.parent.iterdir())
    def fail(*args, **kwargs):
        raise RuntimeError('engine failed')
    monkeypatch.setattr('pytesseract.image_to_string', fail)
    with pytest.raises(RuntimeError):
        OCRService.image_to_text(image)
    assert set(image.parent.iterdir()) == before


def test_preprocessing_uses_unique_temporaries(image):
    outputs = [Path(OCRService.preprocess_image_for_ocr(image)) for _ in range(2)]
    try:
        assert outputs[0] != outputs[1]
        assert all(p.is_file() for p in outputs)
        assert not image.with_name('sample_enhanced.png').exists()
    finally:
        for path in outputs:
            path.unlink(missing_ok=True)


def test_batch_compression_reports_sizes_and_continues_after_failure(image, tmp_path):
    results, errors = BatchService.batch_compress_images([tmp_path/'missing.png', image], tmp_path/'batch')
    assert len(results) == len(errors) == 1
    assert results[0]['original_size'] == image.stat().st_size
    assert results[0]['new_size'] == Path(results[0]['output']).stat().st_size


def test_batch_preserves_existing_files_and_same_stem_inputs(image, tmp_path):
    other = tmp_path/'other';other.mkdir()
    second = other/image.name;second.write_bytes(image.read_bytes())
    folder = tmp_path/'batch';folder.mkdir()
    existing = folder/'sample_compressed.png';existing.write_bytes(b'existing')
    results, errors = BatchService.batch_compress_images([image,second],folder)
    assert not errors
    assert len({r['output'] for r in results}) == 2
    assert existing.read_bytes() == b'existing'


def test_image_quality_and_preview_use_identical_encoder(image, tmp_path):
    source = Image.effect_noise((300, 300), 80).convert('RGB')
    path = tmp_path/'noise.jpg';source.save(path,quality=95)
    for suffix in ['.jpg','.png','.webp']:
        typed = path.with_suffix(suffix)
        source.save(typed)
        for quality in [10,95]:
            preview, estimated = ImageService.preview_image(typed,'compress',{'quality':quality})
            output = tmp_path/f'out-{quality}{suffix}'
            ImageService.save_image(preview,output,quality)
            assert output.stat().st_size == estimated
    low = ImageService.encode_image(source,'.jpg',10)
    high = ImageService.encode_image(source,'.jpg',95)
    assert len(low) < len(high)


def test_convert_format_enforces_selected_format(image,tmp_path):
    output = ImageService.convert_format(image,tmp_path/'wrong.png','jpg')
    assert Path(output).suffix == '.jpg'
    with Image.open(output) as converted:
        assert converted.format == 'JPEG'


def test_docx_replacement_across_runs_preserves_formatting_and_surrounding_text(tmp_path):
    source = tmp_path/'runs.docx';document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run('prefix Hel').bold = True
    paragraph.add_run('lo and Hel').italic = True
    paragraph.add_run('lo suffix').font.size = Pt(16)
    table = document.add_table(1,1)
    table.cell(0,0).paragraphs[0].add_run('Hel')
    table.cell(0,0).paragraphs[0].add_run('lo')
    header=document.sections[0].header.paragraphs[0]
    header.add_run('Hel');header.add_run('lo')
    document.save(source)
    output = WordService.find_replace_docx(source,tmp_path/'out.docx','Hello','Hi')
    result = Document(output)
    assert result.paragraphs[0].text == 'prefix Hi and Hi suffix'
    assert result.paragraphs[0].runs[0].bold
    assert result.paragraphs[0].runs[1].italic
    assert result.paragraphs[0].runs[2].font.size == Pt(16)
    assert result.tables[0].cell(0,0).text == 'Hi'
    assert result.sections[0].header.paragraphs[0].text == 'Hi'


@pytest.mark.parametrize('replacement',['','longer replacement','नमस्ते'])
def test_multiple_replacements_in_one_run(tmp_path,replacement):
    source=tmp_path/'in.docx';document=Document();document.add_paragraph('HelloHello Hello')
    document.save(source)
    output=WordService.find_replace_docx(source,tmp_path/'out.docx','Hello',replacement)
    assert Document(output).paragraphs[0].text == replacement*2+' '+replacement


def test_failed_output_preserves_destination(tmp_path):
    output=tmp_path/'important.txt';output.write_text('original')
    with pytest.raises(RuntimeError):
        with atomic_output(output) as temporary:
            temporary.write_text('incomplete')
            raise RuntimeError('failure')
    assert output.read_text() == 'original'
    assert not list(tmp_path.glob('.odt-*'))
