from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGridLayout,
    QPushButton,
)
from PySide6.QtCore import Qt


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)

        self.setLayout(layout)

        title = QLabel("Offline Document Processing Toolkit")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "A local offline app for PDF, image, OCR, and Word document operations."
        )
        subtitle.setStyleSheet("font-size: 16px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(18)

        cards = [
            ("PDF Tools", "Merge, split, rotate, extract, compress, and convert PDFs."),
            ("Image Tools", "Resize, crop, compress, convert, rotate, and enhance images."),
            ("OCR Tools", "Extract text from images and scanned PDFs offline."),
            ("Word Tools", "Convert DOCX, extract text, and automate document tasks."),
            ("Batch Tools", "Process multiple files together."),
            ("Privacy First", "All files stay on your local system."),
        ]

        for i, (heading, text) in enumerate(cards):
            card = self.create_card(heading, text)
            row = i // 2
            col = i % 2
            grid.addWidget(card, row, col)

        layout.addLayout(grid)
        layout.addStretch()

    def create_card(self, heading, text):
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(130)
        button.setText(f"{heading}\n\n{text}")
        button.setStyleSheet("""
            QPushButton {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                text-align: left;
                padding: 20px;
                font-size: 15px;
                color: #333;
            }

            QPushButton:hover {
                border: 1px solid #2563eb;
                background-color: #f8fbff;
            }
        """)
        return button