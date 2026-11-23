"""Open the disposable upgrade fixture in the real application and preserve its state."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

FIXTURE_ID='upgrade-fixture'


def run(data_directory,report_file):
    from utils.version import VERSION
    report={'version':VERSION,'passed':False,'runtime':{'frozen':bool(getattr(sys,'frozen',False))},'checks':[]}
    window=None
    try:
        data=Path(data_directory).resolve();database=data/'workspace.sqlite3'
        if not database.is_file():raise ValueError('The disposable upgrade fixture is missing.')
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            if not db.execute('SELECT 1 FROM projects WHERE id=?',(FIXTURE_ID,)).fetchone():
                raise ValueError('This command only accepts a disposable upgrade-fixture workspace.')
        os.environ.update(ODT_DATA_DIR=str(data),ODT_CONFIG_DIR=str(data.parent),ODT_NO_SETUP='1')
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from utils.qt_runtime import configure_qt_plugins
        configure_qt_plugins()
        from PySide6.QtWidgets import QApplication,QMessageBox
        from PySide6.QtCore import Qt
        from ui.main_window import MainWindow
        from utils.app_config import AppConfig
        from utils.task_controller import shutdown_tasks
        from services.workspace_service import assemble_workspace
        from services.validation_service import ValidationService
        config=AppConfig.load_config();config['last_project']=FIXTURE_ID;config['setup_complete']=True;AppConfig.save_config(config)
        app=QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        errors=[]
        # Diagnostics run unattended; report any GUI error instead of blocking
        # the CI process behind an offscreen modal message box.
        QMessageBox.critical=lambda parent,title,message:errors.append(str(message))
        window=MainWindow();window.show()
        page=window.workspace_page
        deadline=time.monotonic()+40
        while page.preview_image is None and not errors and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        if errors:raise RuntimeError('; '.join(errors))
        if page.preview_image is None:raise RuntimeError('The saved project did not render in the installed app.')
        if page.project_id!=FIXTURE_ID or page.project_name.text()!='Preserved upgrade project':
            raise RuntimeError('The saved project was not reopened.')
        if page.model.document['pages'][0]['rotation']!=90:raise RuntimeError('The saved page edit was lost.')
        page.undo()
        if page.model.document['pages'][0]['rotation']!=0:raise RuntimeError('Undo history was lost during upgrade.')
        page.redo()
        if page.model.document['pages'][0]['rotation']!=90:raise RuntimeError('Redo history was lost during upgrade.')
        report['checks'].append('Installed GUI reopens the saved project, renders it, and preserves undo/redo')
        output=Path(config['default_output_folder'])/'upgrade-probe.pdf'
        assemble_workspace(page.model.document,output)
        inspected=ValidationService.inspect_pdf(output)
        if inspected['pages']!=1 or 'UPGRADE FIXTURE' not in ''.join(inspected['text']):
            raise RuntimeError('The reopened project could not be exported.')
        report['checks'].append('The reopened project exports readable content')
        window.close();shutdown_tasks()
        report['passed']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        if window:
            window.close()
            from utils.task_controller import shutdown_tasks
            shutdown_tasks()
    target=Path(report_file);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if sys.stdout:print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1
