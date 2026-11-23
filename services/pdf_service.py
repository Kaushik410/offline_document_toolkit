from utils.external_process import run_external
from pathlib import Path
import subprocess
import shutil
import tempfile
import io
from utils.output_utils import atomic_output, distinct_output

from pypdf import PdfReader, PdfWriter
import fitz  # PyMuPDF

from PIL import Image, ImageDraw, ImageFont
from services.image_service import ImageService


class PDFService:

    @staticmethod
    def _validate_pdf(input_file):
        input_path = Path(input_file)

        if not input_path.exists():
            raise FileNotFoundError(f"PDF file not found: {input_file}")

        if input_path.suffix.lower() != ".pdf":
            raise ValueError("Input file must be a PDF file.")

        return input_path

    @staticmethod
    def _prepare_output_pdf(output_file):
        output_path = Path(output_file)

        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        return output_path

    @staticmethod
    def _parse_page_range(page_range, total_pages):
        pages = set()

        parts = page_range.replace(" ", "").split(",")

        for part in parts:
            if not part:
                continue

            if "-" in part:
                start, end = part.split("-")

                if not start.isdigit() or not end.isdigit():
                    raise ValueError("Invalid page range format.")

                start = int(start)
                end = int(end)

                if start > end:
                    raise ValueError("Invalid page range. Start page is greater than end page.")

                for page_num in range(start, end + 1):
                    if page_num < 1 or page_num > total_pages:
                        raise ValueError(f"Page number out of range: {page_num}")

                    pages.add(page_num - 1)

            else:
                if not part.isdigit():
                    raise ValueError("Invalid page number format.")

                page_num = int(part)

                if page_num < 1 or page_num > total_pages:
                    raise ValueError(f"Page number out of range: {page_num}")

                pages.add(page_num - 1)

        return sorted(pages)

    @staticmethod
    def merge_pdfs(input_files, output_file):
        if not input_files:
            raise ValueError("No PDF files selected.")

        output_path = PDFService._prepare_output_pdf(output_file)

        writer = PdfWriter()

        for input_file in input_files:
            input_path = PDFService._validate_pdf(input_file)
            reader = PdfReader(str(input_path))

            if reader.is_encrypted:
                raise ValueError(f"Encrypted PDF cannot be merged without unlocking: {input_path.name}")

            for page in reader.pages:
                writer.add_page(page)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def split_pdf(input_file, output_folder):
        input_path = PDFService._validate_pdf(input_file)

        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Encrypted PDF cannot be split without unlocking.")

        output_files = []

        for index, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)

            output_file = output_dir / f"{input_path.stem}_page_{index}.pdf"

            with atomic_output(output_file) as temporary:
                with open(temporary, "wb") as f:
                    writer.write(f)

            output_files.append(str(output_file))

        return output_files

    @staticmethod
    def extract_pages(input_file, page_range, output_file):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Encrypted PDF cannot be processed without unlocking.")

        total_pages = len(reader.pages)
        selected_pages = PDFService._parse_page_range(page_range, total_pages)

        if not selected_pages:
            raise ValueError("No valid pages selected.")

        writer = PdfWriter()

        for page_index in selected_pages:
            writer.add_page(reader.pages[page_index])

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def delete_pages(input_file, page_range, output_file):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Encrypted PDF cannot be processed without unlocking.")

        total_pages = len(reader.pages)
        pages_to_delete = set(PDFService._parse_page_range(page_range, total_pages))

        if len(pages_to_delete) >= total_pages:
            raise ValueError("Cannot delete all pages from the PDF.")

        writer = PdfWriter()

        for index, page in enumerate(reader.pages):
            if index not in pages_to_delete:
                writer.add_page(page)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def rotate_pages(input_file, page_range, angle, output_file):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        if angle not in [90, 180, 270]:
            raise ValueError("Rotation angle must be 90, 180, or 270 degrees.")

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Encrypted PDF cannot be processed without unlocking.")

        total_pages = len(reader.pages)
        pages_to_rotate = set(PDFService._parse_page_range(page_range, total_pages))

        writer = PdfWriter()

        for index, page in enumerate(reader.pages):
            if index in pages_to_rotate:
                page.rotate(angle)

            writer.add_page(page)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def compress_pdf(input_file, output_file, quality="ebook"):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        from utils.engine_registry import EngineRegistry
        gs_path = EngineRegistry.find("ghostscript")

        if not gs_path:
            raise RuntimeError(
                "Ghostscript was not found. Open Settings → Setup to install or locate it."
            )

        quality_map = {
            "screen": "/screen",
            "ebook": "/ebook",
            "printer": "/printer",
            "prepress": "/prepress",
        }

        pdf_setting = quality_map.get(quality, "/ebook")

        distinct_output(input_path, output_path)
        with atomic_output(output_path) as temporary:
            command = [gs_path, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                       f"-dPDFSETTINGS={pdf_setting}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                       f"-sOutputFile={temporary}", str(input_path)]
            try:
                result = run_external(command, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("Ghostscript compression timed out after 120 seconds.") from error
            if result.returncode != 0:
                raise RuntimeError(f"Ghostscript compression failed:\n{result.stderr}")

        original_size = input_path.stat().st_size
        compressed_size = output_path.stat().st_size

        return str(output_path), original_size, compressed_size

    @staticmethod
    def pdf_to_images(input_file, output_folder, image_format="png", dpi=200):
        input_path = PDFService._validate_pdf(input_file)

        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_format = image_format.lower()

        if image_format not in ["png", "jpg", "jpeg"]:
            raise ValueError("Image format must be png or jpg.")

        doc = fitz.open(str(input_path))
        output_files = []

        try:
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)

            for page_index in range(len(doc)):
                page = doc[page_index]
                pix = page.get_pixmap(matrix=matrix, alpha=False)

                output_file = output_dir / f"{input_path.stem}_page_{page_index + 1}.{image_format}"
                with atomic_output(output_file) as temporary:
                    pix.save(str(temporary))

                output_files.append(str(output_file))

        finally:
            doc.close()

        return output_files

    @staticmethod
    def images_to_pdf(input_files, output_file):
        if not input_files:
            raise ValueError("No image files selected.")

        output_path = PDFService._prepare_output_pdf(output_file)

        images = []

        try:
            for input_file in input_files:
                img_path = Path(input_file)

                if not img_path.exists():
                    raise FileNotFoundError(f"Image file not found: {input_file}")

                for frame in ImageService.load_frames(img_path):
                    images.append(ImageService.to_rgb(frame))

            if not images:
                raise ValueError("No valid images selected.")

            first_image = images[0]
            remaining_images = images[1:]

            with atomic_output(output_path) as temporary:
                first_image.save(str(temporary), save_all=True, append_images=remaining_images)

        finally:
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass

        return str(output_path)

    @staticmethod
    def protect_pdf(input_file, output_file, password):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        if not password:
            raise ValueError("Password cannot be empty.")

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Input PDF is already encrypted.")

        writer = PdfWriter(clone_from=reader)
        writer.encrypt(password)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def unlock_pdf(input_file, output_file, password):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        if not password:
            raise ValueError("Password cannot be empty.")

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            result = reader.decrypt(password)

            if result == 0:
                raise ValueError("Incorrect password or unable to decrypt PDF.")

        writer = PdfWriter(clone_from=reader)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)

    @staticmethod
    def _overlay_display_page(page, overlay):
        """Place a layer made in visible-page coordinates onto any rotation/crop."""
        rotation = page.rotation
        page.set_rotation(0)
        try:
            page.show_pdf_page(page.rect, overlay, 0, rotate=rotation,
                               keep_proportion=False, overlay=True)
        finally:
            page.set_rotation(rotation)

    @staticmethod
    def add_page_numbers(input_file, output_file, position="bottom-center"):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)
        if position not in ("bottom-left", "bottom-center", "bottom-right"):
            raise ValueError("Choose a bottom-left, bottom-center, or bottom-right position.")
        with fitz.open(str(input_path)) as document:
            for index, page in enumerate(document, start=1):
                rect = page.rect
                text = str(index)
                margin_x, margin_y = min(40, rect.width / 8), min(25, rect.height / 8)
                font_size = min(10, rect.height / 3,
                    (rect.width - 2 * margin_x) / fitz.get_text_length(text, fontsize=1))
                text_width = fitz.get_text_length(text, fontsize=font_size)
                if position == "bottom-left":
                    x = margin_x
                elif position == "bottom-right":
                    x = rect.width - margin_x - text_width
                else:
                    x = (rect.width - text_width) / 2
                with fitz.open() as overlay:
                    layer = overlay.new_page(width=rect.width, height=rect.height)
                    layer.insert_text((x, rect.height - margin_y), text,
                                      fontsize=font_size, color=(0, 0, 0))
                    PDFService._overlay_display_page(page, overlay)
            with atomic_output(output_path) as temporary:
                document.save(str(temporary), garbage=4, deflate=True)
        return str(output_path)

    @staticmethod
    def add_watermark(input_file, output_file, watermark_text, watermark_style="diagonal"):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)
        if not watermark_text.strip():
            raise ValueError("Watermark text cannot be empty.")
        if watermark_style not in ("horizontal", "diagonal"):
            raise ValueError("Watermark style must be horizontal or diagonal.")
        with fitz.open(str(input_path)) as document:
            for page in document:
                rect = page.rect
                # Render at twice PDF resolution and scale to fit even long labels.
                width, height = max(1, round(rect.width * 2)), max(1, round(rect.height * 2))
                try:
                    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 108)
                except OSError:
                    font = ImageFont.load_default(size=108)
                bounds = font.getbbox(watermark_text)
                text_width, text_height = max(1, bounds[2] - bounds[0]), max(1, bounds[3] - bounds[1])
                label = Image.new("RGBA", (text_width + 8, text_height + 8))
                ImageDraw.Draw(label).text((4 - bounds[0], 4 - bounds[1]), watermark_text,
                                          font=font, fill=(100, 100, 100, 85))
                if watermark_style == "diagonal":
                    label = label.rotate(35, expand=True, resample=Image.Resampling.BICUBIC)
                label.thumbnail((max(1, int(width * 0.85)), max(1, int(height * 0.75))),
                                Image.Resampling.LANCZOS)
                image = Image.new("RGBA", (width, height))
                image.alpha_composite(label, ((width - label.width) // 2, (height - label.height) // 2))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                with fitz.open() as overlay:
                    layer = overlay.new_page(width=rect.width, height=rect.height)
                    layer.insert_image(layer.rect, stream=buffer.getvalue())
                    PDFService._overlay_display_page(page, overlay)
            with atomic_output(output_path) as temporary:
                document.save(str(temporary), garbage=4, deflate=True)
        return str(output_path)

    @staticmethod
    def get_pdf_page_count(input_file):
        input_path = PDFService._validate_pdf(input_file)

        doc = fitz.open(str(input_path))

        try:
            return len(doc)

        finally:
            doc.close()

    @staticmethod
    def render_pdf_page(input_file, page_index, output_file=None, dpi=120):
        input_path = PDFService._validate_pdf(input_file)

        if page_index < 0:
            raise ValueError("Page index cannot be negative.")

        doc = fitz.open(str(input_path))

        try:
            if page_index >= len(doc):
                raise ValueError("Page index out of range.")

            page = doc[page_index]

            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)

            pix = page.get_pixmap(matrix=matrix, alpha=False)

            if output_file is None:
                temp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                temp.close()
                output_file = temp.name

            pix.save(str(output_file))
            return str(output_file)

        finally:
            doc.close()

    @staticmethod
    def save_organized_pdf(input_file, output_file, page_order, rotations=None):
        input_path = PDFService._validate_pdf(input_file)
        output_path = PDFService._prepare_output_pdf(output_file)

        reader = PdfReader(str(input_path))

        if reader.is_encrypted:
            raise ValueError("Encrypted PDF cannot be organized without unlocking.")

        total_pages = len(reader.pages)

        if not page_order:
            raise ValueError("Page order cannot be empty.")

        if rotations is None:
            rotations = {}

        writer = PdfWriter()

        for original_page_index in page_order:
            if original_page_index < 0 or original_page_index >= total_pages:
                raise ValueError(f"Invalid page index: {original_page_index}")

            page = reader.pages[original_page_index]

            angle = rotations.get(original_page_index, 0) % 360

            if angle:
                page.rotate(angle)

            writer.add_page(page)

        with atomic_output(output_path) as temporary:
            with open(temporary, "wb") as f:
                writer.write(f)

        return str(output_path)
    @staticmethod
    def render_thumbnails(input_file, dpi=45, progress_callback=None):
        with fitz.open(PDFService._validate_pdf(input_file)) as document:
            if document.needs_pass:
                raise ValueError("Unlock the PDF first.")
            thumbnails = []
            for index, page in enumerate(document):
                thumbnails.append(page.get_pixmap(dpi=dpi, alpha=False).tobytes("png"))
                if progress_callback:
                    progress_callback(int((index + 1) / len(document) * 100))
            return thumbnails
