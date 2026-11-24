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
    QTextEdit,
    QDialog,
    QHBoxLayout,
)

from services.ocr_service import OCRService 
from utils.file_dialog_utils import get_default_output_path
from ui.ocr_preview_dialog import OCRPagePreviewDialog


class OCRResultDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)

        self.text = text

        self.setWindowTitle("OCR Result")
        self.resize(900, 650)

        layout = QVBoxLayout()
        self.setLayout(layout)

        title = QLabel("Extracted Text")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        self.text_box = QTextEdit()
        self.text_box.setPlainText(text)
        layout.addWidget(self.text_box)

        button_layout = QHBoxLayout()

        self.save_txt_btn = QPushButton("Save as TXT")
        self.save_docx_btn = QPushButton("Save as DOCX")
        self.close_btn = QPushButton("Close")

        self.save_txt_btn.clicked.connect(self.save_as_txt)
        self.save_docx_btn.clicked.connect(self.save_as_docx)
        self.close_btn.clicked.connect(self.close)

        button_layout.addStretch()
        button_layout.addWidget(self.save_txt_btn)
        button_layout.addWidget(self.save_docx_btn)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def save_as_txt(self):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save OCR text as TXT",
            get_default_output_path("ocr_output.txt"),
            "Text Files (*.txt)"
        )
        output_file = normalize_output_selection(self, output_file, ".txt")

        if not output_file:
            return

        def completed(result_path):
            QMessageBox.information(self, "Success", f"OCR text saved successfully.\n\nSaved at:\n{result_path}")
        run_task(self, OCRService.save_text_as_txt, self.text_box.toPlainText(), output_file,
                 on_success=completed)


    def save_as_docx(self):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save OCR text as DOCX",
            get_default_output_path("ocr_output.docx"),
            "Word Files (*.docx)"
        )
        output_file = normalize_output_selection(self, output_file, ".docx")

        if not output_file:
            return

        def completed(result_path):
            QMessageBox.information(self, "Success", f"OCR text saved successfully.\n\nSaved at:\n{result_path}")
        run_task(self, OCRService.save_text_as_docx, self.text_box.toPlainText(), output_file,
                 on_success=completed)



