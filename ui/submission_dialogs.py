"""Editable packet checklists and native PDF form fields."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QTableWidget,
    QTableWidgetItem,QDialogButtonBox,QMessageBox,QLabel,QHeaderView,QLineEdit)
from services.submission_service import PROFILES,validate_requirements
from services.form_service import inspect_fields


class ChecklistDialog(QDialog):
    def __init__(self,current,parent=None):
        super().__init__(parent);self.setWindowTitle('Submission checklist');self.resize(600,450)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Define the document roles required by this packet. These are editable examples.'))
        self.profile=QComboBox();self.profile.addItems(PROFILES);layout.addWidget(self.profile)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Required document role','Minimum documents'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);layout.addWidget(self.table)
        row=QHBoxLayout();layout.addLayout(row)
        add=QPushButton('Add role');add.clicked.connect(lambda:self.add_row('supporting',1));row.addWidget(add)
        delete=QPushButton('Remove selected');delete.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()));row.addWidget(delete)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)
        self.profile.currentTextChanged.connect(lambda name:self.populate(PROFILES[name]));self.populate(current)
        self.requirements=None

    def add_row(self,role,minimum):
        row=self.table.rowCount();self.table.insertRow(row)
        self.table.setItem(row,0,QTableWidgetItem(role));self.table.setItem(row,1,QTableWidgetItem(str(minimum)))

    def populate(self,rows):
        self.table.setRowCount(0)
        for row in rows:self.add_row(row['role'],row['minimum'])

    def save(self):
        try:
            rows=[{'role':self.table.item(row,0).text(),'minimum':int(self.table.item(row,1).text())} for row in range(self.table.rowCount())]
            self.requirements=validate_requirements(rows)
        except (ValueError,AttributeError) as error:QMessageBox.warning(self,'Check document roles',str(error));return
        self.accept()


class FormFieldsDialog(QDialog):
    def __init__(self,fields,values=None,parent=None):
        super().__init__(parent);self.setWindowTitle('Fill PDF form fields');self.resize(650,500)
        self.fields=fields;self.values=dict(values or {});self.controls={}
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Fields stay editable in the exported PDF. Signature and read-only fields are preserved.'))
        table=QTableWidget(0,2);table.setHorizontalHeaderLabels(['Field','Value']);table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        layout.addWidget(table)
        seen=set()
        for field in fields:
            if field['name'] in seen:continue
            seen.add(field['name']);row=table.rowCount();table.insertRow(row)
            item=QTableWidgetItem(f"{field['name']} (page {field['page']+1})");item.setFlags(item.flags()&~Qt.ItemIsEditable);table.setItem(row,0,item)
            value=self.values.get(field['name'],field['value'])
            choices=list(field['choices'])
            if field['on_state']:choices=['Off',field['on_state']]
            if choices:
                control=QComboBox();control.addItems([str(choice) for choice in choices]);control.setCurrentText(str(value))
            else:control=QLineEdit(str(value))
            control.setEnabled(field['editable']);table.setCellWidget(row,1,control)
            if field['editable']:self.controls[field['name']]=control
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)

    def save(self):
        self.values.update({name:control.currentText() if isinstance(control,QComboBox) else control.text() for name,control in self.controls.items()})
        self.accept()
