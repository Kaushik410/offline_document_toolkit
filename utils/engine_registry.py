"""Locate installed or bundled engines without requiring users to edit PATH."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

from utils.app_config import AppConfig


class EngineRegistry:
    COMMANDS = {'tesseract':('tesseract',), 'libreoffice':('libreoffice','soffice'),
                'ghostscript':('gs','gswin64c','gswin32c'), 'ocrmypdf':('ocrmypdf',)}
    URLS = {'tesseract':'https://tesseract-ocr.github.io/tessdoc/Installation.html',
            'libreoffice':'https://www.libreoffice.org/download/download-libreoffice/',
            'ghostscript':'https://ghostscript.com/releases/gsdnld.html',
            'ocrmypdf':'https://ocrmypdf.readthedocs.io/en/stable/installation.html'}

    @staticmethod
    def find(name):
        config = AppConfig.load_config()
        configured = config.get('engine_paths',{}).get(name)
        if configured and Path(configured).is_file():
            return str(Path(configured).resolve())
        roots = [Path(sys.executable).parent/'engines', Path(getattr(sys,'_MEIPASS', '.'))/'engines']
        for root in roots:
            for command in EngineRegistry.COMMANDS[name]:
                for candidate in [root/command,root/(command+'.exe'),root/name/(command+'.exe'),root/name/command]:
                    if candidate.is_file(): return str(candidate.resolve())
        for command in EngineRegistry.COMMANDS[name]:
            found = shutil.which(command)
            if found: return found
        candidates = []
        if sys.platform == 'darwin':
            candidates += [Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')] if name=='libreoffice' else []
            candidates += [Path(prefix)/command for prefix in ['/opt/homebrew/bin','/usr/local/bin']
                           for command in EngineRegistry.COMMANDS[name]]
        if os.name == 'nt':
            for variable in ['ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA']:
                root = Path(os.environ.get(variable,'C:/Program Files'))
                if name=='libreoffice': candidates.append(root/'LibreOffice/program/soffice.exe')
                if name=='tesseract': candidates.append(root/'Tesseract-OCR/tesseract.exe')
                if name=='ghostscript': candidates.extend(sorted(root.glob('gs/gs*/bin/gswin64c.exe'),reverse=True))
        return next((str(path) for path in candidates if path.is_file()),None)

    @staticmethod
    def configure():
        import pytesseract
        path = EngineRegistry.find('tesseract')
        pytesseract.pytesseract.tesseract_cmd = path or 'tesseract'

    @staticmethod
    def status():
        rows=[]
        for name in EngineRegistry.COMMANDS:
            path = EngineRegistry.find(name)
            rows.append({'name':name,'path':path,'version':AppConfig.get_command_version(path) if path else 'Not installed'})
        try:
            EngineRegistry.configure()
            import pytesseract
            languages = pytesseract.get_languages(config='') if EngineRegistry.find('tesseract') else []
        except Exception:
            languages=[]
        return {'engines':rows,'languages':languages}
