"""Atomic file replacement shared by services and cancellable worker processes."""
from contextlib import contextmanager
from pathlib import Path
import os
import uuid


_report_temp = None


@contextmanager
def atomic_output(destination):
    """Keep the old destination intact until a complete replacement is ready."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / (".odt-" + uuid.uuid4().hex + destination.suffix)
    if _report_temp:
        _report_temp(str(temporary))
    # Register before creation so termination cannot leave an untracked file.
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        yield temporary
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def distinct_output(input_file, output_file):
    if Path(input_file).resolve() == Path(output_file).resolve():
        raise ValueError("Choose an output file different from the input file.")
