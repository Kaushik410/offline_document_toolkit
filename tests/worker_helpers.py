"""Importable jobs used to exercise real spawned processes."""
import os
from pathlib import Path
import subprocess
import sys
import time
from utils.output_utils import atomic_output


def slow_output(destination, progress_callback=None, status_callback=None):
    with atomic_output(destination) as temporary:
        temporary.write_text('incomplete')
        child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        if status_callback:
            status_callback(str(child.pid))
        if progress_callback:
            progress_callback(10)
        time.sleep(30)
    return destination


def process_identity():
    return os.getpid()
