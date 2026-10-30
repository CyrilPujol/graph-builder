"""Compact Qt editors for inherited graph appearance."""
from __future__ import annotations

import json
from copy import deepcopy

from PySide6.QtCore import Qt, QRectF, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget, QInputDialog)

from graph_styles import (FIELDS, effective_style, palette_styles, presets,
                          contrast_text_color, remove_preset, set_overrides,
                          set_palette_style, set_preset)


SPECS = {
    'vertex': {
        'fill': ('Fill', 'color'), 'outline': ('Outline', 'color'),
        'shape': ('Shape', ('circle', 'square', 'diamond', 'triangle',
                           'hollow_circle', 'hollow_square', 'hollow_diamond',
                           'hollow_triangle', 'none')),
        'size': ('Diameter', (4, 200, 1)),
        'outline_width': ('Outline width', (0, 20, .5)),
        'text': ('Text color', 'color'),
        'latex_label': ('Label is LaTeX', (False, True)),
        'tikz_options': ('Extra TikZ node options', 'text'),
    },
    'edge': {
        'stroke': ('Stroke', 'color'), 'width': ('Width', (.5, 20, .5)),
        'pattern': ('Pattern', ('solid', 'dash', 'dot', 'dashdot')),
        'opacity': ('Opacity', (0, 1, .05)),
        'label_t': ('Label position', (0, 1, .05)),
        'label_offset': ('Label offset', (-100, 100, 1)),
        'latex_label': ('Label is LaTeX', (False, True)),
        'tikz_options': ('Extra TikZ draw options', 'text'),
    },
}


