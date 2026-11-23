"""Reversible workspace edits stored as compact commands, with v0.3 migration."""
import copy
import uuid


def empty_document():
    return {'assets': {}, 'pages': []}


class WorkspaceModel:
    LIMIT = 100

    def __init__(self, document=None):
        saved = copy.deepcopy(document) if document else empty_document()
        self.base = empty_document()
        self.commands = []
        self.position = 0
        self.document = empty_document()
        if saved.get('format') == 2:
            self.base = saved['base']
            self.document = copy.deepcopy(self.base)
            self.commands = saved['commands']
            if not 0 <= saved['position'] <= len(self.commands):
                raise ValueError('Invalid workspace history position.')
            for command in self.commands[:saved['position']]:
                self._apply(command, True)
            self.position = saved['position']
        elif 'history' in saved:
            # Old snapshots remain undoable, then naturally expire as new edits
            # reach the history limit. New projects never create snapshots.
            history = saved['history']
            self.base = copy.deepcopy(history[0])
            self.commands = [{'kind': 'legacy', 'before': before, 'after': after}
                             for before, after in zip(history, history[1:])]
            self.position = saved['position']
            self.document = copy.deepcopy(history[self.position])
        else:
            self.base = saved
            self.document = copy.deepcopy(saved)

    @property
    def history(self):
        # Existing toolbar code only uses the history length.
        return [None] * (len(self.commands) + 1)

    def serialize(self):
        return copy.deepcopy({'format': 2, 'base': self.base,
                              'commands': self.commands, 'position': self.position})

    def _apply(self, command, forward):
        kind = command['kind']
        value = 'after' if forward else 'before'
        if kind == 'batch':
            for child in command['commands'] if forward else reversed(command['commands']):self._apply(child,forward)
        elif kind == 'legacy':
            self.document = copy.deepcopy(command[value])
        elif kind == 'import':
            if forward:
                self.document['assets'].update(copy.deepcopy(command['assets']))
                self.document['pages'].extend(copy.deepcopy(command['pages']))
            else:
                ids = {page['id'] for page in command['pages']}
                self.document['pages'] = [page for page in self.document['pages'] if page['id'] not in ids]
                for key in command['assets']:
                    self.document['assets'].pop(key, None)
        elif kind == 'remove':
            if forward:
                ids = {row['page']['id'] for row in command['rows']}
                self.document['pages'] = [page for page in self.document['pages'] if page['id'] not in ids]
            else:
                for row in command['rows']:
                    self.document['pages'].insert(row['index'], copy.deepcopy(row['page']))
        elif kind == 'order':
            pages = {page['id']: page for page in self.document['pages']}
            self.document['pages'] = [pages[key] for key in command[value]]
        elif kind == 'page':
            index = next(i for i, page in enumerate(self.document['pages']) if page['id'] == command['id'])
            self.document['pages'][index] = copy.deepcopy(command[value])
        elif kind == 'value':
            target = self.document
            for key in command['path'][:-1]:
                target = target[key]
            if command[value] is None:
                target.pop(command['path'][-1], None)
            else:
                target[command['path'][-1]] = copy.deepcopy(command[value])
        else:
            raise ValueError('Unsupported workspace edit.')

    def _commit(self, command):
        self.commands = self.commands[:self.position]
        self._apply(command, True)
        self.commands.append(command)
        self.position += 1
        if len(self.commands) > self.LIMIT:
            current = self.document
            self.document = self.base
            self._apply(self.commands.pop(0), True)
            self.base = self.document
            self.document = current
            self.position -= 1

    def undo(self):
        if self.position:
            self.position -= 1
            self._apply(self.commands[self.position], False)

    def redo(self):
        if self.position < len(self.commands):
            self._apply(self.commands[self.position], True)
            self.position += 1

    def import_assets(self, assets):
        added, pages = {}, []
        for asset in assets:
            key = uuid.uuid4().hex
            added[key] = copy.deepcopy(asset)
            added[key].setdefault('role', 'unassigned')
            for index in range(asset['page_count']):
                pages.append({'id': uuid.uuid4().hex, 'asset': key, 'page': index,
                              'rotation': 0, 'crop': None, 'edits': [], 'redactions': []})
        if added:
            self._commit({'kind': 'import', 'assets': added, 'pages': pages})

    def reorder(self, ids):
        before = [page['id'] for page in self.document['pages']]
        if len(ids) != len(before) or set(ids) != set(before):
            raise ValueError('Invalid page order')
        if ids != before:
            self._commit({'kind': 'order', 'before': before, 'after': list(ids)})

    def edit(self, page_id, operation):
        before = next(page for page in self.document['pages'] if page['id'] == page_id)
        after = copy.deepcopy(before)
        kind = operation['operation']
        if kind == 'rotate':
            if after['edits']:
                after['edits'].append({'operation': 'rotate', 'params': {'angle': operation['angle']}})
            else:
                after['rotation'] = (after['rotation'] + operation['angle']) % 360
        elif kind == 'crop_pdf':
            after['crop'] = operation['rect']
        elif kind == 'redact':
            after.setdefault('redactions', []).append(operation['rect'])
        else:
            after['edits'].append(copy.deepcopy(operation))
        self._commit({'kind': 'page', 'id': page_id, 'before': copy.deepcopy(before), 'after': after})

    def set_value(self, path, value):
        target = self.document
        for key in path[:-1]:
            target = target[key]
        before = copy.deepcopy(target.get(path[-1]))
        if before != value:
            self._commit({'kind': 'value', 'path': list(path), 'before': before, 'after': copy.deepcopy(value)})

    def set_many_values(self,changes):
        commands=[]
        for path,value in changes:
            target=self.document
            for key in path[:-1]:target=target[key]
            before=copy.deepcopy(target.get(path[-1]))
            if before!=value:commands.append({'kind':'value','path':list(path),'before':before,'after':copy.deepcopy(value)})
        if commands:self._commit({'kind':'batch','commands':commands})

    def remove(self, page_ids):
        rows = [{'index': index, 'page': copy.deepcopy(page)} for index, page in enumerate(self.document['pages'])
                if page['id'] in page_ids]
        if rows:
            self._commit({'kind': 'remove', 'rows': rows})
