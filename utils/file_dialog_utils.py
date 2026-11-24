from pathlib import Path
from utils.app_config import AppConfig


def get_default_output_folder():
    config = AppConfig.load_config()
    folder = Path(config.get("default_output_folder", "outputs"))
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def get_default_output_path(default_filename):
    folder = Path(get_default_output_folder())
    return str(folder / default_filename)


def confirm_normalized_output(parent, selected_path, final_path):
    """The native save dialog only confirms the path it returned, before normalization."""
    from PySide6.QtWidgets import QMessageBox
    selected, final = Path(selected_path), Path(final_path)
    if final.resolve() != selected.resolve() and final.exists():
        return QMessageBox.question(
            parent, 'Replace existing file?',
            f'The selected format will save to:\n{final}\n\nThis file already exists. Replace it?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) == QMessageBox.Yes
    return True


def normalize_output_selection(parent, selected_path, suffix, append=False):
    """Normalize before scheduling a save, including the final overwrite check."""
    if not selected_path:
        return ''
    final = Path(selected_path)
    if final.suffix.lower() != suffix:
        final = Path(str(final) + suffix) if append else final.with_suffix(suffix)
    return str(final) if confirm_normalized_output(parent, selected_path, final) else ''
