from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer
import os

from ui.dashboard_page import DashboardPage
from ui.pdf_tools_page import PDFToolsPage
from ui.image_tools_page import ImageToolsPage
from ui.ocr_tools_page import OCRToolsPage
from ui.word_tools_page import WordToolsPage
from ui.settings_page import SettingsPage
from ui.batch_tools_page import BatchToolsPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        from services.workspace_store import WorkspaceStore
        from ui.job_queue import JobQueue
        self.workspace_store = WorkspaceStore()
        self.job_queue = JobQueue(self.workspace_store, self)
        from utils.version import VERSION
        self.setWindowTitle("Offline Document Toolkit "+VERSION)
        self.resize(1200, 750)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6fa;
            }

            QWidget {
                font-family: Segoe UI;
                font-size: 14px;
            }

            QLabel#TitleLabel {
                font-size: 24px;
                font-weight: bold;
                color: #222;
                padding: 16px;
            }

            QWidget#Sidebar {
                background-color: #1f2937;
            }

            QPushButton#SidebarButton {
                color: white;
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 14px 18px;
                font-size: 15px;
            }

            QPushButton#SidebarButton:hover {
                background-color: #374151;
            }

            QPushButton#SidebarButton:checked {
                background-color: #2563eb;
                font-weight: bold;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.central_widget.setLayout(main_layout)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(240)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(4)
        self.sidebar.setLayout(sidebar_layout)

        app_title = QLabel("Doc Toolkit")
        app_title.setAlignment(Qt.AlignCenter)
        app_title.setStyleSheet("""
            color: white;
            font-size: 22px;
            font-weight: bold;
            padding: 18px;
        """)
        sidebar_layout.addWidget(app_title)

        self.btn_dashboard = self.create_sidebar_button("Dashboard")
        self.btn_pdf = self.create_sidebar_button("PDF Tools")
        self.btn_image = self.create_sidebar_button("Image Tools")
        self.btn_ocr = self.create_sidebar_button("OCR Tools")
        self.btn_word = self.create_sidebar_button("Word Tools")
        self.btn_batch = self.create_sidebar_button("Batch Tools")
        self.btn_settings = self.create_sidebar_button("Settings")

        self.buttons = [
            self.btn_dashboard,
            self.btn_pdf,
            self.btn_image,
            self.btn_ocr,
            self.btn_word,
            self.btn_batch,
            self.btn_settings,
        ]

        sidebar_layout.addWidget(self.btn_dashboard)
        sidebar_layout.addWidget(self.btn_pdf)
        sidebar_layout.addWidget(self.btn_image)
        sidebar_layout.addWidget(self.btn_ocr)
        sidebar_layout.addWidget(self.btn_word)
        sidebar_layout.addWidget(self.btn_batch)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(self.btn_settings)

        self.stack = QStackedWidget()

        self.dashboard_page = DashboardPage()
        self.pdf_tools_page = PDFToolsPage()
        self.image_tools_page = ImageToolsPage()
        self.ocr_tools_page = OCRToolsPage()
        self.word_tools_page = WordToolsPage()
        self.batch_tools_page = BatchToolsPage()
        self.settings_page = SettingsPage()

        self.stack.addWidget(self.dashboard_page)      # 0
        self.stack.addWidget(self.pdf_tools_page)      # 1
        self.stack.addWidget(self.image_tools_page)    # 2
        self.stack.addWidget(self.ocr_tools_page)      # 3
        self.stack.addWidget(self.word_tools_page)     # 4
        self.stack.addWidget(self.batch_tools_page)    # 5
        self.stack.addWidget(self.settings_page)       # 6

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stack)

        self.btn_dashboard.clicked.connect(lambda: self.switch_page(0, self.btn_dashboard))
        self.btn_pdf.clicked.connect(lambda: self.switch_page(1, self.btn_pdf))
        self.btn_image.clicked.connect(lambda: self.switch_page(2, self.btn_image))
        self.btn_ocr.clicked.connect(lambda: self.switch_page(3, self.btn_ocr))
        self.btn_word.clicked.connect(lambda: self.switch_page(4, self.btn_word))
        self.btn_batch.clicked.connect(lambda: self.switch_page(5, self.btn_batch))
        self.btn_settings.clicked.connect(lambda: self.switch_page(6, self.btn_settings))

        from ui.workspace_page import WorkspacePage
        from ui.jobs_page import JobsPage
        from ui.library_page import LibraryPage
        self.workspace_page = WorkspacePage(self.workspace_store, self.job_queue)
        self.jobs_page = JobsPage(self.workspace_store, self.job_queue)
        self.library_page = LibraryPage(self.workspace_store)
        for name, page in [("Workspace", self.workspace_page), ("Jobs", self.jobs_page), ("Library", self.library_page)]:
            button = self.create_sidebar_button(name)
            self.buttons.append(button)
            sidebar_layout.insertWidget(len(self.buttons)-7, button)
            index = self.stack.addWidget(page)
            button.clicked.connect(lambda checked=False, i=index, b=button: self.switch_page(i,b))
            if name == "Workspace": self.btn_workspace = button
            if name == "Jobs": self.btn_jobs = button
        self.workspace_page.jobQueued.connect(lambda job_id: self.switch_page(self.stack.indexOf(self.jobs_page), self.btn_jobs))
        self.switch_page(self.stack.indexOf(self.workspace_page), self.btn_workspace)
        from utils.app_config import AppConfig
        if not AppConfig.load_config().get("setup_complete") and not os.environ.get("ODT_NO_SETUP"):
            QTimer.singleShot(200,self.open_setup)

    def create_sidebar_button(self, text):
        button = QPushButton(text)
        button.setObjectName("SidebarButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def switch_page(self, index, active_button):
        self.stack.setCurrentIndex(index)
        if getattr(self, 'library_page', None) is self.stack.currentWidget():
            self.library_page.search()

        for button in self.buttons:
            button.setChecked(False)

        active_button.setChecked(True)
    def closeEvent(self, event):
        from utils.task_controller import cancel_tasks
        cancel_tasks(self)
        self.job_queue.shutdown()
        self.workspace_page.shutdown()
        self.jobs_page.timer.stop()
        self.library_page.timer.stop()
        super().closeEvent(event)

    def open_setup(self):
        from ui.setup_dialog import SetupDialog
        SetupDialog(self).exec()
