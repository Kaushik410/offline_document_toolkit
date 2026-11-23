from pathlib import Path
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap,QPainter,QPen,QColor
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QTableWidget,QTableWidgetItem,
    QPushButton,QSplitter,QHeaderView,QCheckBox,QMessageBox)
from services.ocr_pipeline import write_json


class OCRReviewDialog(QDialog):
    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=Path(path)
        self.review=json.loads(self.path.read_text(encoding='utf-8'));self.page_index=0;self.loading=False
        self.setWindowTitle('Review recognized text');self.resize(1100,730)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Edit uncertain words, inspect their highlighted area, then approve the reviewed text.'))
        row=QHBoxLayout();layout.addLayout(row)
        self.page=QComboBox();self.page.addItems([f'Page {i+1}' for i in range(len(self.review['pages']))]);row.addWidget(self.page)
        self.only_uncertain=QCheckBox('Show uncertain words only');row.addWidget(self.only_uncertain);row.addStretch()
        self.correction=QLabel();row.addWidget(self.correction)
        split=QSplitter();layout.addWidget(split,1)
        self.preview=QLabel();self.preview.setAlignment(Qt.AlignCenter);self.preview.setMinimumWidth(420);split.addWidget(self.preview)
        self.words=QTableWidget(0,2);self.words.setHorizontalHeaderLabels(['Recognized / corrected word','Confidence'])
        self.words.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);split.addWidget(self.words)
        self.words.itemChanged.connect(self.word_changed);self.words.currentCellChanged.connect(self.highlight)
        self.page.currentIndexChanged.connect(self.load_page);self.only_uncertain.toggled.connect(self.load_page)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        save=QPushButton('Save and approve OCR');save.clicked.connect(self.approve)
        close=QPushButton('Close without approval');close.clicked.connect(self.reject)
        buttons.addStretch();buttons.addWidget(close);buttons.addWidget(save)
        self.load_page()

    def load_page(self,*args):
        self.loading=True;self.page_index=self.page.currentIndex();page=self.review['pages'][self.page_index]
        self.words.setRowCount(0)
        for index,word in enumerate(page['words']):
            if self.only_uncertain.isChecked() and not word['uncertain']:continue
            row=self.words.rowCount();self.words.insertRow(row)
            item=QTableWidgetItem(word['text']);item.setData(Qt.UserRole,index)
            if word['uncertain']:item.setBackground(QColor('#fef3c7'))
            self.words.setItem(row,0,item)
            confidence=QTableWidgetItem(f"{word['confidence']:.0f}");confidence.setFlags(confidence.flags()&~Qt.ItemIsEditable)
            self.words.setItem(row,1,confidence)
        correction=page['corrections']
        self.correction.setText(f"Recognition rotation: {correction['rotation']}°; deskew: {correction['deskew_degrees']:.1f}°")
        self.loading=False;self.highlight()

    def word_changed(self,item):
        if self.loading or item.column()!=0:return
        self.review['pages'][self.page_index]['words'][item.data(Qt.UserRole)]['text']=item.text()

    def highlight(self,*args):
        page=self.review['pages'][self.page_index];pixmap=QPixmap(page['image'])
        if pixmap.isNull():return
        row=self.words.currentRow()
        painter=QPainter(pixmap);painter.setPen(QPen(QColor('#dc2626'),3))
        for index,word in enumerate(page['words']):
            selected=row>=0 and self.words.item(row,0) and self.words.item(row,0).data(Qt.UserRole)==index
            if word['uncertain'] or selected:
                x,y,w,h=word['bbox'];painter.drawRect(x,y,w,h)
        painter.end();self.preview.setPixmap(pixmap.scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'words'):self.highlight()

    def approve(self):
        self.review['approved']=True;write_json(self.path,self.review);self.accept()
