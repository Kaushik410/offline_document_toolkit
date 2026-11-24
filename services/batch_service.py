"""Batch adapters with consistent results, progress, and collision-free names."""
from pathlib import Path

from services.pdf_service import PDFService
from services.image_service import ImageService
from services.ocr_service import OCRService
from services.word_service import WordService


class BatchService:
    @staticmethod
    def _prepare_output_folder(output_folder):
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @staticmethod
    def _available_name(folder, filename):
        candidate = folder / filename
        index = 2
        while candidate.exists():
            candidate = folder / f'{Path(filename).stem}_{index}{Path(filename).suffix}'
            index += 1
        return candidate

    @staticmethod
    def _run(input_files, output_folder, operation, naming, progress_callback=None,
             status_callback=None, cancel_callback=None):
        folder = BatchService._prepare_output_folder(output_folder)
        results, errors = [], []
        for index, source in enumerate(input_files):
            if cancel_callback and cancel_callback():
                break
            source = Path(source)
            output = BatchService._available_name(folder, naming(source))
            if status_callback:
                status_callback(f'Processing {index + 1}/{len(input_files)}: {source.name}')
            try:
                result = operation(source, output)
                if isinstance(result, tuple):
                    path, original, new = result
                    details = {'output': str(path), 'original_size': original, 'new_size': new}
                else:
                    details = {'output': str(result)}
                results.append({'input': str(source), **details})
            except Exception as error:
                errors.append({'input': str(source), 'error': str(error)})
            if progress_callback:
                progress_callback(int((index + 1) / len(input_files) * 100))
        return results, errors

    @staticmethod
    def batch_compress_pdfs(input_files, output_folder, quality='ebook',
                             progress_callback=None, status_callback=None, cancel_callback=None):
        return BatchService._run(input_files, output_folder,
            lambda src, dst: PDFService.compress_pdf(src, dst, quality),
            lambda src: f'{src.stem}_compressed.pdf',
            progress_callback, status_callback, cancel_callback)

    @staticmethod
    def batch_compress_images(input_files, output_folder, quality=70,
                               progress_callback=None, status_callback=None, cancel_callback=None):
        return BatchService._run(input_files, output_folder,
            lambda src, dst: ImageService.compress_image(src, dst, quality),
            lambda src: f'{src.stem}_compressed{src.suffix}',
            progress_callback, status_callback, cancel_callback)

    @staticmethod
    def batch_convert_images(input_files, output_folder, output_format='png',
                              progress_callback=None, status_callback=None, cancel_callback=None):
        ext = 'jpg' if output_format == 'jpeg' else output_format
        return BatchService._run(input_files, output_folder,
            lambda src, dst: ImageService.convert_format(src, dst, output_format),
            lambda src: f'{src.stem}.{ext}',
            progress_callback, status_callback, cancel_callback)

    @staticmethod
    def batch_ocr_images_to_txt(input_files, output_folder, lang='eng', preprocess=True,
                                progress_callback=None, status_callback=None, cancel_callback=None):
        def operation(source, output):
            text = OCRService.image_to_text(source, lang, preprocess)
            return OCRService.save_text_as_txt(text, output)
        return BatchService._run(input_files, output_folder, operation,
            lambda src: f'{src.stem}_ocr.txt',
            progress_callback, status_callback, cancel_callback)

    @staticmethod
    def batch_docx_to_pdf(input_files, output_folder,
                          progress_callback=None, status_callback=None, cancel_callback=None):
        return BatchService._run(input_files, output_folder,
            lambda src, dst: WordService.docx_to_pdf(src, dst.parent, output_file=dst),
            lambda src: f'{src.stem}.pdf',
            progress_callback, status_callback, cancel_callback)

    @staticmethod
    def batch_scanned_pdfs_to_searchable_pdfs(input_files, output_folder, lang='eng',
        dpi=200, preprocess=True, progress_callback=None, status_callback=None, cancel_callback=None):
        return BatchService._run(input_files, output_folder,
            lambda src, dst: OCRService.pdf_to_searchable_pdf(src, dst, lang, dpi, preprocess),
            lambda src: f'{src.stem}_searchable.pdf',
            progress_callback, status_callback, cancel_callback)
