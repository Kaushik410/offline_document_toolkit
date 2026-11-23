from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,
    QHBoxLayout,QPushButton,QFileDialog,QMessageBox)
from utils.engine_registry import EngineRegistry
from utils.app_config import AppConfig
from utils.task_controller import run_task


class SetupDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Set up local document engines');self.resize(850,470)
        layout=QVBoxLayout(self)
        info=QLabel('PDF and image tools work immediately. Enable OCR and Word conversion by locating installed engines.\n'
                    'Common installation folders are detected automatically; no PATH changes are needed.\n'
                    'The Linux installer can install engines through the system package manager.')
        info.setWordWrap(True);layout.addWidget(info)
        self.table=QTableWidget(4,3);self.table.setHorizontalHeaderLabels(['Engine','Status','Location'])
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row,name in enumerate(EngineRegistry.COMMANDS):
            self.table.setItem(row,0,QTableWidgetItem(name));self.table.setItem(row,1,QTableWidgetItem('Checking…'))
        self.table.selectRow(0);layout.addWidget(self.table)
        self.languages=QLabel('Checking installed OCR language packs…');layout.addWidget(self.languages)
        row=QHBoxLayout();layout.addLayout(row)
        for label,callback in [('Locate executable…',self.locate),('Official installation guide',self.guide),('Refresh',self.refresh),('Continue',self.finish)]:
            button=QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        self.refresh()

    def refresh(self):
        run_task(self,EngineRegistry.status,on_success=self.show_status,show_progress=False)

    def show_status(self,result):
        for index,row in enumerate(result['engines']):
            self.table.setItem(index,1,QTableWidgetItem('Ready' if row['path'] else 'Optional — not installed'))
            self.table.setItem(index,2,QTableWidgetItem(row['path'] or 'Use Locate or the installation guide'))
        self.languages.setText('OCR languages: '+(', '.join(result['languages']) or 'none detected')+
            '\nFor English/Hindi OCR, install the eng and hin language packs.')

    def engine(self):return list(EngineRegistry.COMMANDS)[max(0,self.table.currentRow())]
    def locate(self):
        path,_=QFileDialog.getOpenFileName(self,'Locate '+self.engine())
        if path:
            config=AppConfig.load_config();config.setdefault('engine_paths',{})[self.engine()]=path
            AppConfig.save_config(config);EngineRegistry.configure();self.refresh()
    def guide(self):QDesktopServices.openUrl(QUrl(EngineRegistry.URLS[self.engine()]))
    def finish(self):
        config=AppConfig.load_config();config['setup_complete']=True;AppConfig.save_config(config);self.accept()
