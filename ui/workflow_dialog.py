from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QSpinBox,
    QCheckBox,QDialogButtonBox,QPushButton,QInputDialog,QMessageBox,QLabel,QScrollArea,QWidget)
from services.workflow_service import DEFAULT_RECIPE,STAGES,validate_recipe


class WorkflowDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.recipe=None
        self.setWindowTitle('Prepare documents for submission');self.resize(530,720)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Choose the steps and requirements. Exports are staged for review.'))
        body=QWidget();form=QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);layout.addWidget(scroll,1)
        self.presets=QComboBox();self.presets.addItem('Prepare for submission',dict(DEFAULT_RECIPE))
        for row in store.workflows():self.presets.addItem(row['name'],row['recipe'])
        form.addRow('Saved workflow',self.presets)
        self.steps={}
        for name,label in [('clean','Clean scan images'),('ocr','Recognize scanned text'),('compress','Optimize file size'),
                           ('merge','Merge all pages into one PDF'),('rename','Use the output name'),('export','Validate and export')]:
            check=QCheckBox(label);self.steps[name]=check;form.addRow(check)
        self.steps['export'].setEnabled(False)
        self.name=QLineEdit();form.addRow('Output name',self.name)
        self.format=QComboBox();self.format.addItems(['pdf','jpg','png']);form.addRow('Export format',self.format)
        self.controls={}
        for key,label,maximum in [('max_kb','Maximum KB (0 = unlimited)',10000000),('max_pages','Maximum packet pages (0 = unlimited)',100000),
            ('width','Image width in pixels (0 = original)',20000),('height','Image height in pixels (0 = original)',20000),
            ('min_quality','Minimum image quality',95),('min_dpi','Minimum export DPI',600),('ocr_dpi','OCR recognition DPI',600),('confidence_threshold','Review confidence below',100)]:
            spin=QSpinBox();spin.setRange(0,maximum);form.addRow(label,spin);self.controls[key]=spin
        self.controls['min_quality'].setMinimum(10);self.controls['min_dpi'].setMinimum(72);self.controls['ocr_dpi'].setMinimum(150)
        self.language=QComboBox();self.language.setEditable(True);self.language.addItems(['eng','hin','eng+hin']);form.addRow('OCR language',self.language)
        self.ocr_layout=QComboBox();self.ocr_layout.addItems(['auto','block','columns','sparse']);form.addRow('OCR page layout',self.ocr_layout)
        self.flags={}
        for key,label in [('auto_rotate','Correct recognition orientation'),('deskew','Deskew before recognition'),
                          ('adaptive_ocr','Retry uncertain OCR regions'),('review_ocr','Review uncertain OCR words'),('review_before_export','Review packet before publishing')]:
            check=QCheckBox(label);self.flags[key]=check;form.addRow(check)
        self.privacy={}
        for key,label in [('remove_metadata','Remove document metadata'),('remove_comments','Remove comments and annotations'),('remove_attachments','Remove embedded attachments')]:
            check=QCheckBox(label);self.privacy[key]=check;form.addRow(check)
        note=QLabel('OCR correction affects recognition only; original page graphics are preserved.\n'
                    'Image effects in the workspace rasterize those pages. Form pages reject image effects.\n'
                    'Without Merge, PDF export creates one file per page.')
        note.setWordWrap(True);layout.addWidget(note)
        save=QPushButton('Save these settings as a workflow');save.clicked.connect(self.save_preset);layout.addWidget(save)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Choose output folder and queue')
        buttons.accepted.connect(self.accept_recipe);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.presets.currentIndexChanged.connect(self.load_selected);self.format.currentTextChanged.connect(self.format_changed)
        self.load_selected()

    def load_selected(self):
        value=validate_recipe(self.presets.currentData() or DEFAULT_RECIPE)
        for name,check in self.steps.items():check.setChecked(name in value['steps'])
        self.name.setText(value['output_name']);self.format.setCurrentText(value['format'])
        for key,spin in self.controls.items():spin.setValue(value['max_bytes']//1024 if key=='max_kb' else value[key])
        self.language.setCurrentText(value['language']);self.ocr_layout.setCurrentText(value['ocr_layout'])
        for key,check in self.privacy.items():check.setChecked(value['privacy'][key])
        for key,check in self.flags.items():check.setChecked(value[key])
        self.format_changed()

    def format_changed(self):
        image=self.format.currentText()!='pdf'
        for key in ('width','height'):
            self.controls[key].setEnabled(image)
            if not image:self.controls[key].setValue(0)
        self.steps['merge'].setEnabled(not image)

    def value(self):
        value=dict(DEFAULT_RECIPE,steps=[key for key in STAGES if self.steps[key].isChecked()],
                   output_name=self.name.text(),format=self.format.currentText(),language=self.language.currentText())
        for key,spin in self.controls.items():value['max_bytes' if key=='max_kb' else key]=spin.value()*1024 if key=='max_kb' else spin.value()
        value.update({key:check.isChecked() for key,check in self.flags.items()})
        value['ocr_layout']=self.ocr_layout.currentText();value['privacy']={key:check.isChecked() for key,check in self.privacy.items()}
        return validate_recipe(value)

    def accept_recipe(self):
        try:self.recipe=self.value()
        except ValueError as error:QMessageBox.warning(self,'Check workflow',str(error));return
        self.accept()

    def save_preset(self):
        name,ok=QInputDialog.getText(self,'Save workflow','Workflow name:')
        if not ok:return
        try:
            value=self.value();self.store.save_workflow(name,value)
        except ValueError as error:QMessageBox.warning(self,'Check workflow',str(error));return
        self.presets.addItem(name,value);self.presets.setCurrentIndex(self.presets.count()-1)
