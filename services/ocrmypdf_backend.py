from utils.external_process import run_external
"""Optional comparison backend, kept outside the default OCR pipeline."""
from pathlib import Path
import subprocess
from utils.engine_registry import EngineRegistry
from utils.output_utils import atomic_output


def convert(input_file,output_file,lang='eng'):
    executable=EngineRegistry.find('ocrmypdf')
    if not executable:raise RuntimeError('Optional OCRmyPDF backend is not installed. Use Setup for installation guidance.')
    with atomic_output(output_file) as temporary:
        result=run_external([executable,'--skip-text','--rotate-pages','--deskew','--output-type','pdf',
                               '--optimize','0','-l',lang,str(Path(input_file).resolve()),str(temporary)],
                              capture_output=True,text=True,timeout=300)
        if result.returncode:raise RuntimeError('OCRmyPDF failed: '+result.stderr)
    return str(output_file)
