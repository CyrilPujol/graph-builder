"""Compact Qt editors for inherited graph appearance."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt, QSignalBlocker, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPalette
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from graph_builder_core.model.regions import set_region_properties
from graph_builder_core.model.styles import (
    FIELDS, contrast_text_color, effective_style, has_custom_look, reset_palette_style,
    set_palette_style,
)
from graph_builder_core.ui.items import draw_vertex_body, edge_arrow_path, edge_pen


SPECS = {
    'vertex': {
        'fill': ('Fill', 'color'), 'outline': ('Outline', 'color'),
        'shape': ('Shape', ('circle', 'square', 'diamond', 'triangle', 'none')),
        'size': ('Diameter', (4, 200, 1)),
        'outline_width': ('Outline width', (0, 20, .5)),
        'text': ('Text color', 'color'),
        'tikz_options': ('Extra TikZ node options', 'text'),
    },
    'edge': {
        'stroke': ('Stroke', 'color'), 'width': ('Width', (.5, 20, .5)),
        'pattern': ('Pattern', ('solid', 'dash', 'dot', 'dashdot')),
        'opacity': ('Opacity', (0, 1, .05)),
        'label_t': ('Label position', (0, 1, .05)),
        'label_offset': ('Label offset', (-100, 100, 1)),
        'arrow_shape': ('Arrowhead', ('triangle', 'stealth', 'latex', 'open')),
        'arrow_length': ('Arrowhead length', (3, 40, 1)),
        'arrow_width': ('Arrowhead width', (3, 40, 1)),
        'tikz_options': ('Extra TikZ draw options', 'text'),
    },
}


class RegionPropertiesDialog(QDialog):
    """Small editor for a region's label and independent appearance."""

    preview_changed = Signal()

    def __init__(self, region, graph, parent=None):
        super().__init__(parent)
        self.setProperty('_gb_compact_theme_dialog', True)
        self._source_graph = graph
        self._region_id = region['id']
        self.setWindowTitle('Region properties')
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        fields = QFormLayout()
        fields.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label_edit = QLineEdit(str(region.get('label', '')))
        fields.addRow('Label', self.label_edit)
        self.mode = QComboBox()
        self.mode.addItem('Convex hull', 'hull')
        self.mode.addItem('Manual boundary', 'manual')
        self.mode.setCurrentIndex(1 if region['mode'] == 'path' else 0)
        fields.addRow('Boundary', self.mode)
        self.mode_note = QLabel()
        self.mode_note.setWordWrap(True)
        fields.addRow('', self.mode_note)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()
        padding = QDoubleSpinBox()
        padding.setRange(-200, 200)
        padding.setSingleStep(2)
        padding.setValue(float(region.get('margin', 0)))
        padding.setToolTip('Positive padding expands the region, negative padding moves it inward. Applied after curves.')
        fields.addRow('Padding', padding)
        padding.valueChanged.connect(self.preview_changed)
        self.controls = {}
        self.controls['padding'] = padding
        style = region['style']
        for field, title in (('fill', 'Fill'), ('outline', 'Outline')):
            control = QLineEdit(str(style[field]))
            row = QHBoxLayout()
            row.addWidget(control)
            choose = QPushButton('…')
            choose.setFixedWidth(30)
            choose.clicked.connect(lambda _, box=control: self._choose_color(box))
            row.addWidget(choose)
            none = QPushButton('None')
            none.clicked.connect(lambda _, box=control: box.setText('none'))
            row.addWidget(none)
            fields.addRow(title, row)
            self.controls[field] = control
            control.textChanged.connect(self.preview_changed)
        width = QDoubleSpinBox()
        width.setRange(0, 20)
        width.setSingleStep(.5)
        width.setValue(float(style['width']))
        fields.addRow('Outline width', width)
        width.valueChanged.connect(self.preview_changed)
        self.controls['width'] = width
        opacity = QDoubleSpinBox()
        opacity.setRange(0, 1)
        opacity.setSingleStep(.05)
        opacity.setDecimals(2)
        opacity.setValue(float(style['opacity']))
        fields.addRow('Opacity', opacity)
        opacity.valueChanged.connect(self.preview_changed)
        self.controls['opacity'] = opacity
        extra = QLineEdit(str(style.get('tikz_options', '')))
        extra.setToolTip('Additional TikZ fill options. The canvas is an approximation.')
        fields.addRow('Extra TikZ options', extra)
        extra.textChanged.connect(self.preview_changed)
        self.controls['tikz_options'] = extra
        self.label_edit.textChanged.connect(self.preview_changed)
        layout.addLayout(fields)
        note = QLabel('The canvas approximates the TikZ look. Extra options may only appear in export and may fail to compile.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_color(self, box):
        color = QColorDialog.getColor(QColor(box.text()), self)
        if color.isValid():
            box.setText(color.name())

    def _mode_changed(self):
        if self.mode.currentData() == 'hull':
            self.mode_note.setText('The boundary is the convex hull of its vertices and follows them when they move.')
        else:
            self.mode_note.setText('The boundary follows its vertex order or linked edges and can be reshaped with curve points.')
        self.preview_changed.emit()

    def values(self):
        return {'label': self.label_edit.text(),
                'mode': self.mode.currentData(),
                'margin': self.controls['padding'].value(),
                'style': {'fill': self.controls['fill'].text().strip(),
                          'outline': self.controls['outline'].text().strip(),
                          'width': self.controls['width'].value(),
                          'opacity': self.controls['opacity'].value(),
                          'tikz_options': self.controls['tikz_options'].text()}}

    def _accept(self):
        for field in ('fill', 'outline'):
            value = self.controls[field].text().strip()
            if value != 'none' and not QColor(value).isValid():
                QMessageBox.warning(self, 'Invalid color',
                                    f'{field.title()} must be a color or none.')
                return
        try:
            set_region_properties(deepcopy(self._source_graph), self._region_id,
                                  self.values())
        except ValueError as error:
            QMessageBox.warning(self, 'Invalid region boundary', str(error))
            return
        self.accept()


class PropertiesDialog(QDialog):
    advanced_open = False
    preview_changed = Signal()

    def __init__(self, graph, kind, attributes, *, bulk=False, style_only=False,
                 parent=None):
        super().__init__(parent)
        self.setProperty('_gb_compact_theme_dialog', True)
        self.source_graph, self.graph, self.kind = graph, deepcopy(graph), kind
        self.attributes = list(attributes)
        self.bulk, self.style_only = bulk, style_only
        self.type_delta = 0
        self.look_mode = None
        self.custom_look_notice = None
        self._look_touched = False
        self._edited_fields = set()
        self.shared_style_update = None
        self._applying_to_type = False
        self.setWindowTitle(f'{"Vertex" if kind == "vertex" else "Edge"} properties')
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        self.label_edit = None
        if not bulk and not style_only:
            label_row = QHBoxLayout()
            label_row.addWidget(QLabel('Label'))
            self.label_edit = QLineEdit(str(self.attributes[0].get('label', '')))
            self.label_edit.setToolTip('TikZ exports use LaTeX labels. Write $x_1$ for a subscript or \\# for a literal #.')
            label_row.addWidget(self.label_edit)
            layout.addLayout(label_row)
        if not style_only:
            type_row = QHBoxLayout()
            type_row.addWidget(QLabel('Style'))
            self.type_label = QLabel()
            type_row.addWidget(self.type_label, 1)
            step = QWidget()
            step.setObjectName('type_step')
            step.setFixedSize(62, 31)
            step.setStyleSheet('QWidget#type_step { border: 1px solid #d0d4d9; border-radius: 5px; } '
                               'QToolButton { color: #111111; background: #f5f6f7; '
                               'border: none; font-size: 17px; } '
                               'QToolButton:disabled { color: #777d84; background: #f1f2f3; }')
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
            if any(has_custom_look(item) for item in self.attributes):
                object_name = 'vertices' if kind == 'vertex' else 'edges'
                if bulk:
                    message = (f'Some selected {object_name} have custom looks. '
                               'A style change may not affect their whole appearance.')
                else:
                    object_name = 'vertex' if kind == 'vertex' else 'edge'
                    message = (f'This {object_name} has a custom look. '
                               'A style change may not affect its whole appearance.')
                self.custom_look_notice = QLabel(message)
                self.custom_look_notice.setWordWrap(True)
                layout.addWidget(self.custom_look_notice)
        toggle = QPushButton('Style ▾', self)
        self.advanced_toggle = toggle
        toggle.setCheckable(True)
        toggle.setStyleSheet('''
            QPushButton { color: #111111; background: #f5f6f7;
                          border: 1px solid #d0d4d9; border-radius: 4px;
                          padding: 4px 9px; }
            QPushButton:hover:enabled { background: #e6ecee; }
            QPushButton:checked { color: #111111; background: #d4e7e8;
                                  border-color: #96b9bc; }
        ''')
        toggle.setChecked(style_only or PropertiesDialog.advanced_open)
        layout.addWidget(toggle, 0, Qt.AlignLeft)
        toggle.setVisible(not style_only)
        advanced_widget = QWidget(self)
        advanced_widget.setObjectName('style_advanced_panel')
        advanced_layout = QVBoxLayout(advanced_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        if not style_only:
            self.look_mode = QComboBox()
            if bulk:
                self.look_mode.addItem('Keep existing looks', 'keep')
            self.look_mode.addItem(self._inherit_text(), 'inherit')
            self.look_mode.addItem('Custom look', 'custom')
            if not bulk:
                first = self.attributes[0]
                mode = ('custom' if first.get('style_overrides') or first.get('style_preset')
                        else 'inherit')
                self.look_mode.setCurrentIndex(self.look_mode.findData(mode))
            advanced_layout.addWidget(self.look_mode)
            self.apply_type_button = QPushButton('Apply look to basic style')
            self.apply_type_button.clicked.connect(self.apply_look_to_type)
            advanced_layout.addWidget(self.apply_type_button, 0, Qt.AlignLeft)
        self.controls = {}
        if self.label_edit is not None:
            self.label_edit.textChanged.connect(self.preview_changed)
        fields = QFormLayout()
        fields.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for field in FIELDS[kind]:
            if field.startswith('arrow_') and graph.graph.get('graph_type') == 'graph':
                continue
            title, spec = SPECS[kind][field]
            row = QHBoxLayout()
            style = effective_style(graph, kind, self.attributes[0])
            current = self._display_value(field, style)
            if spec == 'color':
                value = QLineEdit(str(current))
                value.setPlaceholderText('Hex color' + (', none' if field in ('fill', 'outline') else
                                                        ', auto' if field == 'text' else ''))
                choose = QPushButton('…')
                choose.setFixedWidth(30)
                choose.clicked.connect(lambda _, box=value: self._choose_color(box))
                row.addWidget(value)
                row.addWidget(choose)
                if field in ('fill', 'outline', 'text'):
                    special = QPushButton('Auto' if field == 'text' else 'None')
                    special.clicked.connect(lambda _, box=value, choice='auto' if field == 'text' else 'none': box.setText(choice))
                    row.addWidget(special)
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
            else:
                value = QComboBox()
                for choice in spec:
                    value.addItem(str(choice).replace('_', ' ').title(), choice)
                value.setCurrentIndex(max(0, value.findData(current)))
                row.addWidget(value)
            self.controls[field] = value
            fields.addRow(title, row)
        advanced_layout.addLayout(fields)
        toggle.toggled.connect(self._toggle_advanced)
        self.advanced_widget = advanced_widget
        layout.addWidget(advanced_widget)
        advanced_widget.setVisible(style_only or PropertiesDialog.advanced_open)
        note = QLabel('Canvas rendering is approximate. Extra TikZ options are exported verbatim and may fail to compile.')
        note.setWordWrap(True)
        advanced_layout.addWidget(note)
        if self.look_mode is not None:
            self.look_mode.currentIndexChanged.connect(self._look_mode_changed)
            self._sync_look()
        self._initial_control_values = self._control_values()
        for field, widget in self.controls.items():
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda _, name=field: self._field_changed(name))
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(lambda _, name=field: self._field_changed(name))
            else:
                widget.currentIndexChanged.connect(lambda _, name=field: self._field_changed(name))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_advanced(self, open_advanced):
        self.advanced_widget.setVisible(open_advanced)
        PropertiesDialog.advanced_open = open_advanced
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    @staticmethod
    def _display_value(field, style):
        # Older files may still use hollow_* shapes. Present them using the
        # equivalent ordinary shape and transparent fill controls.
        if field == 'shape' and str(style['shape']).startswith('hollow_'):
            return style['shape'][7:]
        if field == 'fill' and str(style['shape']).startswith('hollow_'):
            return 'none'
        return style[field]

    def _inherit_text(self):
        indices = {int(item.get('style', 0)) for item in self.attributes}
        if len(indices) == 1:
            return f'Inherit from style {(next(iter(indices)) + self.type_delta) % self._type_count()}'
        return 'Inherit from each style'

    def _type_count(self):
        return max(1, int(self.graph.graph.get(
            'num_vertex_styles' if self.kind == 'vertex' else 'num_edge_styles', 1)))

    def type_values(self):
        return [(int(item.get('style', 0)) + self.type_delta) % self._type_count()
                for item in self.attributes]

    def _update_type_label(self):
        values = set(self.type_values())
        self.type_label.setText(str(next(iter(values))) if len(values) == 1 else 'Mixed')
        if self.look_mode is not None:
            index = self.look_mode.findData('inherit')
            self.look_mode.setItemText(index, self._inherit_text())

    def change_type(self, delta):
        self._clear_pending_type_style()
        self.type_delta += delta
        self._update_type_label()
        self._refresh_readonly_controls()
        self.preview_changed.emit()

    def _sync_look(self):
        mode = self.look_mode.currentData()
        if self.custom_look_notice is not None:
            self.custom_look_notice.setVisible(mode != 'inherit')
        if mode != 'inherit' and not self._applying_to_type:
            self._clear_pending_type_style()
        self.apply_type_button.setEnabled(mode == 'custom' and len(set(self.type_values())) == 1)
        self._refresh_readonly_controls()

    def _look_mode_changed(self):
        self._edited_fields.clear()
        self._sync_look()
        self._initial_control_values = self._control_values()
        self._mark_look_touched()

    def _field_changed(self, field):
        self._edited_fields.add(field)
        if self.look_mode is not None and self.look_mode.currentData() != 'custom':
            with QSignalBlocker(self.look_mode):
                self.look_mode.setCurrentIndex(self.look_mode.findData('custom'))
            self._sync_look()
        self._mark_look_touched()

    def _mark_look_touched(self, *_):
        self._look_touched = True
        self.preview_changed.emit()

    def _refresh_readonly_controls(self):
        if self.look_mode is None or self.look_mode.currentData() != 'inherit':
            return
        attributes = deepcopy(self.attributes[0])
        attributes['style'] = self.type_values()[0]
        attributes.pop('style_overrides', None)
        attributes.pop('style_preset', None)
        style = effective_style(self.graph, self.kind, attributes)
        for field, widget in self.controls.items():
            blocker = QSignalBlocker(widget)
            value = self._display_value(field, style)
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            else:
                widget.setText(str(value))
            del blocker
        self._initial_control_values = self._control_values()

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
        if mode == 'inherit':
            return {field: None for field in FIELDS[self.kind]}
        if self.bulk:
            values = self._control_values()
            return {field: values[field] for field in self._edited_fields
                    if values[field] != self._initial_control_values[field]}
        return self._control_values()

    def clear_preset(self):
        if self.look_mode is None or not self._look_touched or self.look_mode.currentData() == 'keep':
            return False
        if self.bulk and self.look_mode.currentData() == 'custom' and not self.changes():
            return False
        return True

    def _clear_pending_type_style(self):
        if self.shared_style_update is not None:
            self.shared_style_update = None
            self.graph = deepcopy(self.source_graph)

    def apply_look_to_type(self):
        if self.look_mode.currentData() != 'custom' or len(set(self.type_values())) != 1:
            return
        values = self._control_values()
        if not self._valid_colors(values):
            return
        index = self.type_values()[0]
        self.shared_style_update = (index, values)
        set_palette_style(self.graph, self.kind, index, values)
        self._applying_to_type = True
        self.look_mode.setCurrentIndex(self.look_mode.findData('inherit'))
        self._applying_to_type = False
        self._look_touched = True
        self.preview_changed.emit()

    def _control_values(self):
        return {field: (widget.currentData() if isinstance(widget, QComboBox) else
                        widget.value() if isinstance(widget, QDoubleSpinBox) else widget.text().strip())
                for field, widget in self.controls.items()}

    def _accept(self):
        if self.look_mode is not None and self.look_mode.currentData() != 'custom':
            self.accept()
            return
        if self._valid_colors(self.changes()):
            self.accept()

    def _valid_colors(self, changes, *, warn=True):
        for field in ('fill', 'outline', 'text', 'stroke'):
            value = changes.get(field)
            special = (value == 'auto' and field == 'text') or (value == 'none' and field in ('fill', 'outline'))
            if value is not None and not special and not (isinstance(value, str) and
                    len(value) == 7 and value.startswith('#') and QColor(value).isValid()):
                if warn:
                    QMessageBox.warning(self, 'Invalid color', f'{field}: enter a #RRGGBB color or the offered special value.')
                return False
        return True


class BasicStyleSample(QWidget):
    """Render the currently edited style even when no graph object uses it."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setFixedHeight(116)
        self.setAccessibleName('Basic style preview')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Base))
        painter.setPen(QPen(self.palette().color(QPalette.Mid), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)
        graph = self.dialog.preview_graph()
        if graph is None:
            return
        kind = self.dialog._current_kind
        style = effective_style(graph, kind, {'style': self.dialog._current_index})
        center = QPointF(self.width() / 2, self.height() / 2)
        if kind == 'vertex':
            painter.save()
            painter.translate(center)
            painter.scale(min(1, 82 / max(1, float(style['size']))),
                          min(1, 82 / max(1, float(style['size']))))
            fill = draw_vertex_body(painter, style)
            color = style['text']
            if color == 'auto':
                color = (self.palette().color(QPalette.Text).name()
                         if fill == 'none' else contrast_text_color(fill))
            painter.setPen(QColor(color))
            painter.drawText(QRectF(-40, -20, 80, 40), Qt.AlignCenter,
                             str(self.dialog._current_index))
            painter.restore()
        else:
            stroke = style['stroke']
            parent = self.dialog.parent()
            if (getattr(parent, 'theme_dark', False) and self.dialog._current_index == 0
                    and QColor(stroke) == QColor('#000000')):
                style = dict(style, stroke='#ffffff')
            start = QPointF(35, center.y())
            end = QPointF(self.width() - 35, center.y())
            painter.setOpacity(float(style['opacity']))
            painter.setPen(edge_pen(style))
            painter.drawLine(start, end)
            if graph.graph.get('graph_type') != 'graph':
                painter.setPen(QPen(QColor(style['stroke']), 1, Qt.SolidLine,
                                    Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush if style['arrow_shape'] == 'open'
                                 else QColor(style['stroke']))
                painter.drawPath(edge_arrow_path(end, 1, 0, style))


class StylesDialog(QDialog):
    """Browse and edit shared basic styles in a single movable dialog."""
    preview_changed = Signal()
    def __init__(self, graph, parent=None):
        super().__init__(parent)
        self.setProperty('_gb_compact_theme_dialog', True)
        self.graph = deepcopy(graph)
        self.setWindowTitle('Basic styles')
        layout = QVBoxLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(('vertex', 'edge'))
        layout.addWidget(self.kind)
        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel('Style number'))
        self.slot = QSpinBox()
        self.slot.setMinimum(0)
        slot_row.addWidget(self.slot)
        self.reset_button = QPushButton('Reset this style')
        self.reset_button.setToolTip('Restore this built-in style. Individual custom looks stay unchanged.')
        self.reset_button.clicked.connect(self._reset_current_type)
        slot_row.addWidget(self.reset_button)
        layout.addLayout(slot_row)
        self._current_kind = self.kind.currentText()
        self._current_index = 0
        self.refresh()
        self.editor = self._create_editor()
        layout.addWidget(self.editor)
        self.editor.preview_changed.connect(self.preview_changed)
        layout.addWidget(QLabel('Preview'))
        self.style_sample = BasicStyleSample(self)
        layout.addWidget(self.style_sample)
        self.preview_changed.connect(self.style_sample.update)
        self._initial_values = self.editor._control_values()
        self.kind.currentIndexChanged.connect(self._switch_kind)
        self.slot.valueChanged.connect(self._switch_type)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh(self):
        count = self.graph.graph.get(
            'num_vertex_styles' if self.kind.currentText() == 'vertex' else 'num_edge_styles', 1)
        with QSignalBlocker(self.slot):
            self.slot.setMaximum(max(0, int(count) - 1))

    def _create_editor(self):
        editor = PropertiesDialog(self.graph, self._current_kind,
                                  [{'style': self._current_index}], style_only=True, parent=self)
        editor.setWindowFlags(Qt.Widget)
        editor.setMinimumWidth(0)
        editor.layout().setContentsMargins(0, 0, 0, 0)
        editor.findChild(QDialogButtonBox).hide()
        return editor

    def _save_current_type(self):
        values = self.editor._control_values()
        if values == self._initial_values:
            return True
        if not self.editor._valid_colors(values):
            return False
        set_palette_style(self.graph, self._current_kind, self._current_index, values)
        return True

    def _reset_current_type(self):
        # Discard any unfinished edits in this slot, but keep edits to other
        # slots in the dialog. Cancel still discards all of them.
        self._initial_values = self.editor._control_values()
        reset_palette_style(self.graph, self._current_kind, self._current_index)
        self._switch_type(self._current_index)

    def preview_graph(self):
        graph = deepcopy(self.graph)
        values = self.editor._control_values()
        if not self.editor._valid_colors(values, warn=False):
            return None
        set_palette_style(graph, self._current_kind, self._current_index, values)
        return graph

    def _switch_type(self, index):
        if not self._save_current_type():
            with QSignalBlocker(self.slot):
                self.slot.setValue(self._current_index)
            return
        self._current_index = index
        self.editor.graph = self.graph
        self.editor.attributes = [{'style': index}]
        style = effective_style(self.graph, self._current_kind, self.editor.attributes[0])
        for field, widget in self.editor.controls.items():
            with QSignalBlocker(widget):
                value = self.editor._display_value(field, style)
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(max(0, widget.findData(value)))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                else:
                    widget.setText(str(value))
        self._initial_values = self.editor._control_values()
        self.preview_changed.emit()

    def _switch_kind(self):
        if not self._save_current_type():
            with QSignalBlocker(self.kind):
                self.kind.setCurrentText(self._current_kind)
            return
        self._current_kind = self.kind.currentText()
        self.refresh()
        self._current_index = self.slot.value()
        previous = self.editor
        self.editor = self._create_editor()
        self.editor.preview_changed.connect(self.preview_changed)
        self.layout().replaceWidget(previous, self.editor)
        previous.hide()
        previous.deleteLater()
        self._initial_values = self.editor._control_values()
        self.layout().activate()
        self.resize(max(self.width(), self.sizeHint().width()), self.sizeHint().height())
        self.preview_changed.emit()

    def _accept(self):
        if self._save_current_type():
            self.accept()
