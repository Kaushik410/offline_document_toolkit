"""Offline OCR with private temporary files and preservation of original PDF pages."""
from pathlib import Path
import tempfile

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image
from docx import Document

from services.image_service import ImageService
from utils.output_utils import atomic_output, distinct_output


class OCRService:
    SUPPORTED_IMAGES = ImageService.SUPPORTED_INPUTS
    _validate_image = staticmethod(ImageService._validate_image)

    @staticmethod
    def _validate_pdf(file_path):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f'PDF not found: {file_path}')
        if path.suffix.lower() != '.pdf':
            raise ValueError('Input file must be a PDF.')
        return path

    @staticmethod
    def _prepare_output_path(output_file, default_ext):
        path = Path(output_file)
        if path.suffix.lower() != default_ext:
            path = path.with_suffix(default_ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _preprocess(image):
        gray = cv2.cvtColor(np.array(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
        gray = cv2.fastNlMeansDenoising(gray, None, 15, 7, 21)
        return Image.fromarray(cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11))

    @staticmethod
    def preprocess_image_for_ocr(input_file, output_file=None):
        image = OCRService._preprocess(ImageService.load_image(input_file))
        if output_file is None:
            # Caller owns this unique temporary output; never touch a sibling of input.
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temporary:
                output_file = temporary.name
        output = OCRService._prepare_output_path(output_file, '.png')
        distinct_output(input_file, output)
        return ImageService.save_image(image, output)

    @staticmethod
    def image_to_text(input_file, lang='eng', preprocess=True):
        image = ImageService.load_image(input_file)
        if preprocess:
            image = OCRService._preprocess(image)
        return pytesseract.image_to_string(image, lang=lang, timeout=120).strip()

    @staticmethod
    def _page_image(page, dpi, preprocess, unrotate=False):
        if not 72 <= dpi <= 600:
            raise ValueError('Render DPI must be between 72 and 600.')
        rotation = page.rotation
        if unrotate:
            page.set_rotation(0)
        try:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        finally:
            if unrotate:
                page.set_rotation(rotation)
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        return OCRService._preprocess(image) if preprocess else image

    @staticmethod
    def pdf_to_text(input_file, lang='eng', dpi=200, preprocess=True,
                    progress_callback=None, status_callback=None):
        texts = OCRService.ocr_pages(input_file, lang=lang, dpi=dpi, preprocess=preprocess,
                                      progress_callback=progress_callback, status_callback=status_callback)
        return '\n\n'.join(f'--- Page {i + 1} ---\n{text}' for i, text in enumerate(texts))

    @staticmethod
    def ocr_pages(input_file, lang='eng', dpi=200, preprocess=True,
                  progress_callback=None, status_callback=None):
        with fitz.open(OCRService._validate_pdf(input_file)) as document:
            if document.needs_pass:
                raise ValueError('Unlock the PDF before running OCR.')
            texts = []
            for index, page in enumerate(document):
                if status_callback:
                    status_callback(f'Reading page {index + 1}/{len(document)}')
                image = OCRService._page_image(page, dpi, preprocess, unrotate=True)
                texts.append(pytesseract.image_to_string(image, lang=lang, timeout=120).strip())
                if progress_callback:
                    progress_callback(int((index + 1) / len(document) * 100))
            return texts

    @staticmethod
    def pdf_to_searchable_pdf(input_file, output_file, lang='eng', dpi=200, preprocess=True,
                               progress_callback=None, status_callback=None):
        path = OCRService._validate_pdf(input_file)
        output = OCRService._prepare_output_path(output_file, '.pdf')
        distinct_output(path, output)
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError('Unlock the PDF before running OCR.')
            for index, page in enumerate(document):
                if status_callback:
                    status_callback(f'Adding searchable text: page {index + 1}/{len(document)}')
                # Keep existing text intact and avoid overlapping duplicate OCR text.
                if not page.get_text().strip():
                    image = OCRService._page_image(page, dpi, preprocess, unrotate=True)
                    layer_bytes = pytesseract.image_to_pdf_or_hocr(
                        image, extension='pdf', lang=lang,
                        config=f'--dpi {dpi} -c textonly_pdf=1', timeout=120)
                    with fitz.open('pdf', layer_bytes) as layer:
                        if layer[0].get_text().strip():
                            rotation = page.rotation
                            page.set_rotation(0)
                            try:
                                page.show_pdf_page(page.rect, layer, 0, keep_proportion=False)
                            finally:
                                page.set_rotation(rotation)
                if progress_callback:
                    progress_callback(int((index + 1) / len(document) * 100))
            with atomic_output(output) as temporary:
                document.save(temporary, garbage=4, deflate=True)
        return str(output)

    @staticmethod
    def save_text_as_txt(text, output_file):
        if not text.strip():
            raise ValueError('No text to save.')
        output = OCRService._prepare_output_path(output_file, '.txt')
        with atomic_output(output) as temporary:
            temporary.write_text(text, encoding='utf-8')
        return str(output)

    @staticmethod
    def save_text_as_docx(text, output_file):
        if not text.strip():
            raise ValueError('No text to save.')
        output = OCRService._prepare_output_path(output_file, '.docx')
        document = Document()
        for line in text.split('\n'):
            document.add_paragraph(line)
        with atomic_output(output) as temporary:
            document.save(temporary)
        return str(output)

    @staticmethod
    def render_pdf_page_to_image(input_file, page_index, output_file=None, dpi=200):
        with fitz.open(OCRService._validate_pdf(input_file)) as document:
            if not 0 <= page_index < len(document):
                raise ValueError('Page index out of range.')
            if output_file is None:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temporary:
                    output_file = temporary.name
            image = OCRService._page_image(document[page_index], dpi, False)
            return ImageService.save_image(image, output_file)

    @staticmethod
    def render_page_bytes(input_file, page_index, dpi=120):
        with fitz.open(OCRService._validate_pdf(input_file)) as document:
            if not 0 <= page_index < len(document):
                raise ValueError('Page index out of range.')
            return document[page_index].get_pixmap(dpi=dpi, alpha=False).tobytes('png')

    @staticmethod
    def get_pdf_page_count(input_file):
        with fitz.open(OCRService._validate_pdf(input_file)) as document:
            if document.needs_pass:
                raise ValueError('Unlock the PDF first.')
            return len(document)

    @staticmethod
    def ocr_pdf_page(input_file, page_index, lang='eng', dpi=200, preprocess=True):
        with fitz.open(OCRService._validate_pdf(input_file)) as document:
            if not 0 <= page_index < len(document):
                raise ValueError('Page index out of range.')
            image = OCRService._page_image(document[page_index], dpi, preprocess, unrotate=True)
            return pytesseract.image_to_string(image, lang=lang, timeout=120).strip()
