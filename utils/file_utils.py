from pathlib import Path


def ensure_output_dir():
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    return output_dir


def get_file_name_without_extension(file_path):
    return Path(file_path).stem


def get_file_extension(file_path):
    return Path(file_path).suffix.lower()