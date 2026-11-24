from utils.file_dialog_utils import normalize_output_selection
from utils.task_controller import run_task
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGridLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QInputDialog,
)

from services.word_service import WordService
from utils.file_dialog_utils import get_default_output_folder, get_default_output_path


class WordToolsPage(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        self.setLayout(layout)

        title = QLabel("Word / DOCX Tools")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Convert, extract, and edit DOCX documents locally using python-docx and LibreOffice."
        )
        subtitle.setStyleSheet("font-size: 15px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(16)

        tools = [
            "DOCX to PDF",
            "PDF to DOCX",
            "Scanned PDF to DOCX",
            "DOCX to TXT",
            "TXT to DOCX",
            "Find and Replace",
            "Add Image to DOCX",
            "Generate Certificate",
        ]

        self.tool_buttons = {}

        for i, tool in enumerate(tools):
            button = self.create_tool_button(tool)
            self.tool_buttons[tool] = button
            grid.addWidget(button, i // 3, i % 3)

        layout.addLayout(grid)
        layout.addStretch()

        self.tool_buttons["DOCX to PDF"].clicked.connect(self.handle_docx_to_pdf)
        self.tool_buttons["DOCX to TXT"].clicked.connect(self.handle_docx_to_txt)
        self.tool_buttons["TXT to DOCX"].clicked.connect(self.handle_txt_to_docx)
        self.tool_buttons["Find and Replace"].clicked.connect(self.handle_find_replace)
        self.tool_buttons["Add Image to DOCX"].clicked.connect(self.handle_add_image_to_docx)
        self.tool_buttons["PDF to DOCX"].clicked.connect(self.handle_pdf_to_docx)
        self.tool_buttons["Scanned PDF to DOCX"].clicked.connect(
            self.handle_scanned_pdf_to_docx
        )
        self.tool_buttons["Generate Certificate"].clicked.connect(
            self.handle_generate_certificate
        )

    def create_tool_button(self, text):
        button = QPushButton(text)
        button.setMinimumHeight(85)
        button.setStyleSheet("""
            QPushButton {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                font-size: 15px;
                font-weight: 500;
            }

            QPushButton:hover {
                border: 1px solid #f97316;
                background-color: #fff7ed;
            }
        """)
        return button

    def select_docx(self, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Word Files (*.docx)"
        )
        return file_path 
    
    def select_pdf(self, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "PDF Files (*.pdf)"
        )
        return file_path

    def select_txt(self, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Text Files (*.txt)"
        )
        return file_path

    def select_image(self, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        return file_path

    def select_output_docx(self, title, default_name):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            title,
            get_default_output_path(default_name),
            "Word Files (*.docx)"
        )

        return normalize_output_selection(self, output_file, ".docx", append=True)

    def select_output_txt(self, title, default_name):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            title,
            get_default_output_path(default_name),
            "Text Files (*.txt)"
        )

        return normalize_output_selection(self, output_file, ".txt", append=True)

    def select_output_folder(self, title):
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            get_default_output_folder()
        )
        return folder

    def handle_docx_to_pdf(self):
        input_file = self.select_docx("Select DOCX file to convert to PDF")
        if not input_file:
            return

        output_folder = self.select_output_folder("Select folder to save PDF")
        if not output_folder:
            return

        def completed(result):
            result_path = result
            self.show_success("DOCX converted to PDF successfully.", result_path)
        run_task(self, WordService.docx_to_pdf, input_file, output_folder, on_success=completed)

    def handle_docx_to_txt(self):
        input_file = self.select_docx("Select DOCX file to convert to TXT")
        if not input_file:
            return

        output_file = self.select_output_txt(
            "Save TXT file as",
            "docx_output.txt"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("DOCX converted to TXT successfully.", result_path)
        run_task(self, WordService.docx_to_txt, input_file, output_file, on_success=completed)

    def handle_txt_to_docx(self):
        input_file = self.select_txt("Select TXT file to convert to DOCX")
        if not input_file:
            return

        output_file = self.select_output_docx(
            "Save DOCX file as",
            "txt_output.docx"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("TXT converted to DOCX successfully.", result_path)
        run_task(self, WordService.txt_to_docx, input_file, output_file, on_success=completed)

    def handle_find_replace(self):
        input_file = self.select_docx("Select DOCX file for find and replace")
        if not input_file:
            return

        find_text, ok = QInputDialog.getText(
            self,
            "Find Text",
            "Enter text to find:"
        )

        if not ok or not find_text:
            return

        replace_text, ok = QInputDialog.getText(
            self,
            "Replace Text",
            "Enter replacement text:"
        )

        if not ok:
            return

        output_file = self.select_output_docx(
            "Save updated DOCX as",
            "replaced_output.docx"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Find and replace completed successfully.", result_path)
        run_task(self, WordService.find_replace_docx, input_file, output_file, find_text, replace_text, on_success=completed)

    def handle_add_image_to_docx(self):
        input_file = self.select_docx("Select DOCX file")
        if not input_file:
            return

        image_file = self.select_image("Select image to add")
        if not image_file:
            return

        width_inches, ok = QInputDialog.getDouble(
            self,
            "Image Width",
            "Enter image width in inches:",
            4.0,
            0.5,
            8.0,
            1
        )

        if not ok:
            return

        output_file = self.select_output_docx(
            "Save DOCX with image as",
            "docx_with_image.docx"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Image added to DOCX successfully.", result_path)
        run_task(self, WordService.add_image_to_docx, input_file, image_file, output_file, width_inches=width_inches, on_success=completed)

    def handle_generate_certificate(self):
        recipient_name, ok = QInputDialog.getText(
            self,
            "Recipient Name",
            "Enter recipient name:"
        )

        if not ok or not recipient_name.strip():
            return

        certificate_title, ok = QInputDialog.getText(
            self,
            "Certificate Title",
            "Enter certificate title:",
            text="Certificate of Completion"
        )

        if not ok or not certificate_title.strip():
            return

        body_text, ok = QInputDialog.getMultiLineText(
            self,
            "Certificate Body",
            "Enter certificate body:",
            "has successfully completed the assigned work with sincerity and dedication."
        )

        if not ok or not body_text.strip():
            return

        issued_by, ok = QInputDialog.getText(
            self,
            "Issued By",
            "Enter issuer name/designation:"
        )

        if not ok or not issued_by.strip():
            return

        issue_date, ok = QInputDialog.getText(
            self,
            "Issue Date",
            "Enter issue date:",
            text="Date"
        )

        if not ok or not issue_date.strip():
            return

        output_file = self.select_output_docx(
            "Save certificate as",
            "certificate.docx"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Certificate generated successfully.", result_path)
        run_task(self, WordService.generate_certificate, output_file=output_file, recipient_name=recipient_name, certificate_title=certificate_title, body_text=body_text, issued_by=issued_by, issue_date=issue_date, on_success=completed)

    def show_info(self, title, message):
        QMessageBox.information(
            self,
            title,
            message
        )

    def show_success(self, message, result_path):
        QMessageBox.information(
            self,
            "Success",
            f"{message}\n\nSaved at:\n{result_path}"
        )

    def show_error(self, message, error):
        QMessageBox.critical(
            self,
            "Error",
            f"{message}\n\nReason:\n{str(error)}"
        )

    def ask_ocr_language(self):
        lang, ok = QInputDialog.getItem(
            self,
            "OCR Language",
            "Select OCR language:",
            ["eng", "hin"],
            0,
            False
        )

        if not ok:
            return None

        return lang

    def ask_preprocess(self):
        choice, ok = QInputDialog.getItem(
            self,
            "Preprocessing",
            "Apply scanned-document preprocessing?",
            ["yes", "no"],
            0,
            False
        )

        if not ok:
            return None

        return choice == "yes"

    def ask_dpi(self):
        dpi, ok = QInputDialog.getInt(
            self,
            "PDF Render DPI",
            "Enter DPI for rendering scanned PDF pages:",
            200,
            100,
            400,
            50
        )

        if not ok:
            return None

        return dpi 
    
    def handle_pdf_to_docx(self):
        input_file = self.select_pdf("Select PDF file to convert to DOCX")
        if not input_file:
            return

        output_file = self.select_output_docx(
            "Save converted DOCX as",
            "pdf_output.docx"
        )

        if not output_file:
            return

        choice, ok = QInputDialog.getItem(
            self, "PDF to DOCX", "Choose conversion mode:",
            ["Preserve page appearance (page images)", "Editable layout (best effort)"], 0, False)
        if not ok:
            return
        mode = "appearance" if choice.startswith("Preserve") else "editable"

        def completed(result):
            result_path = result
            self.show_success(
                "PDF converted to DOCX successfully.",
                result_path
            )
        run_task(self, WordService.pdf_to_docx, input_file, output_file, mode=mode, on_success=completed)

    def handle_scanned_pdf_to_docx(self):
        input_file = self.select_pdf("Select scanned PDF file to convert to DOCX")
        if not input_file:
            return

        lang = self.ask_ocr_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        dpi = self.ask_dpi()
        if dpi is None:
            return

        output_file = self.select_output_docx(
            "Save OCR DOCX as",
            "scanned_pdf_ocr_output.docx"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success(
                "Scanned PDF converted to DOCX using OCR successfully.",
                result_path
            )
        run_task(self, WordService.scanned_pdf_to_docx_ocr, input_file, output_file, lang=lang, dpi=dpi, preprocess=preprocess, on_success=completed)
