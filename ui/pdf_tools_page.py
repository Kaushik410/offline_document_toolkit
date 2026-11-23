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
    QLineEdit,
)

from services.pdf_service import PDFService
from utils.file_dialog_utils import get_default_output_folder, get_default_output_path
from ui.pdf_organizer_dialog import PDFOrganizerDialog


class PDFToolsPage(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        self.setLayout(layout)

        title = QLabel("PDF Tools")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(16)

        tools = [
            "Merge PDFs",
            "Split PDF",
            "Extract Pages",
            "Delete Pages",
            "Rotate Pages",
            "PDF Page Organizer",
            "Compress PDF",
            "PDF to Images",
            "Images to PDF",
            "Add Watermark",
            "Add Page Numbers",
            "Protect PDF",
            "Unlock PDF",
        ]

        self.tool_buttons = {}

        for i, tool in enumerate(tools):
            button = self.create_tool_button(tool)
            self.tool_buttons[tool] = button
            grid.addWidget(button, i // 3, i % 3)

        layout.addLayout(grid)
        layout.addStretch()

        self.tool_buttons["Merge PDFs"].clicked.connect(self.handle_merge_pdfs)
        self.tool_buttons["Extract Pages"].clicked.connect(self.handle_extract_pages)
        self.tool_buttons["Delete Pages"].clicked.connect(self.handle_delete_pages)
        self.tool_buttons["Rotate Pages"].clicked.connect(self.handle_rotate_pages)
        self.tool_buttons["PDF Page Organizer"].clicked.connect(
            self.handle_pdf_page_organizer
        )
        self.tool_buttons["Split PDF"].clicked.connect(self.handle_split_pdf)
        self.tool_buttons["PDF to Images"].clicked.connect(self.handle_pdf_to_images)
        self.tool_buttons["Images to PDF"].clicked.connect(self.handle_images_to_pdf)
        self.tool_buttons["Compress PDF"].clicked.connect(self.handle_compress_pdf)
        self.tool_buttons["Protect PDF"].clicked.connect(self.handle_protect_pdf)
        self.tool_buttons["Unlock PDF"].clicked.connect(self.handle_unlock_pdf)
        self.tool_buttons["Add Watermark"].clicked.connect(self.handle_add_watermark)
        self.tool_buttons["Add Page Numbers"].clicked.connect(
            self.handle_add_page_numbers
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
                border: 1px solid #2563eb;
                background-color: #eff6ff;
            }
        """)
        return button

    def select_single_pdf(self, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "PDF Files (*.pdf)"
        )
        return file_path

    def select_output_pdf(self, title, default_name):
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            title,
            get_default_output_path(default_name),
            "PDF Files (*.pdf)"
        )

        return normalize_output_selection(self, output_file, ".pdf", append=True)

    def select_output_folder(self, title):
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            get_default_output_folder()
        )
        return folder

    def ask_page_range(self, title):
        page_range, ok = QInputDialog.getText(
            self,
            title,
            "Enter page numbers/ranges, e.g. 1,3,5-8:"
        )

        if not ok:
            return None

        return page_range.strip()

    def handle_pdf_page_organizer(self):
        input_file = self.select_single_pdf("Select PDF to organize")
        if not input_file:
            return

        try:
            dialog = PDFOrganizerDialog(
                input_file=input_file,
                parent=self
            )
            dialog.exec()

        except Exception as e:
            self.show_error("Failed to open PDF Page Organizer.", e)

    def handle_merge_pdfs(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF files to merge",
            "",
            "PDF Files (*.pdf)"
        )

        if not input_files:
            return

        output_file = self.select_output_pdf(
            "Save merged PDF as",
            "merged_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("PDF files merged successfully.", result_path)
        run_task(self, PDFService.merge_pdfs, input_files, output_file, on_success=completed)

    def handle_extract_pages(self):
        input_file = self.select_single_pdf("Select PDF to extract pages from")
        if not input_file:
            return

        page_range = self.ask_page_range("Extract Pages")
        if not page_range:
            return

        output_file = self.select_output_pdf(
            "Save extracted pages as",
            "extracted_pages.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Pages extracted successfully.", result_path)
        run_task(self, PDFService.extract_pages, input_file, page_range, output_file, on_success=completed)

    def handle_delete_pages(self):
        input_file = self.select_single_pdf("Select PDF to delete pages from")
        if not input_file:
            return

        page_range = self.ask_page_range("Delete Pages")
        if not page_range:
            return

        output_file = self.select_output_pdf(
            "Save PDF after deleting pages as",
            "deleted_pages_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Pages deleted successfully.", result_path)
        run_task(self, PDFService.delete_pages, input_file, page_range, output_file, on_success=completed)

    def handle_rotate_pages(self):
        input_file = self.select_single_pdf("Select PDF to rotate pages")
        if not input_file:
            return

        page_range = self.ask_page_range("Rotate Pages")
        if not page_range:
            return

        angle, ok = QInputDialog.getItem(
            self,
            "Rotation Angle",
            "Select rotation angle:",
            ["90", "180", "270"],
            0,
            False
        )

        if not ok:
            return

        output_file = self.select_output_pdf(
            "Save rotated PDF as",
            "rotated_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Pages rotated successfully.", result_path)
        run_task(self, PDFService.rotate_pages, input_file, page_range, int(angle), output_file, on_success=completed)

    def handle_split_pdf(self):
        input_file = self.select_single_pdf("Select PDF to split")
        if not input_file:
            return

        output_folder = self.select_output_folder("Select folder to save split PDFs")
        if not output_folder:
            return

        def completed(result):
            output_files = result
            QMessageBox.information(
                self,
                "Success",
                f"PDF split successfully.\n\n"
                f"Total files created: {len(output_files)}\n\n"
                f"Saved in:\n{output_folder}"
            )
        run_task(self, PDFService.split_pdf, input_file, output_folder, on_success=completed)

    def handle_pdf_to_images(self):
        input_file = self.select_single_pdf("Select PDF to convert into images")
        if not input_file:
            return

        output_folder = self.select_output_folder("Select folder to save images")
        if not output_folder:
            return

        image_format, ok = QInputDialog.getItem(
            self,
            "Image Format",
            "Select output image format:",
            ["png", "jpg"],
            0,
            False
        )

        if not ok:
            return

        dpi, ok = QInputDialog.getInt(
            self,
            "Image DPI",
            "Enter DPI value:",
            200,
            72,
            600,
            10
        )

        if not ok:
            return

        def completed(result):
            output_files = result
            QMessageBox.information(
                self,
                "Success",
                f"PDF converted to images successfully.\n\n"
                f"Total images created: {len(output_files)}\n\n"
                f"Saved in:\n{output_folder}"
            )
        run_task(self, PDFService.pdf_to_images, input_file, output_folder, image_format=image_format, dpi=dpi, on_success=completed)

    def handle_images_to_pdf(self):
        input_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select images to convert into PDF",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp)"
        )

        if not input_files:
            return

        output_file = self.select_output_pdf(
            "Save image PDF as",
            "images_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Images converted to PDF successfully.", result_path)
        run_task(self, PDFService.images_to_pdf, input_files, output_file, on_success=completed)

    def handle_compress_pdf(self):
        input_file = self.select_single_pdf("Select PDF to compress")
        if not input_file:
            return

        quality, ok = QInputDialog.getItem(
            self,
            "Compression Quality",
            "Select compression level:",
            [
                "ebook - recommended",
                "screen - maximum compression",
                "printer - better quality",
                "prepress - highest quality"
            ],
            0,
            False
        )

        if not ok:
            return

        quality_key = quality.split(" - ")[0]

        output_file = self.select_output_pdf(
            "Save compressed PDF as",
            "compressed_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            (result_path, original_size, compressed_size) = result
            saved_bytes = original_size - compressed_size

            if original_size > 0:
                reduction_percent = (saved_bytes / original_size) * 100
            else:
                reduction_percent = 0

            QMessageBox.information(
                self,
                "Success",
                f"PDF compressed successfully.\n\n"
                f"Original size: {original_size / 1024:.2f} KB\n"
                f"Compressed size: {compressed_size / 1024:.2f} KB\n"
                f"Reduction: {reduction_percent:.2f}%\n\n"
                f"Saved at:\n{result_path}"
            )
        run_task(self, PDFService.compress_pdf, input_file, output_file, quality=quality_key, on_success=completed)

    def handle_protect_pdf(self):
        input_file = self.select_single_pdf("Select PDF to protect")
        if not input_file:
            return

        password, ok = QInputDialog.getText(
            self,
            "Protect PDF",
            "Enter password:"
        )

        if not ok or not password:
            return

        output_file = self.select_output_pdf(
            "Save protected PDF as",
            "protected_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("PDF protected successfully.", result_path)
        run_task(self, PDFService.protect_pdf, input_file, output_file, password, on_success=completed)

    def handle_unlock_pdf(self):
        input_file = self.select_single_pdf("Select PDF to unlock")
        if not input_file:
            return

        password, ok = QInputDialog.getText(
            self,
            "Unlock PDF",
            "Enter password:"
        )

        if not ok or not password:
            return

        output_file = self.select_output_pdf(
            "Save unlocked PDF as",
            "unlocked_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("PDF unlocked successfully.", result_path)
        run_task(self, PDFService.unlock_pdf, input_file, output_file, password, on_success=completed)

    def handle_add_watermark(self):
        input_file = self.select_single_pdf("Select PDF to add watermark")
        if not input_file:
            return

        watermark_text, ok = QInputDialog.getText(
            self,
            "Add Watermark",
            "Enter watermark text:"
        )

        if not ok or not watermark_text.strip():
            return

        watermark_style, ok = QInputDialog.getItem(
            self,
            "Watermark Style",
            "Select watermark style:",
            [
                "horizontal",
                "diagonal",
            ],
            1,
            False
        )

        if not ok:
            return

        output_file = self.select_output_pdf(
            "Save watermarked PDF as",
            "watermarked_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Watermark added successfully.", result_path)
        run_task(self, PDFService.add_watermark, input_file, output_file, watermark_text, watermark_style=watermark_style, on_success=completed)

    def handle_add_page_numbers(self):
        input_file = self.select_single_pdf("Select PDF to add page numbers")
        if not input_file:
            return

        position_text, ok = QInputDialog.getItem(
            self,
            "Page Number Position",
            "Select position:",
            [
                "bottom-center",
                "bottom-right",
                "bottom-left",
            ],
            0,
            False
        )

        if not ok:
            return

        output_file = self.select_output_pdf(
            "Save numbered PDF as",
            "page_numbered_output.pdf"
        )

        if not output_file:
            return

        def completed(result):
            result_path = result
            self.show_success("Page numbers added successfully.", result_path)
        run_task(self, PDFService.add_page_numbers, input_file, output_file, position=position_text, on_success=completed)

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