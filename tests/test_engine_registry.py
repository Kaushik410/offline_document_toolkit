from pathlib import Path
from unittest.mock import patch

from utils.app_config import AppConfig
from utils.engine_registry import EngineRegistry


def test_explicit_engine_location_survives_settings_and_configures_ocr(tmp_path,monkeypatch):
    monkeypatch.setattr(AppConfig,'CONFIG_FILE',tmp_path/'settings.json')
    engine=tmp_path/'custom-ocr';engine.write_text('synthetic executable');engine.chmod(0o755)
    config=AppConfig.load_config();config['engine_paths']={'tesseract':str(engine)}
    AppConfig.save_config(config)
    with patch('shutil.which',return_value=None):
        assert EngineRegistry.find('tesseract')==str(engine.resolve())
        EngineRegistry.configure()
        import pytesseract
        assert pytesseract.pytesseract.tesseract_cmd==str(engine.resolve())
    # A removed configured executable must fall back rather than remain active.
    engine.unlink()
    with patch.object(EngineRegistry,'find',return_value=None):
        EngineRegistry.configure()
        assert pytesseract.pytesseract.tesseract_cmd=='tesseract'


def test_output_settings_preserve_engine_locations_and_last_project(qapp,tmp_path,monkeypatch):
    from ui.settings_page import SettingsPage
    monkeypatch.setattr(AppConfig,'CONFIG_FILE',tmp_path/'settings.json')
    page=SettingsPage()
    updated=AppConfig.load_config()
    updated.update(engine_paths={'tesseract':'/custom/ocr'},last_project='saved-project',setup_complete=True)
    AppConfig.save_config(updated)
    page.output_folder_input.setText(str(tmp_path/'new-output'))
    with patch('ui.settings_page.QMessageBox.information'):
        page.save_settings()
    config=AppConfig.load_config()
    assert config['engine_paths']=={'tesseract':'/custom/ocr'}
    assert config['last_project']=='saved-project' and config['setup_complete']
    from utils.task_controller import cancel_tasks
    cancel_tasks(page);page.close()
