"""Test adapter safety even on hosts where LibreOffice cannot bind local IPC."""
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import fitz
import pytest
from docx import Document
from services.word_service import WordService


@pytest.fixture
def office_adapter(tmp_path,monkeypatch):
    source=tmp_path/'synthetic.docx';document=Document();document.add_paragraph('Example');document.save(source)
    monkeypatch.setattr(WordService,'_find_libreoffice',lambda:'test-libreoffice')
    monkeypatch.setattr('services.word_service.socket.socket',MagicMock())
    return source


def test_libreoffice_uses_new_profile_and_atomic_output(office_adapter,tmp_path,monkeypatch):
    source=office_adapter;calls=[]
    def convert(command,**kwargs):
        calls.append((command,kwargs))
        folder=Path(command[command.index('--outdir')+1])
        with fitz.open() as document:
            page=document.new_page();page.insert_text((30,30),'Example')
            document.save(folder/'synthetic.pdf')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr('services.word_service.subprocess.run',convert)
    output=WordService.docx_to_pdf(source,tmp_path/'out')
    assert Path(output).is_file()
    command,options=calls[0]
    assert any(arg.startswith('-env:UserInstallation=file:') for arg in command)
    assert options['timeout']==120
    assert options['env']['GSETTINGS_BACKEND']=='memory'


def test_stale_output_cannot_be_reported_as_success(office_adapter,tmp_path,monkeypatch):
    folder=tmp_path/'out';folder.mkdir()
    original=folder/'synthetic.pdf';original.write_bytes(b'existing output')
    monkeypatch.setattr('services.word_service.subprocess.run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='',stderr=''))
    with pytest.raises(RuntimeError,match='conversion failed'):
        WordService.docx_to_pdf(office_adapter,folder)
    assert original.read_bytes()==b'existing output'


def test_libreoffice_timeout_is_actionable(office_adapter,tmp_path,monkeypatch):
    def timeout(*args,**kwargs):
        raise subprocess.TimeoutExpired('test-libreoffice',120)
    monkeypatch.setattr('services.word_service.subprocess.run',timeout)
    with pytest.raises(RuntimeError,match='timed out'):
        WordService.docx_to_pdf(office_adapter,tmp_path/'out')
