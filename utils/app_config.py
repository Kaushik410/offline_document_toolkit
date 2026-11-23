from utils.external_process import run_external
from pathlib import Path
import json
import shutil
import subprocess
import sys
import os

from utils.output_utils import atomic_output


class AppConfig:
    if os.name == "nt":
        _root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        _root = Path.home() / "Library/Application Support"
    else:
        _root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    CONFIG_FILE = Path(os.environ.get("ODT_CONFIG_DIR", _root / "offline-document-toolkit")).expanduser() / "settings.json"
    DEFAULT_CONFIG = {
        "default_output_folder": str(Path(os.environ.get(
            "ODT_OUTPUT_DIR", Path.home() / "Documents/Offline Document Toolkit")).expanduser()),
    }

    @staticmethod
    def load_config():
        config = AppConfig.DEFAULT_CONFIG.copy()
        try:
            data = json.loads(AppConfig.CONFIG_FILE.read_text(encoding="utf-8"))
            for key in ("setup_complete", "last_project"):
                if key in data:
                    config[key] = data[key]
            folder_override=data.get("workspace_directory")
            if isinstance(folder_override,str) and folder_override.strip():config["workspace_directory"]=folder_override
            paths = data.get("engine_paths", {})
            if isinstance(paths, dict) and paths:
                config["engine_paths"] = {key: value for key, value in paths.items() if isinstance(key, str) and isinstance(value, str)}
            folder = data.get("default_output_folder")
            if isinstance(folder, str) and folder.strip():
                config["default_output_folder"] = str(Path(folder).expanduser())
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return config

    @staticmethod
    def save_config(config):
        with atomic_output(AppConfig.CONFIG_FILE) as temporary:
            temporary.write_text(json.dumps(config, indent=4), encoding="utf-8")

    @staticmethod
    def reset_config():
        AppConfig.save_config(AppConfig.DEFAULT_CONFIG)
        return AppConfig.DEFAULT_CONFIG.copy()

    @staticmethod
    def ensure_output_folder():
        config = AppConfig.load_config()
        output_dir = Path(config["default_output_folder"])
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @staticmethod
    def find_command(command_names):
        for command in command_names:
            path = shutil.which(command)
            if path:
                return path
        return None

    @staticmethod
    def get_command_version(command):
        try:
            result = run_external(
                [command, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )

            output = result.stdout.strip() or result.stderr.strip()

            if output:
                return output.splitlines()[0]

            return "Installed, version unknown"

        except Exception as e:
            return f"Version check failed: {str(e)}"

    @staticmethod
    def check_dependencies():
        from utils.engine_registry import EngineRegistry
        dependencies = []

        python_info = {
            "name": "Python",
            "status": "Found",
            "path": sys.executable,
            "version": sys.version.splitlines()[0],
            "required_for": "Application runtime",
        }

        dependencies.append(python_info)

        tesseract_path = EngineRegistry.find("tesseract")
        if tesseract_path:
            dependencies.append({
                "name": "Tesseract OCR",
                "status": "Found",
                "path": tesseract_path,
                "version": AppConfig.get_command_version(tesseract_path),
                "required_for": "OCR tools",
            })
        else:
            dependencies.append({
                "name": "Tesseract OCR",
                "status": "Missing",
                "path": "Not found",
                "version": "Not available",
                "required_for": "OCR tools",
            })

        libreoffice_path = EngineRegistry.find("libreoffice")
        if libreoffice_path:
            dependencies.append({
                "name": "LibreOffice",
                "status": "Found",
                "path": libreoffice_path,
                "version": AppConfig.get_command_version(libreoffice_path),
                "required_for": "DOCX to PDF",
            })
        else:
            dependencies.append({
                "name": "LibreOffice",
                "status": "Missing",
                "path": "Not found",
                "version": "Not available",
                "required_for": "DOCX to PDF",
            })

        ghostscript_path = EngineRegistry.find("ghostscript")
        if ghostscript_path:
            dependencies.append({
                "name": "Ghostscript",
                "status": "Found",
                "path": ghostscript_path,
                "version": AppConfig.get_command_version(ghostscript_path),
                "required_for": "Strong PDF compression",
            })
        else:
            dependencies.append({
                "name": "Ghostscript",
                "status": "Missing",
                "path": "Not found",
                "version": "Not available",
                "required_for": "Strong PDF compression",
            })

        return dependencies