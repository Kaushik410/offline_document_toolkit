"""Physical PDF redaction and explicit export privacy policies."""
from pathlib import Path
import fitz
from utils.output_utils import atomic_output

DEFAULT_PRIVACY = {'remove_metadata': False, 'remove_comments': False, 'remove_attachments': False}


def validate_privacy(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_PRIVACY):
        raise ValueError('Invalid privacy options.')
    result = dict(DEFAULT_PRIVACY, **value)
    if any(not isinstance(flag, bool) for flag in result.values()):
        raise ValueError('Privacy options must be enabled or disabled.')
    return result


def apply_redactions(page, rectangles):
    for box in rectangles:
        rectangle = fitz.Rect(box)
        if rectangle.is_empty or rectangle.is_infinite:
            raise ValueError('Select a non-empty redaction area.')
        # Widget values and comments are independent of page painting content.
        for widget in list(page.widgets() or []):
            if widget.rect.intersects(rectangle):
                page.delete_widget(widget)
        for annotation in list(page.annots() or []):
            if annotation.rect.intersects(rectangle):
                page.delete_annot(annotation)
        page.add_redact_annot(rectangle, fill=(0, 0, 0))
    if rectangles:
        page.apply_redactions(images=2, graphics=2, text=0)


def selection_to_redaction(document, page_id, selection):
    reference = next(page for page in document['pages'] if page['id'] == page_id)
    if reference['edits']:
        raise ValueError('Apply redaction before image effects. Undo the image effects first.')
    asset = document['assets'][reference['asset']]
    with fitz.open(asset['pdf']) as pdf:
        page = pdf[reference['page']]
        original_crop = page.cropbox
        if reference.get('crop'):
            x0, y0, x1, y1 = reference['crop']
            page.set_cropbox(fitz.Rect(original_crop.x0+x0*original_crop.width, original_crop.y0+y0*original_crop.height,
                                      original_crop.x0+x1*original_crop.width, original_crop.y0+y1*original_crop.height))
        page.set_rotation((page.rotation + reference['rotation']) % 360)
        visible = page.rect
        box = fitz.Rect(selection[0]*visible.width, selection[1]*visible.height,
                        selection[2]*visible.width, selection[3]*visible.height)
        box = box * page.derotation_matrix
        offset = page.cropbox.top_left - original_crop.top_left
        box += (offset.x, offset.y, offset.x, offset.y)
        return list(box)


def sanitize_document(document, options):
    options = validate_privacy(options)
    if options['remove_metadata']:
        document.set_metadata({})
        document.del_xml_metadata()
    if options['remove_attachments']:
        for name in document.embfile_names():
            document.embfile_del(name)
        for page in document:
            for annotation in list(page.annots() or []):
                if annotation.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT:
                    page.delete_annot(annotation)
    if options['remove_comments']:
        for page in document:
            for annotation in list(page.annots() or []):
                page.delete_annot(annotation)


def sanitize_pdf(input_file, output_file, options):
    with fitz.open(input_file) as document:
        sanitize_document(document, options)
        with atomic_output(output_file) as temporary:
            document.save(temporary, garbage=4, deflate=True)
    return str(output_file)


def privacy_checks(path, options):
    options = validate_privacy(options)
    checks = []
    with fitz.open(path) as document:
        if options['remove_metadata']:
            clean = not any(value for key,value in document.metadata.items() if key not in ('format','encryption')) and not document.get_xml_metadata()
            checks.append({'name': 'Metadata removed', 'passed': clean, 'detail': 'Standard and XML metadata checked'})
        if options['remove_attachments']:
            count = document.embfile_count() + sum(annotation.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT
                for page in document for annotation in page.annots() or [])
            checks.append({'name': 'Attachments removed', 'passed': count == 0, 'detail': f'{count} attachments remain'})
        if options['remove_comments']:
            count = sum(1 for page in document for _ in page.annots() or [])
            checks.append({'name': 'Comments removed', 'passed': count == 0, 'detail': f'{count} annotations remain'})
    return checks
