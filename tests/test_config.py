import json
from pathlib import Path
from utils.app_config import AppConfig


def test_config_is_independent_of_working_directory(tmp_path,monkeypatch):
    config=tmp_path/'profile'/'settings.json'
    monkeypatch.setattr(AppConfig,'CONFIG_FILE',config)
    AppConfig.save_config({'default_output_folder':str(tmp_path/'custom')})
    other=tmp_path/'other';other.mkdir();monkeypatch.chdir(other)
    assert AppConfig.load_config()['default_output_folder']==str(tmp_path/'custom')
    assert not (other/'app_settings.json').exists()


def test_invalid_config_falls_back_without_overwriting_it(tmp_path,monkeypatch):
    config=tmp_path/'settings.json';monkeypatch.setattr(AppConfig,'CONFIG_FILE',config)
    for value in ['{invalid','[]','{"default_output_folder": null}','{"default_output_folder": 123}']:
        config.write_text(value)
        assert AppConfig.load_config()==AppConfig.DEFAULT_CONFIG
        assert config.read_text()==value
