from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGridLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
)

from ui.image_editor_dialog import ImageEditorDialog


class ImageToolsPage(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)
        self.setLayout(layout)

        title = QLabel("Image Tools")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Open an image, preview changes, then save the edited output locally."
        )
        subtitle.setStyleSheet("font-size: 15px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(16)

        self.tools = {
            "Crop Image": "crop",
            "Resize Image": "resize",
            "Rotate Image": "rotate",
            "Flip Image": "flip",
            "Compress Image": "compress",
            "Convert Format": "convert_format",
            "Brightness / Contrast": "brightness_contrast",
            "Sharpen Image": "sharpen",
            "Denoise Image": "denoise",
            "Black and White": "black_white",
            "Add Text": "add_text",
            "Blur Sensitive Area": "blur",
        }

        self.tool_buttons = {}

        for i, tool_name in enumerate(self.tools.keys()):
            button = self.create_tool_button(tool_name)
            self.tool_buttons[tool_name] = button
            grid.addWidget(button, i // 3, i % 3)

            operation = self.tools[tool_name]
            button.clicked.connect(
                lambda checked=False, op=operation: self.open_image_editor(op)
            )

        layout.addLayout(grid)
        layout.addStretch()

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
                border: 1px solid #16a34a;
                background-color: #f0fdf4;
            }
        """)
        return button

    def open_image_editor(self, operation):
        input_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )

        if not input_file:
            return

        try:
            dialog = ImageEditorDialog(
                input_file=input_file,
                operation=operation,
                parent=self
            )
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open image editor.\n\nReason:\n{str(e)}"
            )