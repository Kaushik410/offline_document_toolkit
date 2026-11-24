from pathlib import Path
import os

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QSlider,
    QLineEdit,
    QGroupBox,
    QFormLayout,
    QSizePolicy,
    QRubberBand,
)
from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QPixmap, QMouseEvent

from PIL.ImageQt import ImageQt
from services.image_service import ImageService
from utils.task_controller import run_task, cancel_tasks
from utils.file_dialog_utils import get_default_output_path, confirm_normalized_output


class ImageCanvas(QLabel):
    def __init__(self, allow_selection=False, allow_click=False, parent_dialog=None):
        super().__init__()

        self.allow_selection = allow_selection
        self.allow_click = allow_click
        self.parent_dialog = parent_dialog

        self.original_image_size = None
        self.display_pixmap = None

        self.rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self.origin = QPoint()

        self.selection_rect_display = None
        self.selection_rect_original = None
        self.clicked_point_original = None

        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(420, 420)
        self.setStyleSheet("""
            QLabel {
                background-color: #f3f4f6;
                border: 1px solid #d1d5db;
                border-radius: 8px;
            }
        """)

    def set_image(self, image_path, reset_user_input=True):
        pixmap = QPixmap(str(image_path))
        self.set_pixmap_from_qpixmap(pixmap, reset_user_input=reset_user_input)

    def set_pixmap_from_qpixmap(self, pixmap, reset_user_input=True):
        if pixmap.isNull():
            return

        self.original_image_size = pixmap.size()

        scaled = pixmap.scaled(
            QSize(520, 520),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.display_pixmap = scaled
        self.setPixmap(scaled)

        if reset_user_input:
            self.selection_rect_display = None
            self.selection_rect_original = None
            self.clicked_point_original = None
            self.rubber_band.hide()

    def mousePressEvent(self, event: QMouseEvent):
        if not self.display_pixmap:
            return

        if event.button() != Qt.LeftButton:
            return

        if self.allow_selection:
            point = event.position().toPoint()
            mapped = self.map_display_to_original(point)

            if mapped is None:
                if self.parent_dialog:
                    self.parent_dialog.set_status("Start dragging inside the preview image.")
                return

            self.origin = point
            self.rubber_band.setGeometry(QRect(self.origin, QSize()))
            self.rubber_band.show()

        elif self.allow_click:
            point = event.position().toPoint()
            mapped = self.map_display_to_original(point)

            if mapped is None:
                if self.parent_dialog:
                    self.parent_dialog.set_status("Click inside the preview image.")
                return

            self.clicked_point_original = mapped

            if self.parent_dialog:
                x, y = mapped
                self.parent_dialog.set_status(f"Text position selected: x={x}, y={y}. Now click Update Preview.")

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.allow_selection:
            return

        if not self.display_pixmap:
            return

        self.rubber_band.setGeometry(
            QRect(self.origin, event.position().toPoint()).normalized()
        )

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.allow_selection:
            return

        if not self.display_pixmap:
            return

        rect = QRect(self.origin, event.position().toPoint()).normalized()
        mapped_rect = self.map_rect_to_original(rect)

        if mapped_rect is None:
            self.rubber_band.hide()
            self.selection_rect_display = None
            self.selection_rect_original = None

            if self.parent_dialog:
                self.parent_dialog.set_status("Invalid selection. Drag inside the preview image.")
            return

        self.selection_rect_display = rect
        self.selection_rect_original = mapped_rect

        if self.parent_dialog:
            left, top, right, bottom = mapped_rect
            self.parent_dialog.set_status(
                f"Area selected: left={left}, top={top}, right={right}, bottom={bottom}. Now click Update Preview."
            )

    def _pixmap_offsets(self):
        if not self.display_pixmap:
            return 0, 0

        x_offset = (self.width() - self.display_pixmap.width()) // 2
        y_offset = (self.height() - self.display_pixmap.height()) // 2

        return x_offset, y_offset

    def map_display_to_original(self, point):
        if not self.display_pixmap or not self.original_image_size:
            return None

        x_offset, y_offset = self._pixmap_offsets()

        x = point.x() - x_offset
        y = point.y() - y_offset

        if x < 0 or y < 0:
            return None

        if x >= self.display_pixmap.width() or y >= self.display_pixmap.height():
            return None

        scale_x = self.original_image_size.width() / self.display_pixmap.width()
        scale_y = self.original_image_size.height() / self.display_pixmap.height()

        orig_x = int(x * scale_x)
        orig_y = int(y * scale_y)

        return orig_x, orig_y

    def map_rect_to_original(self, rect):
        top_left = self.map_display_to_original(rect.topLeft())
        bottom_right = self.map_display_to_original(rect.bottomRight())

        if top_left is None or bottom_right is None:
            return None

        left, top = top_left
        right, bottom = bottom_right

        left = max(0, left)
        top = max(0, top)

        right = min(self.original_image_size.width(), right)
        bottom = min(self.original_image_size.height(), bottom)

        if left >= right or top >= bottom:
            return None

        return left, top, right, bottom


class ImageEditorDialog(QDialog):
    def __init__(self, input_file, operation, parent=None):
        super().__init__(parent)

        self.input_file = input_file
        self.operation = operation
        self.input_path = Path(input_file)

        self.original_image = None
        self.preview_image = None

        self.setWindowTitle(f"Image Editor - {operation}")
        self.resize(1200, 760)

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.info_label = QLabel()
        self.info_label.setStyleSheet(
            "font-size: 14px; color: #374151; padding: 6px;"
        )
        self.main_layout.addWidget(self.info_label)

        image_layout = QHBoxLayout()

        left_box = QVBoxLayout()
        left_title = QLabel("Original")
        left_title.setAlignment(Qt.AlignCenter)
        left_title.setStyleSheet("font-weight: bold; font-size: 16px;")

        self.original_canvas = ImageCanvas()
        self.original_canvas.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding
        )

        left_box.addWidget(left_title)
        left_box.addWidget(self.original_canvas)

        right_box = QVBoxLayout()
        right_title = QLabel("Preview")
        right_title.setAlignment(Qt.AlignCenter)
        right_title.setStyleSheet("font-weight: bold; font-size: 16px;")

        allow_selection = operation in ["crop", "blur"]
        allow_click = operation == "add_text"

        self.preview_canvas = ImageCanvas(
            allow_selection=allow_selection,
            allow_click=allow_click,
            parent_dialog=self
        )
        self.preview_canvas.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding
        )

        right_box.addWidget(right_title)
        right_box.addWidget(self.preview_canvas)

        image_layout.addLayout(left_box)
        image_layout.addLayout(right_box)

        self.main_layout.addLayout(image_layout)

        self.controls_box = QGroupBox("Controls")
        self.controls_layout = QFormLayout()
        self.controls_box.setLayout(self.controls_layout)

        self.main_layout.addWidget(self.controls_box)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 13px; color: #2563eb; padding: 4px;")
        self.main_layout.addWidget(self.status_label)

        button_layout = QHBoxLayout()

        self.preview_btn = QPushButton("Update Preview")
        self.undo_btn = QPushButton("Undo")
        self.save_btn = QPushButton("Save Output")
        self.close_btn = QPushButton("Close")

        self.preview_btn.clicked.connect(self.update_preview)
        self.undo_btn.clicked.connect(self.undo_preview)
        self.save_btn.clicked.connect(self.save_output)
        self.close_btn.clicked.connect(self.close)

        button_layout.addStretch()
        button_layout.addWidget(self.preview_btn)
        button_layout.addWidget(self.undo_btn)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.close_btn)

        self.main_layout.addLayout(button_layout)

        self.preview_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        run_task(self, ImageService.load_image, self.input_file, on_success=self.image_loaded,
                 allow_multiframe=self.operation == 'compress',
                 task_title="Loading image")

    def image_loaded(self, image):
        self.original_image = image
        self.preview_image = image.copy()
        self.original_canvas.set_pixmap_from_qpixmap(QPixmap.fromImage(ImageQt(image)))
        self.build_controls()
        self.update_info()
        self.update_preview_canvas(reset_user_input=False)
        self.preview_btn.setEnabled(True)
        self.undo_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        if self.operation in ("crop", "blur"):
            self.set_status("Drag an area on the Preview image, then click Update Preview.")
        elif self.operation == "add_text":
            self.set_status("Enter text and click on the Preview image to choose its position.")
        else:
            self.update_preview()

    def set_status(self, message):
        self.status_label.setText(message)

    def update_info(self):
        width, height = self.original_image.size
        size_kb = os.path.getsize(self.input_file) / 1024

        self.info_label.setText(
            f"File: {self.input_path.name} | "
            f"Original dimensions: {width} x {height} px | "
            f"Original size: {size_kb:.2f} KB"
        )
        count = self.original_image.info.get('odt_frame_count', 1)
        if count > 1:
            self.info_label.setText(self.info_label.text() +
                f' | {count} pages; preview shows page 1; compression saves all pages')

    def build_controls(self):
        self.widgets = {}

        if self.operation == "resize":
            width, height = self.original_image.size

            self.widgets["width"] = QSpinBox()
            self.widgets["width"].setRange(1, 50000)
            self.widgets["width"].setValue(width)

            self.widgets["height"] = QSpinBox()
            self.widgets["height"].setRange(1, 50000)
            self.widgets["height"].setValue(height)

            self.widgets["keep_aspect"] = QCheckBox("Keep aspect ratio")
            self.widgets["keep_aspect"].setChecked(True)

            self.controls_layout.addRow("Width:", self.widgets["width"])
            self.controls_layout.addRow("Height:", self.widgets["height"])
            self.controls_layout.addRow("", self.widgets["keep_aspect"])

        elif self.operation == "compress":
            self.widgets["quality"] = QSlider(Qt.Horizontal)
            self.widgets["quality"].setRange(1, 100)
            self.widgets["quality"].setValue(70)

            self.widgets["quality_label"] = QLabel("70")

            quality_row = QHBoxLayout()
            quality_row.addWidget(self.widgets["quality"])
            quality_row.addWidget(self.widgets["quality_label"])

            self.widgets["quality"].valueChanged.connect(
                lambda v: self.widgets["quality_label"].setText(str(v))
            )

            self.widgets["estimated_size"] = QLabel(
                "Estimated compressed size will appear after preview."
            )

            self.controls_layout.addRow("Quality:", quality_row)
            self.controls_layout.addRow("Info:", self.widgets["estimated_size"])

        elif self.operation == "convert_format":
            self.widgets["output_format"] = QComboBox()
            self.widgets["output_format"].addItems(["png", "jpg", "webp", "bmp"])

            note = QLabel("Choose the output format, then click Save Output.")

            self.controls_layout.addRow("Output format:", self.widgets["output_format"])
            self.controls_layout.addRow("Instruction:", note)

        elif self.operation == "rotate":
            self.widgets["angle"] = QComboBox()
            self.widgets["angle"].addItems(["90", "180", "270"])
            self.controls_layout.addRow("Angle:", self.widgets["angle"])

        elif self.operation == "flip":
            self.widgets["direction"] = QComboBox()
            self.widgets["direction"].addItems(["horizontal", "vertical"])
            self.controls_layout.addRow("Direction:", self.widgets["direction"])

        elif self.operation == "brightness_contrast":
            self.widgets["brightness"] = QDoubleSpinBox()
            self.widgets["brightness"].setRange(0.1, 5.0)
            self.widgets["brightness"].setSingleStep(0.1)
            self.widgets["brightness"].setValue(1.1)

            self.widgets["contrast"] = QDoubleSpinBox()
            self.widgets["contrast"].setRange(0.1, 5.0)
            self.widgets["contrast"].setSingleStep(0.1)
            self.widgets["contrast"].setValue(1.1)

            self.controls_layout.addRow("Brightness:", self.widgets["brightness"])
            self.controls_layout.addRow("Contrast:", self.widgets["contrast"])

        elif self.operation == "sharpen":
            self.widgets["factor"] = QDoubleSpinBox()
            self.widgets["factor"].setRange(0.1, 10.0)
            self.widgets["factor"].setSingleStep(0.1)
            self.widgets["factor"].setValue(2.0)

            self.controls_layout.addRow("Sharpen factor:", self.widgets["factor"])

        elif self.operation == "denoise":
            self.widgets["strength"] = QSpinBox()
            self.widgets["strength"].setRange(1, 30)
            self.widgets["strength"].setValue(10)

            self.controls_layout.addRow("Denoise strength:", self.widgets["strength"])

        elif self.operation == "crop":
            note = QLabel(
                "Drag from top-left to bottom-right on the Preview image, then click Update Preview."
            )
            self.controls_layout.addRow("Instruction:", note)

        elif self.operation == "add_text":
            self.widgets["text"] = QLineEdit()
            self.widgets["text"].setPlaceholderText("Enter text here")

            self.widgets["font_size"] = QSpinBox()
            self.widgets["font_size"].setRange(8, 300)
            self.widgets["font_size"].setValue(32)

            note = QLabel(
                "Enter text, click on the Preview image to choose position, then click Update Preview."
            )

            self.controls_layout.addRow("Text:", self.widgets["text"])
            self.controls_layout.addRow("Font size:", self.widgets["font_size"])
            self.controls_layout.addRow("Instruction:", note)

        elif self.operation == "blur":
            self.widgets["blur_radius"] = QSpinBox()
            self.widgets["blur_radius"].setRange(1, 100)
            self.widgets["blur_radius"].setValue(12)

            note = QLabel(
                "Drag over the sensitive area on the Preview image, then click Update Preview."
            )

            self.controls_layout.addRow("Blur radius:", self.widgets["blur_radius"])
            self.controls_layout.addRow("Instruction:", note)

        elif self.operation == "black_white":
            note = QLabel("Click Update Preview to convert the image to black and white.")
            self.controls_layout.addRow("Instruction:", note)

    def update_preview_canvas(self, reset_user_input=True):
        self.preview_canvas.set_pixmap_from_qpixmap(
            QPixmap.fromImage(ImageQt(self.preview_image)), reset_user_input=reset_user_input)

    def update_preview(self):
        params = {}
        operation = self.operation
        if operation == "resize":
            params = {"width": self.widgets["width"].value(),
                      "height": self.widgets["height"].value(),
                      "keep_aspect": self.widgets["keep_aspect"].isChecked()}
        elif operation == "compress":
            params = {"quality": self.widgets["quality"].value()}
        elif operation == "rotate":
            params = {"angle": int(self.widgets["angle"].currentText())}
        elif operation == "flip":
            params = {"direction": self.widgets["direction"].currentText()}
        elif operation in ("brightness_contrast", "sharpen", "denoise"):
            names = {"brightness_contrast": ("brightness", "contrast"),
                     "sharpen": ("factor",), "denoise": ("strength",)}[operation]
            params = {key: self.widgets[key].value() for key in names}
        elif operation in ("crop", "blur"):
            rect = self.preview_canvas.selection_rect_original
            if rect is None:
                self.set_status("Select an area on the Preview image first.")
                return
            params = {"rect": rect}
            if operation == "blur":
                params["blur_radius"] = self.widgets["blur_radius"].value()
        elif operation == "add_text":
            point = self.preview_canvas.clicked_point_original
            if point is None or not self.widgets["text"].text().strip():
                self.set_status("Enter text and select its position on the Preview image.")
                return
            params = {"text": self.widgets["text"].text(), "x": point[0], "y": point[1],
                      "font_size": self.widgets["font_size"].value()}

        def completed(result):
            self.preview_image, size = result
            self.update_preview_canvas(reset_user_input=True)
            if size is not None:
                suffix = self.input_path.suffix.lower()
                note = " (lossless; quality does not apply)" if suffix in (".png", ".bmp", ".tiff") else ""
                self.widgets["estimated_size"].setText(f"Output size in original format: {size / 1024:.2f} KB{note}")
            self.set_status("Preview updated. You can save the output.")
        base = self.preview_image if operation in ('crop', 'blur', 'add_text') else None
        run_task(self, ImageService.preview_image, self.input_file, operation, params, base_image=base,
                 on_success=completed, task_title="Updating image preview")

    def undo_preview(self):
        self.preview_image = self.original_image.copy()

        self.preview_canvas.selection_rect_display = None
        self.preview_canvas.selection_rect_original = None
        self.preview_canvas.clicked_point_original = None
        self.preview_canvas.rubber_band.hide()

        self.update_preview_canvas(reset_user_input=True)

        if self.operation in ["crop", "blur"]:
            self.set_status("Undo done. Drag a new area on the Preview image, then click Update Preview.")
        elif self.operation == "add_text":
            self.set_status("Undo done. Enter text, click a position on the Preview image, then click Update Preview.")
        else:
            self.set_status("Undo done. Preview restored to original image.")


    def save_output(self):
        default_suffix = self.input_path.suffix

        if self.operation == "convert_format":
            selected_format = self.widgets["output_format"].currentText()
            default_suffix = f".{selected_format}"

        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save output image as",
            get_default_output_path(f"{self.operation}_output{default_suffix}"),
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not output_file:
            return

        output_path = Path(output_file)
        if self.operation == "convert_format":
            output_path = output_path.with_suffix("." + self.widgets["output_format"].currentText())
        elif not output_path.suffix:
            output_path = output_path.with_suffix(self.input_path.suffix)
        if not confirm_normalized_output(self, output_file, output_path):
            return
        quality = self.widgets["quality"].value() if self.operation == "compress" else None

        def completed(result):
            result_path = result[0] if isinstance(result, tuple) else result
            QMessageBox.information(self, "Success", f"Image saved successfully.\n\nSaved at:\n{result_path}")
        if self.operation == 'compress':
            run_task(self, ImageService.compress_image, self.input_file, str(output_path),
                     quality=quality, on_success=completed, task_title="Saving compressed image")
        else:
            run_task(self, ImageService.save_image, self.preview_image, str(output_path),
                     on_success=completed, task_title="Saving image")

    def closeEvent(self, event):
        cancel_tasks(self)
        if self.original_image is not None:
            self.original_image.close()
        event.accept()
