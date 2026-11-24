"""Fill PDF fields without flattening them or modifying imported snapshots."""
import fitz

SUPPORTED = {fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX,
             fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON}


def inspect_fields(path, page_number=None):
    fields = []
    with fitz.open(path) as document:
        for page in document:
            if page_number is not None and page.number != page_number:
                continue
            for widget in page.widgets() or []:
                fields.append({'page': page.number, 'name': widget.field_name,
                               'value': widget.field_value or '', 'type': widget.field_type,
                               'choices': widget.choice_values or [],
                               'on_state': widget.on_state() if widget.field_type in (2, 5) else None,
                               'editable': widget.field_type in SUPPORTED and not widget.field_flags & 1})
    return fields


def fill_document(document, values):
    found = set()
    for page in document:
        for widget in page.widgets() or []:
            name = widget.field_name
            if name not in values:
                continue
            if widget.field_type not in SUPPORTED or widget.field_flags & 1:
                raise ValueError(f'The field {name} is read-only or unsupported.')
            value = values[name]
            if widget.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                allowed = {'Off', widget.on_state()}
                if value not in allowed:
                    raise ValueError(f'Invalid choice for {name}.')
            if widget.choice_values and value not in widget.choice_values:
                raise ValueError(f'Choose one of the available values for {name}.')
            widget.field_value = value
            widget.update()
            found.add(name)
    missing = set(values) - found
    if missing:
        raise ValueError('Form fields no longer exist: ' + ', '.join(sorted(missing)))


def fill_page(page, values):
    for widget in page.widgets() or []:
        if widget.field_name in values:
            widget.field_value = values[widget.field_name]
            widget.update()
