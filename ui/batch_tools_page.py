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
    QProgressDialog,
)

from PySide6.QtCore import Qt

from services.batch_service import BatchService
from utils.file_dialog_utils import get_default_output_folder


class BatchResultDialog(QDialog):
    def __init__(self, title, results, errors, parent=None):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resize(900, 650)

        layout = QVBoxLayout()
        self.setLayout(layout)

        header = QLabel(title)
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(header)

        self.text_box = QTextEdit()
        self.text_box.setReadOnly(True)

        report = self.build_report(results, errors)
        self.text_box.setPlainText(report)

        layout.addWidget(self.text_box)

        button_layout = QHBoxLayout()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        button_layout.addStretch()
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def build_report(self, results, errors):
        lines = []

        lines.append(f"Successful files: {len(results)}")
        lines.append(f"Failed files: {len(errors)}")
        lines.append("")

        if results:
            lines.append("SUCCESS:")
            lines.append("-" * 60)

            for item in results:
                lines.append(f"Input : {item.get('input')}")
                lines.append(f"Output: {item.get('output')}")

                if "original_size" in item and "new_size" in item:
                    original = item["original_size"]
                    new = item["new_size"]

                    saved = original - new
                    reduction = (saved / original) * 100 if original > 0 else 0

                    lines.append(f"Original size: {original / 1024:.2f} KB")
                    lines.append(f"New size     : {new / 1024:.2f} KB")
                    lines.append(f"Reduction    : {reduction:.2f}%")

                lines.append("")

        if errors:
            lines.append("")
            lines.append("ERRORS:")
            lines.append("-" * 60)

            for item in errors:
                lines.append(f"Input: {item.get('input')}")
                lines.append(f"Error: {item.get('error')}")
                lines.append("")

        return "\n".join(lines)


class BatchToolsPage(QWidget):
    def __init__(self):
        super().__init__()


        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        self.setLayout(layout)

        title = QLabel("Batch Tools")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Process multiple PDFs, images, OCR files, and DOCX documents together."
        )
        subtitle.setStyleSheet("font-size: 15px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(16)

        tools = [
            "Batch Compress PDFs",
            "Batch Compress Images",
            "Batch Convert Images",
            "Batch OCR Images to TXT",
            "Batch Scanned PDFs to Searchable PDFs",
            "Batch DOCX to PDF",
        ]

        self.tool_buttons = {}

        for i, tool in enumerate(tools):
            button = self.create_tool_button(tool)
            self.tool_buttons[tool] = button
            grid.addWidget(button, i // 3, i % 3)

        layout.addLayout(grid)
        layout.addStretch()

        self.tool_buttons["Batch Compress PDFs"].clicked.connect(
            self.handle_batch_compress_pdfs
        )
        self.tool_buttons["Batch Compress Images"].clicked.connect(
            self.handle_batch_compress_images
        )
        self.tool_buttons["Batch Convert Images"].clicked.connect(
            self.handle_batch_convert_images
        )
        self.tool_buttons["Batch OCR Images to TXT"].clicked.connect(
            self.handle_batch_ocr_images_to_txt
        )
        self.tool_buttons["Batch Scanned PDFs to Searchable PDFs"].clicked.connect(
            self.handle_batch_scanned_pdfs_to_searchable_pdfs
        )
        self.tool_buttons["Batch DOCX to PDF"].clicked.connect(
            self.handle_batch_docx_to_pdf
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
                border: 1px solid #0891b2;
                background-color: #ecfeff;
            }
        """)
        return button

    def select_output_folder(self, title):
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            get_default_output_folder()
        )
        return folder

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

    def handle_batch_compress_pdfs(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF files to compress",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_files:
            return

        quality, ok = QInputDialog.getItem(
            self,
            "Compression Quality",
            "Select compression level:",
            [
                "ebook - recommended",
                "screen - maximum compression",
                "printer - better quality",
                "prepress - highest quality",
            ],
            0,
            False
        )

        if not ok:
            return

        quality_key = quality.split(" - ")[0]

        output_folder = self.select_output_folder(
            "Select output folder for compressed PDFs"
        )

        if not output_folder:
            return

        def completed(result):
            (results, errors) = result
            self.show_batch_results(
                "Batch Compress PDFs Result",
                results,
                errors
            )
        run_task(self, BatchService.batch_compress_pdfs, input_files, output_folder, quality=quality_key, on_success=completed)

    def handle_batch_compress_images(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select images to compress",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_files:
            return

        quality, ok = QInputDialog.getInt(
            self,
            "Image Quality",
            "Enter image quality percentage:",
            70,
            1,
            100,
            5
        )

        if not ok:
            return

        output_folder = self.select_output_folder(
            "Select output folder for compressed images"
        )

        if not output_folder:
            return

        def completed(result):
            (results, errors) = result
            self.show_batch_results(
                "Batch Compress Images Result",
                results,
                errors
            )
        run_task(self, BatchService.batch_compress_images, input_files, output_folder, quality=quality, on_success=completed)

    def handle_batch_convert_images(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select images to convert",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_files:
            return

        output_format, ok = QInputDialog.getItem(
            self,
            "Output Format",
            "Select output image format:",
            ["png", "jpg", "webp", "bmp"],
            0,
            False
        )

        if not ok:
            return

        output_folder = self.select_output_folder(
            "Select output folder for converted images"
        )

        if not output_folder:
            return

        def completed(result):
            (results, errors) = result
            self.show_batch_results(
                "Batch Convert Images Result",
                results,
                errors
            )
        run_task(self, BatchService.batch_convert_images, input_files, output_folder, output_format=output_format, on_success=completed)

    def handle_batch_ocr_images_to_txt(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select images for batch OCR",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_files:
            return

        lang = self.ask_ocr_language()
        if lang is None:
            return

        preprocess = self.ask_preprocess()
        if preprocess is None:
            return

        output_folder = self.select_output_folder(
            "Select output folder for OCR TXT files"
        )

        if not output_folder:
            return

        def completed(result):
            (results, errors) = result
            self.show_batch_results(
                "Batch OCR Images to TXT Result",
                results,
                errors
            )
        run_task(self, BatchService.batch_ocr_images_to_txt, input_files, output_folder, lang=lang, preprocess=preprocess, on_success=completed)

    def handle_batch_scanned_pdfs_to_searchable_pdfs(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select scanned PDFs",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_files:
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

        output_folder = self.select_output_folder(
            "Select output folder for searchable PDFs"
        )

        if not output_folder:
            return

        def completed(result):
            self.show_batch_results("Batch Searchable PDF Results", *result)
        run_task(self, BatchService.batch_scanned_pdfs_to_searchable_pdfs,
                 input_files, output_folder, lang=lang, dpi=dpi, preprocess=preprocess,
                 on_success=completed)

    def handle_batch_docx_to_pdf(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select DOCX files to convert to PDF",
            "",
            "Word Files (*.docx)"
        )

        if not input_files:
            return

        output_folder = self.select_output_folder(
            "Select output folder for PDF files"
        )

        if not output_folder:
            return

        def completed(result):
            (results, errors) = result
            self.show_batch_results(
                "Batch DOCX to PDF Result",
                results,
                errors
            )
        run_task(self, BatchService.batch_docx_to_pdf, input_files, output_folder, on_success=completed)

    def show_batch_results(self, title, results, errors):
        dialog = BatchResultDialog(
            title,
            results,
            errors,
            parent=self
        )
        dialog.exec()

    def show_error(self, message, error):
        QMessageBox.critical(
            self,
            "Error",
            f"{message}\n\nReason:\n{str(error)}"
        )