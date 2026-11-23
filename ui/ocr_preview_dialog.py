from utils.file_dialog_utils import normalize_output_selection
from utils.task_controller import run_task
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QProgressDialog,
    QSizePolicy,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from services.ocr_service import OCRService
from utils.file_dialog_utils import get_default_output_path
from utils.task_controller import cancel_tasks


class OCRPagePreviewDialog(QDialog):
    def __init__(self, input_file, lang="eng", dpi=200, preprocess=True, parent=None):
        super().__init__(parent)

        self.input_file = input_file
        self.input_path = Path(input_file)
        self.lang = lang
        self.dpi = dpi
        self.preprocess = preprocess

        self.page_count = OCRService.get_pdf_page_count(self.input_file)
        self.current_page_index = 0
        self.page_texts = [""] * self.page_count


        self.current_page_image = None

        self.setWindowTitle("OCR Page-wise Preview")
        self.resize(1250, 780)

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.header_label = QLabel()
        self.header_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; padding: 6px;"
        )
        self.main_layout.addWidget(self.header_label)

        content_layout = QHBoxLayout()

        left_layout = QVBoxLayout()

        preview_title = QLabel("Page Preview")
        preview_title.setAlignment(Qt.AlignCenter)
        preview_title.setStyleSheet("font-weight: bold; font-size: 15px;")

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(520, 620)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 8px;
            }
        """)

        left_layout.addWidget(preview_title)
        left_layout.addWidget(self.preview_label)

        right_layout = QVBoxLayout()

        text_title = QLabel("Editable OCR Text")
        text_title.setAlignment(Qt.AlignCenter)
        text_title.setStyleSheet("font-weight: bold; font-size: 15px;")

        self.text_box = QTextEdit()
        self.text_box.setPlaceholderText("OCR text for this page will appear here...")
        self.text_box.textChanged.connect(self.save_current_text_from_box)

        right_layout.addWidget(text_title)
        right_layout.addWidget(self.text_box)

        content_layout.addLayout(left_layout, 1)
        content_layout.addLayout(right_layout, 1)

        self.main_layout.addLayout(content_layout)

        nav_layout = QHBoxLayout()

        self.prev_btn = QPushButton("Previous Page")
        self.next_btn = QPushButton("Next Page")
        self.ocr_current_btn = QPushButton("Run OCR Current Page")
        self.ocr_all_btn = QPushButton("Run OCR All Pages")
        self.save_txt_btn = QPushButton("Save TXT")
        self.save_docx_btn = QPushButton("Save DOCX")
        self.close_btn = QPushButton("Close")

        self.prev_btn.clicked.connect(self.previous_page)
        self.next_btn.clicked.connect(self.next_page)
        self.ocr_current_btn.clicked.connect(self.run_ocr_current_page)
        self.ocr_all_btn.clicked.connect(self.run_ocr_all_pages)
        self.save_txt_btn.clicked.connect(self.save_as_txt)
        self.save_docx_btn.clicked.connect(self.save_as_docx)
        self.close_btn.clicked.connect(self.close)

        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.ocr_current_btn)
        nav_layout.addWidget(self.ocr_all_btn)
        nav_layout.addWidget(self.save_txt_btn)
        nav_layout.addWidget(self.save_docx_btn)
        nav_layout.addWidget(self.close_btn)

        self.main_layout.addLayout(nav_layout)

        self.load_current_page()

    def update_header(self):
        self.header_label.setText(
            f"File: {self.input_path.name} | Page {self.current_page_index + 1} of {self.page_count}"
        )

    def save_current_text_from_box(self):
        if 0 <= self.current_page_index < self.page_count:
            self.page_texts[self.current_page_index] = self.text_box.toPlainText()

    def load_current_page(self):
        self.update_header()
        self.text_box.blockSignals(True)
        self.text_box.setPlainText(self.page_texts[self.current_page_index])
        self.text_box.blockSignals(False)
        self.prev_btn.setEnabled(self.current_page_index > 0)
        self.next_btn.setEnabled(self.current_page_index < self.page_count - 1)
        run_task(self, OCRService.render_page_bytes, self.input_file, self.current_page_index,
                 on_success=self.set_page_preview, task_title="Loading page")

    def set_page_preview(self, data):
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.current_page_image = pixmap
        self.scale_preview()

    def scale_preview(self):
        if self.current_page_image is not None:
            self.preview_label.setPixmap(self.current_page_image.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_label"):
            self.scale_preview()

    def previous_page(self):
        self.save_current_text_from_box()

        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.load_current_page()

    def next_page(self):
        self.save_current_text_from_box()

        if self.current_page_index < self.page_count - 1:
            self.current_page_index += 1
            self.load_current_page()

    def run_ocr_current_page(self):
        index = self.current_page_index
        def completed(text):
            self.page_texts[index] = text
            if self.current_page_index == index:
                self.text_box.setPlainText(text)
        run_task(self, OCRService.ocr_pdf_page, self.input_file, index,
                 lang=self.lang, dpi=self.dpi, preprocess=self.preprocess,
                 on_success=completed, task_title="Reading current page")

    def run_ocr_all_pages(self):
        self.save_current_text_from_box()
        def completed(texts):
            self.page_texts = texts
            self.text_box.setPlainText(texts[self.current_page_index])
            QMessageBox.information(self, "OCR Complete", "OCR completed for all pages.")
        run_task(self, OCRService.ocr_pages, self.input_file, lang=self.lang,
                 dpi=self.dpi, preprocess=self.preprocess,
                 on_success=completed, task_title="Reading all pages")

    def get_combined_text(self):
        self.save_current_text_from_box()

        parts = []

        for index, text in enumerate(self.page_texts, start=1):
            parts.append(f"--- Page {index} ---")
            parts.append(text.strip())
            parts.append("")

        return "\n".join(parts).strip()

    def save_as_txt(self):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save OCR text as TXT",
            get_default_output_path("ocr_pagewise_output.txt"),
            "Text Files (*.txt)"
        )
        output_file = normalize_output_selection(self, output_file, ".txt")

        if not output_file:
            return

        def completed(result):
            result_path = result
            QMessageBox.information(
                self,
                "Success",
                f"OCR text saved successfully.\n\nSaved at:\n{result_path}"
            )
        run_task(self, OCRService.save_text_as_txt, self.get_combined_text(), output_file, on_success=completed)

    def save_as_docx(self):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save OCR text as DOCX",
            get_default_output_path("ocr_pagewise_output.docx"),
            "Word Files (*.docx)"
        )
        output_file = normalize_output_selection(self, output_file, ".docx")

        if not output_file:
            return

        def completed(result):
            result_path = result
            QMessageBox.information(
                self,
                "Success",
                f"OCR text saved successfully.\n\nSaved at:\n{result_path}"
            )
        run_task(self, OCRService.save_text_as_docx, self.get_combined_text(), output_file, on_success=completed)

    def closeEvent(self, event):
        cancel_tasks(self)
        event.accept()