class StylePreview(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setMinimumHeight(74)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#fafafa'))
        style = self.dialog.preview_style()
        middle = self.rect().center()
        if self.dialog.kind == 'vertex':
            size = min(float(style['size']), 55)
            shape = style['shape']
            fill = style['fill']
            if shape.startswith('hollow_'):
                fill = 'none'
                shape = shape[7:]
            painter.setBrush(Qt.NoBrush if fill == 'none' else QColor(fill))
            painter.setPen(QPen(QColor(style['outline']), float(style['outline_width'])))
            rect = QRectF(middle.x()-size/2, middle.y()-size/2, size, size)
            if shape == 'circle':
                painter.drawEllipse(rect)
            elif shape == 'square':
                painter.drawRect(rect)
            elif shape in ('diamond', 'triangle'):
                from PySide6.QtGui import QPolygonF
                from PySide6.QtCore import QPointF
                points = ([QPointF(middle.x(), rect.top()), QPointF(rect.right(), middle.y()),
                           QPointF(middle.x(), rect.bottom()), QPointF(rect.left(), middle.y())]
                          if shape == 'diamond' else
                          [QPointF(middle.x(), rect.top()), QPointF(rect.right(), rect.bottom()),
                           QPointF(rect.left(), rect.bottom())])
                painter.drawPolygon(QPolygonF(points))
            painter.setPen(QColor(style['text']) if style['text'] != 'auto' else QColor(contrast_text_color(fill)))
            label = self.dialog.label_edit.text() if self.dialog.label_edit is not None else 'A'
            painter.drawText(self.rect(), Qt.AlignCenter, label[:12])
        else:
            pen = QPen(QColor(style['stroke']), float(style['width']))
            pen.setStyle({'solid': Qt.SolidLine, 'dash': Qt.DashLine,
                          'dot': Qt.DotLine, 'dashdot': Qt.DashDotLine}[style['pattern']])
            painter.setOpacity(float(style['opacity']))
            painter.setPen(pen)
            painter.drawLine(25, middle.y(), self.width()-25, middle.y())
        painter.end()


class PropertiesDialog(QDialog):
    advanced_open = False

    def __init__(self, graph, kind, attributes, *, bulk=False, style_only=False, parent=None):
        super().__init__(parent)
        self.graph, self.kind = graph, kind
        self.attributes = list(attributes)
        self.bulk, self.style_only = bulk, style_only
        self.type_delta = 0
        self.look_mode = None
        self._look_touched = False
        self.setWindowTitle(f'{"Vertex" if kind == "vertex" else "Edge"} properties')
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        self.label_edit = None
        if not bulk and not style_only:
            label_row = QHBoxLayout()
            label_row.addWidget(QLabel('Label'))
            self.label_edit = QLineEdit(str(self.attributes[0].get('label', '')))
            label_row.addWidget(self.label_edit)
            layout.addLayout(label_row)
        if not style_only:
            type_row = QHBoxLayout()
            type_row.addWidget(QLabel('Type'))
            self.type_label = QLabel()
            type_row.addWidget(self.type_label, 1)
            step = QWidget()
            step.setObjectName('type_step')
            step.setStyleSheet('QWidget#type_step { border: 1px solid #b8bec4; border-radius: 5px; } '
                               'QToolButton { border: none; color: #111111; font-size: 17px; }')
            step_layout = QHBoxLayout(step)
            step_layout.setContentsMargins(2, 1, 2, 1)
            step_layout.setSpacing(0)
            for text, delta in (('−', -1), ('+', 1)):
                button = QToolButton(step)
                button.setText(text)
                button.setFixedSize(29, 27)
                button.clicked.connect(lambda _, change=delta: self.change_type(change))
                step_layout.addWidget(button)
            type_row.addWidget(step)
            layout.addLayout(type_row)
            self._update_type_label()
        self.preset_choice = None
        toggle = QToolButton()
        toggle.setText('Advanced ▾')
        toggle.setCheckable(True)
        toggle.setChecked(style_only or PropertiesDialog.advanced_open)
        toggle.setVisible(not style_only)
        layout.addWidget(toggle)
        advanced_widget = QWidget()
        advanced_layout = QVBoxLayout(advanced_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        if not style_only:
            self.look_mode = QComboBox()
            if bulk:
                self.look_mode.addItem('Keep existing looks', 'keep')
            self.look_mode.addItem(self._inherit_text(), 'inherit')
            self.look_mode.addItem('Custom look', 'custom')
            if presets(graph, kind):
                self.look_mode.addItem('Named preset', 'preset')
            if not bulk:
                first = self.attributes[0]
                mode = ('preset' if first.get('style_preset') else
                        'custom' if first.get('style_overrides') else 'inherit')
                self.look_mode.setCurrentIndex(self.look_mode.findData(mode))
            advanced_layout.addWidget(self.look_mode)
            self.preset_choice = QComboBox()
            for identifier, data in presets(graph, kind).items():
                self.preset_choice.addItem(data.get('name', identifier), identifier)
            current_preset = self.attributes[0].get('style_preset')
            if current_preset:
                self.preset_choice.setCurrentIndex(max(0, self.preset_choice.findData(current_preset)))
            advanced_layout.addWidget(self.preset_choice)
            self.preset_choice.setVisible(self.preset_choice.count() > 0)
        self.preview = StylePreview(self)
        advanced_layout.addWidget(self.preview)
        if self.label_edit is not None:
            self.label_edit.textChanged.connect(self.preview.update)
        if self.preset_choice is not None:
            self.preset_choice.currentIndexChanged.connect(self.preview.update)
        self.controls = {}
        self.edit_widgets = []
        fields = QFormLayout()
        for field in FIELDS[kind]:
            title, spec = SPECS[kind][field]
            row = QHBoxLayout()
            current = effective_style(graph, kind, self.attributes[0])[field]
            if spec == 'color':
                value = QLineEdit(str(current))
                value.setPlaceholderText('Hex color' + (', none' if field == 'fill' else ', auto' if field == 'text' else ''))
                choose = QPushButton('…')
                choose.setFixedWidth(30)
                choose.clicked.connect(lambda _, box=value: self._choose_color(box))
                row.addWidget(value)
                row.addWidget(choose)
                self.edit_widgets.append(choose)
                if field in ('fill', 'text'):
                    special = QPushButton('None' if field == 'fill' else 'Auto')
                    special.clicked.connect(lambda _, box=value, choice='none' if field == 'fill' else 'auto': box.setText(choice))
                    row.addWidget(special)
                    self.edit_widgets.append(special)
                value.textChanged.connect(self.preview.update)
            elif spec == 'text':
                value = QLineEdit(str(current))
                row.addWidget(value)
            elif isinstance(spec, tuple) and len(spec) == 3 and all(isinstance(x, (int, float)) for x in spec):
                value = QDoubleSpinBox()
                value.setRange(spec[0], spec[1])
                value.setSingleStep(spec[2])
                value.setDecimals(2)
                value.setValue(float(current))
                row.addWidget(value)
                value.valueChanged.connect(self.preview.update)
            else:
                value = QComboBox()
                for choice in spec:
                    value.addItem(str(choice).replace('_', ' ').title(), choice)
                value.setCurrentIndex(max(0, value.findData(current)))
                row.addWidget(value)
                value.currentIndexChanged.connect(self.preview.update)
            self.controls[field] = value
            self.edit_widgets.append(value)
            fields.addRow(title, row)
        advanced_layout.addLayout(fields)
        advanced_widget.setVisible(style_only or PropertiesDialog.advanced_open)
        toggle.toggled.connect(advanced_widget.setVisible)
        if not style_only:
            toggle.toggled.connect(lambda checked: setattr(PropertiesDialog, 'advanced_open', checked))
        layout.addWidget(advanced_widget)
        note = QLabel('Canvas preview is approximate. Extra TikZ options are exported verbatim and may fail to compile.')
        note.setWordWrap(True)
        advanced_layout.addWidget(note)
        if self.look_mode is not None:
            self.look_mode.currentIndexChanged.connect(self._sync_look)
            self._sync_look()
            self.look_mode.currentIndexChanged.connect(self._mark_look_touched)
            self.preset_choice.currentIndexChanged.connect(self._refresh_readonly_controls)
            self.preset_choice.currentIndexChanged.connect(self._mark_look_touched)
            for widget in self.controls.values():
                if isinstance(widget, QLineEdit):
                    widget.textChanged.connect(self._mark_look_touched)
                elif isinstance(widget, QDoubleSpinBox):
                    widget.valueChanged.connect(self._mark_look_touched)
                else:
                    widget.currentIndexChanged.connect(self._mark_look_touched)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _inherit_text(self):
        indices = {int(item.get('col', 0)) for item in self.attributes}
        if len(indices) == 1:
            return f'Inherit from type {(next(iter(indices)) + self.type_delta) % self._type_count()}'
        return 'Inherit from each type'

    def _type_count(self):
        return max(1, int(self.graph.graph.get(
            'num_vertex_colors' if self.kind == 'vertex' else 'num_edge_colors', 1)))

    def type_values(self):
        return [(int(item.get('col', 0)) + self.type_delta) % self._type_count()
                for item in self.attributes]

    def _update_type_label(self):
        values = set(self.type_values())
        self.type_label.setText(str(next(iter(values))) if len(values) == 1 else 'Mixed')
        if self.look_mode is not None:
            index = self.look_mode.findData('inherit')
            self.look_mode.setItemText(index, self._inherit_text())

    def change_type(self, delta):
        self.type_delta += delta
        self._update_type_label()
        self._refresh_readonly_controls()
        self.preview.update()

    def _sync_look(self):
        mode = self.look_mode.currentData()
        for widget in self.edit_widgets:
            widget.setEnabled(mode == 'custom')
        self.preset_choice.setEnabled(mode == 'preset')
        self._refresh_readonly_controls()
        self.preview.update()

    def _mark_look_touched(self, *_):
        self._look_touched = True
        self.preview.update()

    def _refresh_readonly_controls(self):
        if self.look_mode is None or self.look_mode.currentData() not in ('inherit', 'preset'):
            return
        attributes = deepcopy(self.attributes[0])
        attributes['col'] = self.type_values()[0]
        attributes.pop('style_overrides', None)
        if self.look_mode.currentData() == 'inherit':
            attributes.pop('style_preset', None)
        else:
            attributes['style_preset'] = self.preset_choice.currentData()
        style = effective_style(self.graph, self.kind, attributes)
        for field, widget in self.controls.items():
            blocker = QSignalBlocker(widget)
            value = style[field]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            else:
                widget.setText(str(value))
            del blocker

    def _choose_color(self, box):
        color = QColorDialog.getColor(QColor(box.text()) if box.text() != 'none' else QColor('white'), self)
        if color.isValid():
            box.setText(color.name())

    def changes(self):
        if self.look_mode is not None and not self._look_touched:
            return {}
        mode = self.look_mode.currentData() if self.look_mode is not None else 'custom'
        if mode == 'keep':
            return {}
        if mode in ('inherit', 'preset'):
            return {field: None for field in FIELDS[self.kind]}
        return {field: (widget.currentData() if isinstance(widget, QComboBox) else
                        widget.value() if isinstance(widget, QDoubleSpinBox) else widget.text().strip())
                for field, widget in self.controls.items()}

    def preset_change(self):
        if self.look_mode is None or not self._look_touched or self.look_mode.currentData() == 'keep':
            return None
        return self.preset_choice.currentData() if self.look_mode.currentData() == 'preset' else ''

    def preview_style(self):
        attributes = deepcopy(self.attributes[0])
        if not self.style_only:
            attributes['col'] = self.type_values()[0]
        identifier = self.preset_change()
        if identifier is not None:
            if identifier:
                attributes['style_preset'] = identifier
            else:
                attributes.pop('style_preset', None)
        set_overrides(attributes, self.changes())
        return effective_style(self.graph, self.kind, attributes)

    def _accept(self):
        if self.look_mode is not None and self.look_mode.currentData() != 'custom':
            self.accept()
            return
        for field in ('fill', 'outline', 'text', 'stroke'):
            value = self.changes().get(field)
            special = (value == 'auto' and field == 'text') or (value == 'none' and field == 'fill')
            if value is not None and not special and not (isinstance(value, str) and
                    len(value) == 7 and value.startswith('#') and QColor(value).isValid()):
                QMessageBox.warning(self, 'Invalid color', f'{field}: enter a #RRGGBB color or the offered special value.')
                return
        self.accept()


class StylesDialog(QDialog):
    """Edit palette slots and named presets on an isolated graph copy."""
    def __init__(self, graph, parent=None):
        super().__init__(parent)
        self.graph = deepcopy(graph)
        self.setWindowTitle('Shared styles')
        layout = QVBoxLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(('vertex', 'edge'))
        layout.addWidget(self.kind)
        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel('Type index'))
        self.slot = QSpinBox()
        self.slot.setMinimum(0)
        slot_row.addWidget(self.slot)
        edit_slot = QPushButton('Edit type style')
        edit_slot.clicked.connect(self.edit_palette)
        slot_row.addWidget(edit_slot)
        layout.addLayout(slot_row)
        self.preset = QComboBox()
        layout.addWidget(self.preset)
        self.kind.currentIndexChanged.connect(self.refresh)
        preset_row = QHBoxLayout()
        for title, action in (('New preset', self.new_preset), ('Edit', self.edit_preset),
                              ('Rename', self.rename_preset), ('Delete', self.delete_preset)):
            button = QPushButton(title)
            button.clicked.connect(action)
            preset_row.addWidget(button)
        layout.addLayout(preset_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        self.slot.setMaximum(max(0, int(self.graph.graph.get(
            'num_vertex_colors' if self.kind.currentText() == 'vertex' else 'num_edge_colors', 1)) - 1))
        self.preset.clear()
        for identifier, data in presets(self.graph, self.kind.currentText()).items():
            self.preset.addItem(data.get('name', identifier), identifier)

    def _edit_style(self, initial, color_index=0):
        attributes = {'col': color_index, 'style_overrides': json.dumps(initial)}
        dialog = PropertiesDialog(self.graph, self.kind.currentText(), [attributes],
                                  style_only=True, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return None
        result = dict(initial)
        for field, value in dialog.changes().items():
            if value is None:
                result.pop(field, None)
            else:
                result[field] = value
        return result

    def edit_palette(self):
        kind, index = self.kind.currentText(), self.slot.value()
        result = self._edit_style(palette_styles(self.graph, kind).get(str(index), {}), index)
        if result is not None:
            set_palette_style(self.graph, kind, index, result)

    def new_preset(self):
        name, accepted = QInputDialog.getText(self, 'New preset', 'Name:')
        if not accepted or not name.strip():
            return
        kind = self.kind.currentText()
        identifier = 'preset0'
        index = 0
        while identifier in presets(self.graph, kind):
            index += 1
            identifier = f'preset{index}'
        result = self._edit_style({})
        if result is not None:
            set_preset(self.graph, kind, identifier, name.strip(), result)
            self.refresh()
            self.preset.setCurrentIndex(self.preset.findData(identifier))

    def edit_preset(self):
        identifier = self.preset.currentData()
        if identifier is None:
            return
        kind = self.kind.currentText()
        data = presets(self.graph, kind)[identifier]
        result = self._edit_style(data['style'])
        if result is not None:
            set_preset(self.graph, kind, identifier, data['name'], result)

    def rename_preset(self):
        identifier = self.preset.currentData()
        if identifier is None:
            return
        kind = self.kind.currentText()
        data = presets(self.graph, kind)[identifier]
        name, accepted = QInputDialog.getText(self, 'Rename preset', 'Name:', text=data['name'])
        if accepted and name.strip():
            set_preset(self.graph, kind, identifier, name.strip(), data['style'])
            self.refresh()

    def delete_preset(self):
        identifier = self.preset.currentData()
        if identifier is not None:
            remove_preset(self.graph, self.kind.currentText(), identifier)
            self.refresh()
