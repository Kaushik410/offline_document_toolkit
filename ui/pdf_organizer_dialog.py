from utils.file_dialog_utils import normalize_output_selection
from utils.task_controller import run_task
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QAbstractItemView,
)

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon, QTransform

from services.pdf_service import PDFService
from services.ocr_service import OCRService
from utils.task_controller import cancel_tasks
from utils.file_dialog_utils import get_default_output_path


class PDFOrganizerDialog(QDialog):
    def __init__(self, input_file, parent=None):
        super().__init__(parent)

        self.input_file = input_file
        self.input_path = Path(input_file)

        self.page_count = PDFService.get_pdf_page_count(self.input_file)
        self.page_order = list(range(self.page_count))
        self.rotations = {}

        self.thumbnails = {}
        self.preview_cache = {}
        self.current_preview = None
        self.is_refreshing = False

        self.setWindowTitle("PDF Page Organizer")
        self.resize(1250, 780)

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self.header_label = QLabel(
            f"File: {self.input_path.name} | Total Pages: {self.page_count}"
        )
        self.header_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; padding: 6px;"
        )
        main_layout.addWidget(self.header_label)

        content_layout = QHBoxLayout()

        left_layout = QVBoxLayout()

        thumb_title = QLabel("Page Thumbnails")
        thumb_title.setAlignment(Qt.AlignCenter)
        thumb_title.setStyleSheet("font-weight: bold; font-size: 15px;")

        hint_label = QLabel("Tip: Drag thumbnails to reorder pages.")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("font-size: 12px; color: #6b7280;")

        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setIconSize(QSize(110, 150))
        self.thumbnail_list.setMinimumWidth(300)

        self.thumbnail_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.thumbnail_list.setDefaultDropAction(Qt.MoveAction)
        self.thumbnail_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.thumbnail_list.setMovement(QListWidget.Snap)
        self.thumbnail_list.setDragEnabled(True)
        self.thumbnail_list.setAcceptDrops(True)
        self.thumbnail_list.setDropIndicatorShown(True)

        self.thumbnail_list.currentRowChanged.connect(self.preview_selected_page)
        self.thumbnail_list.model().rowsMoved.connect(self.sync_order_after_drag_drop)

        left_layout.addWidget(thumb_title)
        left_layout.addWidget(hint_label)
        left_layout.addWidget(self.thumbnail_list)

        right_layout = QVBoxLayout()

        preview_title = QLabel("Page Preview")
        preview_title.setAlignment(Qt.AlignCenter)
        preview_title.setStyleSheet("font-weight: bold; font-size: 15px;")

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(720, 620)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 8px;
            }
        """)

        right_layout.addWidget(preview_title)
        right_layout.addWidget(self.preview_label)

        content_layout.addLayout(left_layout)
        content_layout.addLayout(right_layout, 1)

        main_layout.addLayout(content_layout)

        button_layout = QHBoxLayout()

        self.move_up_btn = QPushButton("Move Up")
        self.move_down_btn = QPushButton("Move Down")
        self.rotate_left_btn = QPushButton("Rotate Left")
        self.rotate_right_btn = QPushButton("Rotate Right")
        self.delete_btn = QPushButton("Delete Page")
        self.save_btn = QPushButton("Save Organized PDF")
        self.close_btn = QPushButton("Close")

        self.move_up_btn.clicked.connect(self.move_page_up)
        self.move_down_btn.clicked.connect(self.move_page_down)
        self.rotate_left_btn.clicked.connect(lambda: self.rotate_selected_page(-90))
        self.rotate_right_btn.clicked.connect(lambda: self.rotate_selected_page(90))
        self.delete_btn.clicked.connect(self.delete_selected_page)
        self.save_btn.clicked.connect(self.save_pdf)
        self.close_btn.clicked.connect(self.close)

        button_layout.addWidget(self.move_up_btn)
        button_layout.addWidget(self.move_down_btn)
        button_layout.addWidget(self.rotate_left_btn)
        button_layout.addWidget(self.rotate_right_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.close_btn)

        main_layout.addLayout(button_layout)

        run_task(self, PDFService.render_thumbnails, self.input_file,
                 on_success=self.set_thumbnails, task_title="Loading page thumbnails")

    def get_qtransform(self, angle):
        transform = QTransform()
        transform.rotate(angle)
        return transform

    def sync_order_after_drag_drop(self, *args):
        if self.is_refreshing:
            return

        new_order = []

        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            original_page_index = item.data(Qt.UserRole)

            if original_page_index is not None:
                new_order.append(original_page_index)

        if len(new_order) == len(self.page_order):
            self.page_order = new_order
            self.refresh_labels_only()

            current_row = self.thumbnail_list.currentRow()
            if current_row >= 0:
                self.preview_selected_page(current_row)

    def refresh_labels_only(self):
        for display_index in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(display_index)
            original_page_index = item.data(Qt.UserRole)

            rotation_angle = self.rotations.get(original_page_index, 0)

            label_text = f"Output {display_index + 1}: Page {original_page_index + 1}"

            if rotation_angle:
                label_text += f" | Rot {rotation_angle}°"

            item.setText(label_text)

    def set_thumbnails(self, data):
        for index, image in enumerate(data):
            pixmap = QPixmap()
            pixmap.loadFromData(image)
            self.thumbnails[index] = pixmap
        self.load_thumbnails()
        if self.page_order:
            self.thumbnail_list.setCurrentRow(0)

    def load_thumbnails(self):
        self.is_refreshing = True
        self.thumbnail_list.clear()
        for index in self.page_order:
            pixmap = self.thumbnails.get(index, QPixmap())
            angle = self.rotations.get(index, 0)
            if angle:
                pixmap = pixmap.transformed(self.get_qtransform(angle), Qt.SmoothTransformation)
            item = QListWidgetItem(QIcon(pixmap), "")
            item.setData(Qt.UserRole, index)
            self.thumbnail_list.addItem(item)
        self.refresh_labels_only()
        self.is_refreshing = False

    def get_selected_row(self):
        row = self.thumbnail_list.currentRow()

        if row < 0 or row >= len(self.page_order):
            return None

        return row

    def preview_selected_page(self, row):
        if self.is_refreshing or not 0 <= row < len(self.page_order):
            return
        item = self.thumbnail_list.item(row)
        if item is None:
            return
        index = item.data(Qt.UserRole)
        def display(data):
            # Limit the high resolution cache; thumbnails are retained separately.
            if len(self.preview_cache) >= 8:
                self.preview_cache.pop(next(iter(self.preview_cache)))
            self.preview_cache[index] = data
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            angle = self.rotations.get(index, 0)
            if angle:
                pixmap = pixmap.transformed(self.get_qtransform(angle), Qt.SmoothTransformation)
            self.current_preview = pixmap
            self.scale_preview()
        if index in self.preview_cache:
            display(self.preview_cache[index])
        else:
            run_task(self, OCRService.render_page_bytes, self.input_file, index,
                     on_success=display, task_title="Loading page preview")

    def scale_preview(self):
        if self.current_preview is not None:
            self.preview_label.setPixmap(self.current_preview.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh_after_order_change(self, selected_row):
        self.load_thumbnails()

        if self.page_order:
            selected_row = max(0, min(selected_row, len(self.page_order) - 1))
            self.thumbnail_list.setCurrentRow(selected_row)
        else:
            self.preview_label.clear()

    def move_page_up(self):
        row = self.get_selected_row()

        if row is None or row == 0:
            return

        self.page_order[row - 1], self.page_order[row] = (
            self.page_order[row],
            self.page_order[row - 1],
        )

        self.refresh_after_order_change(row - 1)

    def move_page_down(self):
        row = self.get_selected_row()

        if row is None or row == len(self.page_order) - 1:
            return

        self.page_order[row + 1], self.page_order[row] = (
            self.page_order[row],
            self.page_order[row + 1],
        )

        self.refresh_after_order_change(row + 1)

    def rotate_selected_page(self, angle):
        row = self.get_selected_row()

        if row is None:
            return

        item = self.thumbnail_list.item(row)

        if item is None:
            return

        original_page_index = item.data(Qt.UserRole)

        current_angle = self.rotations.get(original_page_index, 0)
        new_angle = (current_angle + angle) % 360

        if new_angle == 0:
            self.rotations.pop(original_page_index, None)
        else:
            self.rotations[original_page_index] = new_angle

        self.refresh_after_order_change(row)

    def delete_selected_page(self):
        row = self.get_selected_row()

        if row is None:
            return

        if len(self.page_order) == 1:
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "At least one page must remain in the PDF."
            )
            return

        item = self.thumbnail_list.item(row)

        if item is None:
            return

        original_page_index = item.data(Qt.UserRole)

        confirm = QMessageBox.question(
            self,
            "Delete Page",
            f"Delete original page {original_page_index + 1} from output PDF?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        self.page_order.pop(row)
        self.rotations.pop(original_page_index, None)

        self.refresh_after_order_change(row)

    def save_pdf(self):
        self.sync_order_after_drag_drop()

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save organized PDF as",
            get_default_output_path("organized_output.pdf"),
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
                f"Organized PDF saved successfully.\n\nSaved at:\n{result_path}"
            )
        run_task(self, PDFService.save_organized_pdf, self.input_file, output_file, self.page_order, rotations=self.rotations, on_success=completed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_label"):
            self.scale_preview()

    def closeEvent(self, event):
        cancel_tasks(self)
        event.accept()
