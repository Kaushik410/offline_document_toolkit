from utils.external_process import run_external
from pathlib import Path
import subprocess
import tempfile
import os
import io
import re
import socket
import shutil
import fitz  # PyMuPDF

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from utils.output_utils import atomic_output


class WordService:
    SUPPORTED_DOCX = [".docx"]
    SUPPORTED_TXT = [".txt"]
    SUPPORTED_IMAGES = [".png", ".jpg", ".jpeg", ".webp", ".bmp"]

    @staticmethod
    def _validate_docx(file_path):
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if path.suffix.lower() not in WordService.SUPPORTED_DOCX:
            raise ValueError(f"Not a DOCX file: {file_path}")

        return path

    @staticmethod
    def _validate_txt(file_path):
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if path.suffix.lower() not in WordService.SUPPORTED_TXT:
            raise ValueError(f"Not a TXT file: {file_path}")

        return path

    @staticmethod
    def _validate_image(file_path):
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Image not found: {file_path}")

        if path.suffix.lower() not in WordService.SUPPORTED_IMAGES:
            raise ValueError(f"Unsupported image file: {file_path}")

        return path

    @staticmethod
    def _prepare_output_path(output_file, default_ext):
        output_path = Path(output_file)

        if output_path.suffix == "":
            output_path = output_path.with_suffix(default_ext)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        return output_path

    @staticmethod
    def _find_libreoffice():
        from utils.engine_registry import EngineRegistry
        path = EngineRegistry.find("libreoffice")
        if path:
            return path

        raise RuntimeError(
            "LibreOffice was not found. Open Settings → Setup to install or locate it."
        )

    @staticmethod
    def docx_to_pdf(input_file, output_folder, output_file=None):
        path = WordService._validate_docx(input_file).resolve()
        output_dir = Path(output_folder).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = Path(output_file) if output_file else output_dir / f"{path.stem}.pdf"
        libreoffice = WordService._find_libreoffice()
        with tempfile.TemporaryDirectory(prefix="odt-libreoffice-") as directory:
            work = Path(directory)
            if os.name == "posix":
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                        probe.bind(str(work / "ipc-probe"))
                        probe.listen(1)
                except PermissionError as error:
                    raise RuntimeError(
                        "LibreOffice needs local IPC socket binding, which this sandbox blocks. "
                        "Run this conversion in a desktop or container that permits local IPC.") from error
                finally:
                    (work / "ipc-probe").unlink(missing_ok=True)
            env = os.environ.copy()
            # Avoid shared profiles, desktop configuration, and stale output detection.
            env.update({"GSETTINGS_BACKEND": "memory", "SAL_USE_VCLPLUGIN": "svp",
                        "XDG_CACHE_HOME": str(work / "cache"),
                        "XDG_CONFIG_HOME": str(work / "config")})
            if os.name == "posix":
                runtime = work / "runtime"
                runtime.mkdir(mode=0o700)
                env["XDG_RUNTIME_DIR"] = str(runtime)
            command = [libreoffice, f"-env:UserInstallation={(work / 'profile').as_uri()}",
                       "--headless", "--norestore", "--convert-to", "pdf:writer_pdf_Export",
                       "--outdir", str(work), str(path)]
            try:
                result = run_external(command, capture_output=True, text=True,
                                        timeout=120, env=env)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("LibreOffice conversion timed out after 120 seconds.") from error
            converted = work / f"{path.stem}.pdf"
            if result.returncode != 0 or not converted.is_file():
                raise RuntimeError(f"LibreOffice conversion failed.\n{result.stdout}\n{result.stderr}")
            with atomic_output(output) as temporary:
                shutil.copyfile(converted, temporary)
        return str(output)

    @staticmethod
    def docx_to_txt(input_file, output_file):
        path = WordService._validate_docx(input_file)
        output_path = WordService._prepare_output_path(output_file, ".txt")

        document = Document(str(path))

        lines = []

        for paragraph in document.paragraphs:
            lines.append(paragraph.text)

        for table_index, table in enumerate(document.tables, start=1):
            lines.append("")
            lines.append(f"[Table {table_index}]")

            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    row_text.append(cell.text.strip())
                lines.append("\t".join(row_text))

        with atomic_output(output_path) as temporary:
            temporary.write_text("\n".join(lines), encoding="utf-8")

        return str(output_path)

    @staticmethod
    def txt_to_docx(input_file, output_file):
        path = WordService._validate_txt(input_file)
        output_path = WordService._prepare_output_path(output_file, ".docx")

        document = Document()
        document.add_heading(path.stem, level=1)

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            clean_line = line.rstrip("\n")

            if clean_line.strip():
                document.add_paragraph(clean_line)
            else:
                document.add_paragraph("")

        with atomic_output(output_path) as temporary:
            document.save(temporary)

        return str(output_path)

    @staticmethod
    def find_replace_docx(input_file, output_file, find_text, replace_text):
        if not find_text:
            raise ValueError("Find text cannot be empty.")

        path = WordService._validate_docx(input_file)
        output_path = WordService._prepare_output_path(output_file, ".docx")

        document = Document(str(path))

        def replace_group(nodes):
            text = "".join(node.text or "" for node in nodes)
            offsets = []
            offset = 0
            for node in nodes:
                offsets.append(offset)
                offset += len(node.text or "")
            matches = []
            start = 0
            while True:
                start = text.find(find_text, start)
                if start < 0:
                    break
                matches.append((start, start + len(find_text)))
                start += len(find_text)
            if not matches:
                return
            # Change w:t nodes only. Run.text would delete drawings and field XML.
            for start, end in reversed(matches):
                first = next(i for i, node in enumerate(nodes)
                             if offsets[i] <= start < offsets[i] + len(node.text or ""))
                last = next(i for i, node in enumerate(nodes)
                            if offsets[i] < end <= offsets[i] + len(node.text or ""))
                prefix = (nodes[first].text or "")[:start - offsets[first]]
                suffix = (nodes[last].text or "")[end - offsets[last]:]
                if first == last:
                    nodes[first].text = prefix + replace_text + suffix
                else:
                    nodes[first].text = prefix + replace_text
                    for index in range(first + 1, last):
                        nodes[index].text = ""
                    nodes[last].text = suffix
            for node in nodes:
                value = node.text or ""
                node.set(qn("xml:space"), "preserve")
                # Represent replacement tabs and line breaks using proper Word elements.
                if any(character in value for character in "\t\r\n"):
                    parent = node.getparent()
                    position = parent.index(node)
                    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
                    for piece in re.split(r"([\t\n])", normalized):
                        element = OxmlElement("w:tab" if piece == "\t" else "w:br" if piece == "\n" else "w:t")
                        if piece not in ("\t", "\n"):
                            element.text = piece
                            element.set(qn("xml:space"), "preserve")
                        parent.insert(position, element)
                        position += 1
                    parent.remove(node)

        def replace_in_paragraph(paragraph):
            nodes = []
            for run in paragraph.xpath("./w:r | ./w:hyperlink/w:r"):
                for element in run:
                    if element.tag == qn("w:t"):
                        nodes.append(element)
                    elif element.tag != qn("w:rPr"):
                        # A drawing, field, or break separates distinct text sequences.
                        replace_group(nodes)
                        nodes = []
            replace_group(nodes)

        # Body, nested tables, headers, footers, and text boxes; visit each XML part once.
        for part in document.part.package.parts:
            element = getattr(part, "element", None)
            if element is not None:
                for paragraph in element.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    replace_in_paragraph(paragraph)

        with atomic_output(output_path) as temporary:
            document.save(temporary)

        return str(output_path)

    @staticmethod
    def add_image_to_docx(input_file, image_file, output_file, width_inches=4.0):
        path = WordService._validate_docx(input_file)
        image_path = WordService._validate_image(image_file)
        output_path = WordService._prepare_output_path(output_file, ".docx")

        if width_inches <= 0:
            raise ValueError("Image width must be greater than 0.")

        document = Document(str(path))

        document.add_paragraph("")
        document.add_picture(str(image_path), width=Inches(width_inches))

        with atomic_output(output_path) as temporary:
            document.save(temporary)

        return str(output_path)

    @staticmethod
    def generate_certificate(
        output_file,
        recipient_name,
        certificate_title,
        body_text,
        issued_by,
        issue_date
    ):
        if not recipient_name.strip():
            raise ValueError("Recipient name cannot be empty.")

        if not certificate_title.strip():
            raise ValueError("Certificate title cannot be empty.")

        if not body_text.strip():
            raise ValueError("Certificate body cannot be empty.")

        if not issued_by.strip():
            raise ValueError("Issued by field cannot be empty.")

        if not issue_date.strip():
            raise ValueError("Issue date cannot be empty.")

        output_path = WordService._prepare_output_path(output_file, ".docx")

        document = Document()

        section = document.sections[0]
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

        title = document.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title.add_run(certificate_title.upper())
        title_run.bold = True
        title_run.font.size = Pt(24)

        document.add_paragraph("")

        subtitle = document.add_paragraph()
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle_run = subtitle.add_run("This is to certify that")
        subtitle_run.font.size = Pt(14)

        name_para = document.add_paragraph()
        name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        name_run = name_para.add_run(recipient_name)
        name_run.bold = True
        name_run.font.size = Pt(22)

        document.add_paragraph("")

        body_para = document.add_paragraph()
        body_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        body_run = body_para.add_run(body_text)
        body_run.font.size = Pt(13)

        document.add_paragraph("")
        document.add_paragraph("")

        date_para = document.add_paragraph()
        date_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        date_run = date_para.add_run(f"Date: {issue_date}")
        date_run.font.size = Pt(12)

        issued_para = document.add_paragraph()
        issued_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        issued_run = issued_para.add_run(f"Issued by: {issued_by}")
        issued_run.font.size = Pt(12)
        issued_run.bold = True

        with atomic_output(output_path) as temporary:
            document.save(temporary)

        return str(output_path)
    
    @staticmethod
    def pdf_to_docx(input_file, output_file, mode="appearance", dpi=200,
                    progress_callback=None, status_callback=None):
        if mode == "editable":
            return WordService.pdf_to_docx_editable(input_file, output_file,
                progress_callback=progress_callback, status_callback=status_callback)
        if mode != "appearance":
            raise ValueError("PDF conversion mode must be appearance or editable.")
        input_path = Path(input_file)
        if not input_path.is_file() or input_path.suffix.lower() != ".pdf":
            raise ValueError("Select an existing PDF file.")
        output = WordService._prepare_output_path(output_file, ".docx").with_suffix(".docx")
        document = Document()
        with fitz.open(input_path) as source:
            if source.needs_pass:
                raise ValueError("Unlock the PDF before conversion.")
            for index, page in enumerate(source):
                if status_callback:
                    status_callback(f"Preserving page {index + 1}/{len(source)}")
                section = document.sections[0] if index == 0 else document.add_section(WD_SECTION_START.NEW_PAGE)
                section.page_width, section.page_height = Pt(page.rect.width), Pt(page.rect.height)
                section.top_margin = section.bottom_margin = Pt(0)
                section.left_margin = section.right_margin = Pt(0)
                section.header_distance = section.footer_distance = Pt(0)
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = Pt(1)
                picture = paragraph.add_run().add_picture(
                    io.BytesIO(page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")),
                    width=section.page_width, height=section.page_height)
                # Anchor to the physical page so a full-height image cannot add a blank page.
                inline = picture._inline
                anchor = OxmlElement("wp:anchor")
                for key, value in {"distT": "0", "distB": "0", "distL": "0", "distR": "0",
                    "simplePos": "0", "relativeHeight": "0", "behindDoc": "0",
                    "locked": "0", "layoutInCell": "1", "allowOverlap": "1"}.items():
                    anchor.set(key, value)
                simple = OxmlElement("wp:simplePos"); simple.set("x", "0"); simple.set("y", "0")
                anchor.append(simple)
                for axis in ("H", "V"):
                    position = OxmlElement("wp:position" + axis)
                    position.set("relativeFrom", "page")
                    offset = OxmlElement("wp:posOffset"); offset.text = "0"
                    position.append(offset); anchor.append(position)
                for tag in ("extent", "effectExtent"):
                    for child in list(inline):
                        if child.tag.endswith("}" + tag):
                            anchor.append(child)
                anchor.append(OxmlElement("wp:wrapNone"))
                for child in list(inline):
                    anchor.append(child)
                inline.getparent().replace(inline, anchor)
                if progress_callback:
                    progress_callback(int((index + 1) / len(source) * 100))
        with atomic_output(output) as temporary:
            document.save(temporary)
        return str(output)

    @staticmethod
    def pdf_to_docx_editable(input_file, output_file, progress_callback=None, status_callback=None):
        """Reconstruct styled paragraphs, tables, and images in editable page sections.

        PDF is a fixed layout format, so this is a best-effort reconstruction.
        Appearance mode is available when exact page layout matters more than editing.
        """
        input_path = Path(input_file)
        if not input_path.is_file() or input_path.suffix.lower() != ".pdf":
            raise ValueError("Select an existing PDF file.")
        output = WordService._prepare_output_path(output_file, ".docx").with_suffix(".docx")
        document = Document()
        with fitz.open(input_path) as source:
            if source.needs_pass:
                raise ValueError("Unlock the PDF before conversion.")
            for index, page in enumerate(source):
                if status_callback:
                    status_callback(f"Reconstructing page {index + 1}/{len(source)}")
                page.remove_rotation()
                section = document.sections[0] if index == 0 else document.add_section(WD_SECTION_START.NEW_PAGE)
                section.page_width, section.page_height = Pt(page.rect.width), Pt(page.rect.height)
                margin = min(24, page.rect.width / 10, page.rect.height / 10)
                section.top_margin = section.bottom_margin = Pt(margin)
                section.left_margin = section.right_margin = Pt(margin)
                usable_width = page.rect.width - 2 * margin
                tables = page.find_tables().tables
                items = [(tuple(table.bbox), "table", table.extract()) for table in tables]
                table_rects = [fitz.Rect(table.bbox) for table in tables]
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_IMAGES)["blocks"]
                for block in blocks:
                    if block["type"] == 1:
                        items.append((block["bbox"], "image", block["image"]))
                    elif block["type"] == 0:
                        for line in block["lines"]:
                            rect = fitz.Rect(line["bbox"])
                            center = (rect.tl + rect.br) / 2
                            if not any(center in table_rect for table_rect in table_rects):
                                items.append((line["bbox"], "text", line["spans"]))
                cursor = margin
                for bbox, kind, content in sorted(items, key=lambda item: (item[0][1], item[0][0])):
                    if kind == "table":
                        if not content:
                            continue
                        table = document.add_table(rows=len(content), cols=max(map(len, content)))
                        table.style = "Table Grid"
                        for row_index, row in enumerate(content):
                            for col_index, text in enumerate(row):
                                table.cell(row_index, col_index).text = text or ""
                    else:
                        paragraph = document.add_paragraph()
                        formatting = paragraph.paragraph_format
                        formatting.space_before = Pt(max(0, bbox[1] - cursor))
                        formatting.space_after = Pt(0)
                        formatting.left_indent = Pt(max(0, min(bbox[0] - margin, usable_width - 1)))
                        if kind == "image":
                            width = min(bbox[2] - bbox[0], usable_width)
                            paragraph.add_run().add_picture(io.BytesIO(content), width=Pt(width))
                        else:
                            formatting.line_spacing = 1.0
                            for span in content:
                                run = paragraph.add_run(span["text"])
                                run.font.name = span["font"].split("+")[-1]
                                run.font.size = Pt(span["size"])
                                run.bold = bool(span["flags"] & 16)
                                run.italic = bool(span["flags"] & 2)
                                run.font.color.rgb = RGBColor.from_string(f'{span["color"]:06X}')
                    cursor = max(cursor, bbox[3])
                if not items:
                    document.add_paragraph("[No editable content found. Use OCR for scanned text.]")
                if progress_callback:
                    progress_callback(int((index + 1) / len(source) * 100))
        with atomic_output(output) as temporary:
            document.save(temporary)
        return str(output)

    @staticmethod
    def pdf_to_docx_basic(input_file, output_file):
        input_path = Path(input_file)

        if not input_path.exists():
            raise FileNotFoundError(f"PDF file not found: {input_file}")

        if input_path.suffix.lower() != ".pdf":
            raise ValueError("Input file must be a PDF file.")

        output_path = Path(output_file)

        if output_path.suffix.lower() != ".docx":
            output_path = output_path.with_suffix(".docx")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        pdf_doc = fitz.open(str(input_path))
        docx = Document()

        docx.add_heading(input_path.stem, level=1)

        try:
            for page_index, page in enumerate(pdf_doc):
                if page_index > 0:
                    paragraph = docx.add_paragraph()
                    run = paragraph.add_run()
                    run.add_break(WD_BREAK.PAGE)

                docx.add_heading(f"Page {page_index + 1}", level=2)

                blocks = page.get_text("blocks")
                blocks = sorted(blocks, key=lambda block: (block[1], block[0]))

                page_has_text = False

                for block in blocks:
                    text = block[4].strip()

                    if not text:
                        continue

                    page_has_text = True

                    for line in text.splitlines():
                        clean_line = line.strip()

                        if clean_line:
                            docx.add_paragraph(clean_line)

                if not page_has_text:
                    docx.add_paragraph("[No selectable text found on this page. Try Scanned PDF to DOCX using OCR.]")

        finally:
            pdf_doc.close()

        with atomic_output(output_path) as temporary:
            docx.save(temporary)
        return str(output_path)

    @staticmethod
    def scanned_pdf_to_docx_ocr(
        input_file,
        output_file,
        lang="eng",
        dpi=200,
        preprocess=True
    ):
        input_path = Path(input_file)

        if not input_path.exists():
            raise FileNotFoundError(f"PDF file not found: {input_file}")

        if input_path.suffix.lower() != ".pdf":
            raise ValueError("Input file must be a PDF file.")

        output_path = Path(output_file)

        if output_path.suffix.lower() != ".docx":
            output_path = output_path.with_suffix(".docx")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        from services.ocr_service import OCRService

        text = OCRService.pdf_to_text(
            str(input_path),
            lang=lang,
            dpi=dpi,
            preprocess=preprocess
        )

        if not text.strip():
            text = "[No text detected]"

        result_path = OCRService.save_text_as_docx(
            text,
            str(output_path)
        )

        return result_path