class OCRToolsPage(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        self.setLayout(layout)

        title = QLabel("OCR Tools")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Extract text from images and scanned PDFs completely offline using Tesseract OCR."
        )
        subtitle.setStyleSheet("font-size: 15px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(16)

        tools = [
            "Image to Text",
            "Scanned PDF to Text",
            "PDF OCR Page-wise Preview",
            "Scanned PDF to Searchable PDF",
            "Export OCR as TXT",
            "Export OCR as DOCX",
            "Improve Scanned Document",
        ]

        self.tool_buttons = {}

        for i, tool in enumerate(tools):
            button = self.create_tool_button(tool)
            self.tool_buttons[tool] = button
            grid.addWidget(button, i // 3, i % 3)

        layout.addLayout(grid)
        smart_button = QPushButton("Smart OCR: orientation, deskew, and confidence review…")
        smart_button.clicked.connect(self.smart_ocr)
        layout.addWidget(smart_button)
        layout.addStretch()

        self.tool_buttons["Image to Text"].clicked.connect(self.handle_image_to_text)
        self.tool_buttons["Scanned PDF to Text"].clicked.connect(self.handle_pdf_to_text)
        self.tool_buttons["Scanned PDF to Searchable PDF"].clicked.connect(
            self.handle_pdf_to_searchable_pdf
        )
        self.tool_buttons["Improve Scanned Document"].clicked.connect(
            self.handle_improve_scanned_document
        )

        self.tool_buttons["Export OCR as TXT"].clicked.connect(
            lambda: self.show_info(
                "Export OCR as TXT",
                "Use Image to Text or Scanned PDF to Text first. The result window has a Save as TXT button."
            )
        )

        self.tool_buttons["Export OCR as DOCX"].clicked.connect(
            lambda: self.show_info(
                "Export OCR as DOCX",
                "Use Image to Text or Scanned PDF to Text first. The result window has a Save as DOCX button."
            )
        )

        self.tool_buttons["PDF OCR Page-wise Preview"].clicked.connect(
            self.handle_pdf_ocr_pagewise_preview
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
                border: 1px solid #9333ea;
                background-color: #faf5ff;
            }
        """)
        return button

    def ask_language(self):
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
            "Enter DPI for rendering PDF pages:",
            200,
            100,
            400,
            50
        )

        if not ok:
            return None

        return dpi

    def handle_image_to_text(self):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select image for OCR",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_file:
            return

        lang = self.ask_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        def completed(result):
            text = result
            if not text:
                text = "[No text detected]"

            dialog = OCRResultDialog(text, parent=self)
            dialog.exec()
        run_task(self, OCRService.image_to_text, input_file, lang=lang, preprocess=preprocess, on_success=completed)

    def handle_pdf_to_text(self):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select scanned PDF for OCR",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_file:
            return

        lang = self.ask_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        dpi = self.ask_dpi()
        if dpi is None:
            return

        def completed(result):
            text = result
            if not text:
                text = "[No text detected]"

            dialog = OCRResultDialog(text, parent=self)
            dialog.exec()
        run_task(self, OCRService.pdf_to_text, input_file, lang=lang, dpi=dpi, preprocess=preprocess, on_success=completed)

    def handle_pdf_to_searchable_pdf(self):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select scanned PDF",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_file:
            return

        lang = self.ask_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        dpi = self.ask_dpi()
        if dpi is None:
            return

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save searchable PDF as",
            get_default_output_path("searchable_output.pdf"),
            "PDF Files (*.pdf)"
        )
        output_file = normalize_output_selection(self, output_file, ".pdf")

        if not output_file:
            return

        def completed(result):
            result_path = result
            QMessageBox.information(
                self,
                "Success",
                f"Searchable PDF created successfully.\n\nSaved at:\n{result_path}"
            )
        run_task(self, OCRService.pdf_to_searchable_pdf, input_file, output_file, lang=lang, dpi=dpi, preprocess=preprocess, on_success=completed)

    def handle_improve_scanned_document(self):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select scanned image to improve",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_file:
            return

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save improved scanned image as",
            get_default_output_path("improved_scan.png"),
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )
        output_file = normalize_output_selection(self, output_file, ".png")

        if not output_file:
            return

        def completed(result):
            result_path = result
            QMessageBox.information(
                self,
                "Success",
                f"Scanned document improved successfully.\n\nSaved at:\n{result_path}"
            )
        run_task(self, OCRService.preprocess_image_for_ocr, input_file, output_file, on_success=completed)

    def show_info(self, title, message):
        QMessageBox.information(
            self,
            title,
            message
        )

    def show_error(self, message, error):
        QMessageBox.critical(
            self,
            "Error",
            f"{message}\n\nReason:\n{str(error)}"
        )

    def handle_pdf_ocr_pagewise_preview(self):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select scanned PDF for page-wise OCR preview",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_file:
            return

        lang = self.ask_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        dpi = self.ask_dpi()
        if dpi is None:
            return

        try:
            dialog = OCRPagePreviewDialog(
                input_file=input_file,
                lang=lang,
                dpi=dpi,
                preprocess=preprocess,
                parent=self
            )
            dialog.exec()

        except Exception as e:
            self.show_error("Failed to open page-wise OCR preview.", e)
    def smart_ocr(self):
        from pathlib import Path
        import uuid
        from services.ocr_pipeline import analyze_pdf, apply_review
        from services.workspace_store import data_directory
        from ui.ocr_review_dialog import OCRReviewDialog
        input_file, _ = QFileDialog.getOpenFileName(self, "Select PDF for smart OCR", "", "PDF files (*.pdf)")
        if not input_file:
            return
        language = self.ask_language()
        if not language:
            return
        directory = data_directory() / "ocr-reviews" / uuid.uuid4().hex
        def analyzed(result):
            dialog = OCRReviewDialog(directory / "review.json", self)
            if dialog.exec() != dialog.Accepted:
                return
            output, _ = QFileDialog.getSaveFileName(self, "Save reviewed searchable PDF", get_default_output_path("reviewed.pdf"), "PDF files (*.pdf)")
            output = normalize_output_selection(self, output, ".pdf")
            if output:
                run_task(self, apply_review, input_file, output, dialog.review,
                         on_success=lambda path: QMessageBox.information(self, "OCR complete", "Reviewed text saved in the searchable PDF."))
        run_task(self, analyze_pdf, input_file, str(directory), lang=language,
                 on_success=analyzed, task_title="Smart OCR")
