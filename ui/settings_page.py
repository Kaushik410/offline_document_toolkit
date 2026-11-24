from utils.task_controller import run_task
from pathlib import Path
import subprocess
import sys

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QGroupBox,
    QFormLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from PySide6.QtCore import Qt

from utils.app_config import AppConfig


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()

        self.config = AppConfig.load_config()

        layout = QVBoxLayout()
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)

        self.setLayout(layout)

        title = QLabel("Settings")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Configure local output folders and check offline dependencies."
        )
        subtitle.setStyleSheet("font-size: 15px; color: #555; padding-left: 16px;")
        layout.addWidget(subtitle)

        self.create_output_folder_section(layout)
        self.create_dependency_section(layout)
        setup_button = QPushButton("Set up / locate local engines…")
        setup_button.clicked.connect(self.open_setup)
        layout.addWidget(setup_button)

        layout.addStretch()

    def create_output_folder_section(self, parent_layout):
        group = QGroupBox("Output Settings")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                margin-top: 10px;
                padding: 14px;
                background-color: white;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)

        form_layout = QFormLayout()
        group.setLayout(form_layout)

        folder_layout = QHBoxLayout()

        self.output_folder_input = QLineEdit()
        self.output_folder_input.setText(
            self.config.get("default_output_folder", "outputs")
        )
        self.output_folder_input.setPlaceholderText("Select default output folder")

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_output_folder)

        folder_layout.addWidget(self.output_folder_input)
        folder_layout.addWidget(browse_btn)

        form_layout.addRow("Default Output Folder:", folder_layout)

        button_layout = QHBoxLayout()

        save_btn = QPushButton("Save Settings")
        reset_btn = QPushButton("Reset Settings")
        open_btn = QPushButton("Open Output Folder")

        save_btn.clicked.connect(self.save_settings)
        reset_btn.clicked.connect(self.reset_settings)
        open_btn.clicked.connect(self.open_output_folder)

        button_layout.addStretch()
        button_layout.addWidget(open_btn)
        button_layout.addWidget(reset_btn)
        button_layout.addWidget(save_btn)

        form_layout.addRow("", button_layout)

        parent_layout.addWidget(group)

    def create_dependency_section(self, parent_layout):
        group = QGroupBox("Offline Dependency Check")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                margin-top: 10px;
                padding: 14px;
                background-color: white;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)

        layout = QVBoxLayout()
        group.setLayout(layout)

        self.dependency_table = QTableWidget()
        self.dependency_table.setColumnCount(5)
        self.dependency_table.setHorizontalHeaderLabels(
            ["Tool", "Status", "Path", "Version", "Used For"]
        )

        self.dependency_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.dependency_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dependency_table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addWidget(self.dependency_table)

        button_layout = QHBoxLayout()

        refresh_btn = QPushButton("Refresh Check")
        refresh_btn.clicked.connect(self.load_dependency_table)

        button_layout.addStretch()
        button_layout.addWidget(refresh_btn)

        layout.addLayout(button_layout)

        parent_layout.addWidget(group)

        self.load_dependency_table()

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Default Output Folder",
            self.output_folder_input.text()
        )

        if folder:
            self.output_folder_input.setText(folder)

    def save_settings(self):
        folder = self.output_folder_input.text().strip()

        if not folder:
            QMessageBox.warning(
                self,
                "Invalid Folder",
                "Output folder cannot be empty."
            )
            return

        try:
            output_dir = Path(folder)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Setup and workspace autosave may have changed these settings
            # since this screen was constructed.
            self.config = AppConfig.load_config()
            self.config["default_output_folder"] = str(output_dir.resolve())
            AppConfig.save_config(self.config)

            QMessageBox.information(
                self,
                "Settings Saved",
                f"Settings saved successfully.\n\nOutput folder:\n{output_dir.resolve()}"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save settings.\n\nReason:\n{str(e)}"
            )

    def reset_settings(self):
        self.config = AppConfig.reset_config()
        self.output_folder_input.setText(self.config["default_output_folder"])

        QMessageBox.information(
            self,
            "Settings Reset",
            "Settings reset to default values."
        )

    def open_output_folder(self):
        folder = self.output_folder_input.text().strip()

        if not folder:
            QMessageBox.warning(
                self,
                "Invalid Folder",
                "Output folder cannot be empty."
            )
            return

        try:
            output_dir = Path(folder)
            output_dir.mkdir(parents=True, exist_ok=True)

            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(output_dir)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(output_dir)])
            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(output_dir)])
            else:
                QMessageBox.information(
                    self,
                    "Output Folder",
                    f"Output folder:\n{output_dir}"
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open output folder.\n\nReason:\n{str(e)}"
            )

    def load_dependency_table(self):
        run_task(self, AppConfig.check_dependencies, on_success=self.set_dependency_table,
                 show_progress=False)

    def set_dependency_table(self, dependencies):

        self.dependency_table.setRowCount(len(dependencies))

        for row, dep in enumerate(dependencies):
            values = [
                dep["name"],
                dep["status"],
                dep["path"],
                dep["version"],
                dep["required_for"],
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if col == 1:
                    if value == "Found":
                        item.setForeground(Qt.darkGreen)
                    else:
                        item.setForeground(Qt.red)

                self.dependency_table.setItem(row, col, item)
    def open_setup(self):
        from ui.setup_dialog import SetupDialog
        SetupDialog(self).exec()
