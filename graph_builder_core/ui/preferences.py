"""Per-user editor preferences, independent of graph documents."""
from __future__ import annotations

import re
import sys

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QKeySequenceEdit, QStyleFactory, QWidget,
)


def settings():
    return QSettings('Cyril Pujol', 'Graph Builder')


def shortcut_text(sequence):
    return sequence.toString(QKeySequence.PortableText)


class _ConflictShortcutDelegate(QStyledItemDelegate):
    """Keep a conflicted shortcut red even when its row is selected."""

    def paint(self, painter, option, index):
        if index.data(Qt.UserRole + 1) and option.state & QStyle.State_Selected:
            option = QStyleOptionViewItem(option)
            color = index.data(Qt.ForegroundRole)
            if isinstance(color, QBrush):
                option.palette.setColor(QPalette.HighlightedText, color.color())
        super().paint(painter, option, index)


class PreferencesDialog(QDialog):
    """Searchable shortcut list and a small appearance preference."""

    def __init__(self, shortcuts, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Preferences')
        self.resize(570, 520)
        self.shortcuts = shortcuts
        self.values = {key: tuple(shortcut_text(s) for s in action.shortcuts())
                       for key, (_, action) in shortcuts.items()}
        self.defaults = {key: tuple(shortcut_text(s) for s in defaults)
                         for key, (defaults, _) in shortcuts.items()}
        self._edit_order = []
        self._conflict_warning = None
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(('System', 'Light', 'Dark'))
        saved_theme = str(settings().value('appearance/theme', 'Light'))
        self.theme.setCurrentText(saved_theme if saved_theme in ('System', 'Light', 'Dark') else 'Light')
        form.addRow('Theme', self.theme)
        outer.addLayout(form)
        outer.addWidget(QLabel('Keyboard shortcuts'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search actions…')
        outer.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(('Action', 'Shortcut'))
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 340)
        self.tree.setItemDelegateForColumn(1, _ConflictShortcutDelegate(self.tree))
        outer.addWidget(self.tree, 1)
        self.editor = QKeySequenceEdit()
        self.editor.setMaximumSequenceLength(1)
        self.editor.setEnabled(False)
        # QKeySequenceEdit delegates clicks and keyboard focus to its line edit.
        self._shortcut_focus_widgets = (self.editor, *self.editor.findChildren(QLineEdit))
        for widget in self._shortcut_focus_widgets:
            widget.installEventFilter(self)
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel('Selected action'))
        edit_row.addWidget(self.editor, 1)
        self.clear_button = QPushButton('Clear')
        self.reset_button = QPushButton('Reset')
        self.clear_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        edit_row.addWidget(self.clear_button)
        edit_row.addWidget(self.reset_button)
        outer.addLayout(edit_row)
        self.note = QLabel('Tab and Enter keep their navigation roles.')
        self.note.setWordWrap(True)
        outer.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.reset_all = QPushButton('Reset all shortcuts')
        buttons.addButton(self.reset_all, QDialogButtonBox.ResetRole)
        outer.addWidget(buttons)
        self.items = {}
        self._build_tree()
        self._refresh_conflicts()
        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.editor.keySequenceChanged.connect(self._edited)
        self.clear_button.clicked.connect(lambda: self._set_selected(()))
        self.reset_button.clicked.connect(lambda: self._set_selected(self.defaults[self._selected_key()]))
        self.reset_all.clicked.connect(self._reset_all)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _build_tree(self):
        groups = {}
        for key, (_, action) in self.shortcuts.items():
            group = key.split('/', 1)[0]
            root = groups.get(group)
            if root is None:
                root = QTreeWidgetItem(self.tree, [group, ''])
                root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
                groups[group] = root
            item = QTreeWidgetItem(root, [action.text().replace('&', ''), ', '.join(self.values[key])])
            item.setData(0, Qt.UserRole, key)
            self.items[key] = item
        self.tree.expandAll()

    def _filter(self, query):
        query = query.casefold().strip()
        for key, item in self.items.items():
            item.setHidden(bool(query and query not in item.text(0).casefold()
                                and query not in key.casefold()))
        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            root.setHidden(all(root.child(i).isHidden() for i in range(root.childCount())))

    def _selected_key(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _selection_changed(self):
        key = self._selected_key()
        self.editor.blockSignals(True)
        self.editor.setKeySequence(QKeySequence(self.values[key][0]) if key and self.values[key] else QKeySequence())
        self.editor.blockSignals(False)
        self.editor.setEnabled(bool(key))
        self.clear_button.setEnabled(bool(key))
        self.reset_button.setEnabled(bool(key))

    def _set_selected(self, value):
        key = self._selected_key()
        if key:
            self.values[key] = tuple(value)
            self.items[key].setText(1, ', '.join(value))
            if key in self._edit_order:
                self._edit_order.remove(key)
            self._edit_order.append(key)
            self._refresh_conflicts()
            self._selection_changed()

    def _edited(self, sequence):
        key = self._selected_key()
        if not key:
            return
        value = shortcut_text(sequence)
        if not value:
            self._set_selected(())
            return
        if sequence in (QKeySequence(Qt.Key_Tab), QKeySequence(Qt.SHIFT | Qt.Key_Tab),
                        QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            self.note.setText('Tab and Enter are reserved for navigation and staged actions.')
            self._selection_changed()
            return
        self._set_selected((value,))

    def _conflicts(self):
        users = {}
        for key, assigned in self.values.items():
            for sequence in assigned:
                if sequence:
                    users.setdefault(sequence, []).append(key)
        return {sequence: keys for sequence, keys in users.items() if len(keys) > 1}

    def _refresh_conflicts(self):
        conflicts = self._conflicts()
        marked = {key for keys in conflicts.values() for key in keys}
        red = QColor('#ff7373' if QApplication.palette().color(QPalette.Window).lightness() < 128
                     else '#b12424')
        for key, item in self.items.items():
            item.setForeground(1, QBrush(red) if key in marked else QBrush())
            item.setData(1, Qt.UserRole + 1, key in marked)
        if conflicts:
            names = ', '.join(conflicts)
            self.note.setText(f'Conflicting shortcuts: {names}. Fix them before saving, or let Graph Builder resolve them.')
            self.note.setStyleSheet(f'color: {red.name()};')
        else:
            self.note.setText('Tab and Enter keep their navigation roles.')
            self.note.setStyleSheet('')

    def _resolve_conflicts(self):
        # A newly assigned shortcut takes precedence over an older assignment.
        priority = list(reversed(self._edit_order)) + [key for key in self.values if key not in self._edit_order]
        used = set()
        for key in priority:
            retained = tuple(sequence for sequence in self.values[key] if sequence not in used)
            self.values[key] = retained
            used.update(retained)
            self.items[key].setText(1, ', '.join(retained))
        self._refresh_conflicts()

    def accept(self):
        if not self._conflicts():
            super().accept()
            return
        if self._conflict_warning is not None:
            self._conflict_warning.raise_()
            return
        warning = QMessageBox(self)
        warning.setIcon(QMessageBox.Warning)
        warning.setWindowTitle('Shortcut conflicts')
        warning.setText('Some shortcuts are assigned to more than one action.')
        warning.setInformativeText('Keep editing, or resolve the conflicts automatically and save?')
        warning.addButton('Keep editing', QMessageBox.RejectRole)
        resolve = warning.addButton('Resolve and save', QMessageBox.AcceptRole)
        self._conflict_warning = warning

        def finished(_):
            self._conflict_warning = None
            if warning.clickedButton() is resolve:
                self._resolve_conflicts()
                QDialog.accept(self)
            warning.deleteLater()

        warning.finished.connect(finished)
        warning.open()

    def eventFilter(self, watched, event):
        if watched in self._shortcut_focus_widgets:
            if event.type() == QEvent.FocusIn:
                self.editor.setStyleSheet('QKeySequenceEdit { border: 2px solid #15857f; '
                                          'background: #d4e7e8; border-radius: 4px; padding: 3px; } '
                                          'QKeySequenceEdit QLineEdit { background: #d4e7e8; '
                                          'color: #111111; }')
            elif event.type() == QEvent.FocusOut:
                self.editor.setStyleSheet('')
        return super().eventFilter(watched, event)

    def _reset_all(self):
        self.values = dict(self.defaults)
        self._edit_order.clear()
        for key, item in self.items.items():
            item.setText(1, ', '.join(self.values[key]))
        self._refresh_conflicts()
        self._selection_changed()
_DARK_COLORS = {
    '#111111': '#edf0f2', '#222222': '#e0e5e8', '#303943': '#d1d9dd',
    '#353b41': '#cbd2d7', '#555c63': '#b8c0c6', '#777d84': '#929ba3',
    '#8a8f96': '#89949c', '#ffffff': '#20252a', '#fcfcfd': '#1c2126',
    '#f5f6f7': '#2b3137', '#f1f2f3': '#30363c', '#f0f1f2': '#30363c',
    '#e6e7e9': '#353c43', '#e4e6e9': '#394148', '#d7dce0': '#46515a',
    '#d0d4d9': '#59636b', '#c4c9ce': '#64717a', '#b8bec4': '#68737b',
    '#9ba2a9': '#829098', '#d4e7e8': '#285b60', '#96b9bc': '#3d777d',
    '#e6ecee': '#35494e',
    '#edf6f4': '#294449', '#dcefeb': '#32565b', '#fff1d8': '#57442c',
    '#f7faf9': '#27343a', '#172b36': '#edf0f2', '#33434d': '#d5dfe2',
    '#687982': '#a8b5ba', '#536670': '#b4c0c5', '#dbe8e5': '#49595b',
}
_DARK_COLORS['rgba(255, 255, 255, 235)'] = 'rgba(37, 43, 48, 235)'
_COLOR_PATTERN = re.compile('|'.join(re.escape(k) for k in sorted(_DARK_COLORS, key=len, reverse=True)), re.I)


class ThemeManager(QObject):
    """Theme existing controls and controls created by later dialogs."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.original_palette = QPalette(app.palette())
        self.mode = 'System'
        self._applying = False
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not self._applying and event.type() in (QEvent.Show, QEvent.StyleChange):
            if hasattr(watched, 'styleSheet'):
                self._style_widget(watched)
        return False

    def _style_widget(self, widget):
        # Native macOS controls can ignore an explicit Light palette. Keep the
        # main window native, but paint each in-app dialog consistently rather
        # than mixing two control styles inside the same form.
        owner = widget if isinstance(widget, QWidget) else None
        while owner is not None and not isinstance(owner, QDialog):
            owner = owner.parentWidget()
        if (sys.platform == 'darwin' and isinstance(owner, QDialog)
                and not isinstance(owner, QFileDialog)):
            use_fusion = self.mode == 'Light'
            was_fusion = widget.property('_gb_light_dialog_control') is True
            if use_fusion != was_fusion:
                self._applying = True
                try:
                    widget.setStyle(QStyleFactory.create('Fusion') if use_fusion else None)
                    widget.setProperty('_gb_light_dialog_control', use_fusion)
                finally:
                    self._applying = False
                if widget is owner and widget.property('_gb_compact_theme_dialog'):
                    QTimer.singleShot(0, lambda dialog=widget: dialog.adjustSize()
                                      if dialog.isVisible() else None)
        current = widget.styleSheet()
        stored = widget.property('_gb_original_stylesheet')
        transformed = widget.property('_gb_transformed_stylesheet')
        if current != transformed and current != stored:
            stored = current
            widget.setProperty('_gb_original_stylesheet', stored)
        if stored is None:
            return
        desired = _COLOR_PATTERN.sub(lambda match: _DARK_COLORS[match.group().lower()], stored) if self.is_dark else stored
        if desired != current:
            self._applying = True
            try:
                widget.setStyleSheet(desired)
                widget.setProperty('_gb_transformed_stylesheet', desired)
            finally:
                self._applying = False

    @property
    def is_dark(self):
        return self.mode == 'Dark' or (self.mode == 'System' and
                                       self.original_palette.color(QPalette.Window).lightness() < 128)

    def apply(self, mode):
        self.mode = mode
        palette = QPalette(self.original_palette)
        if self.is_dark:
            colors = {
                QPalette.Window: '#252b30', QPalette.WindowText: '#edf0f2',
                QPalette.Base: '#20252a', QPalette.AlternateBase: '#2b3137',
                QPalette.Text: '#edf0f2', QPalette.Button: '#353c43',
                QPalette.ButtonText: '#edf0f2', QPalette.ToolTipBase: '#353c43',
                QPalette.ToolTipText: '#edf0f2', QPalette.Highlight: '#357f82',
                QPalette.HighlightedText: '#ffffff',
            }
            for role, value in colors.items():
                palette.setColor(role, QColor(value))
        elif mode == 'Light':
            colors = {
                QPalette.Window: '#f5f6f7', QPalette.WindowText: '#111111',
                QPalette.Base: '#ffffff', QPalette.AlternateBase: '#f1f2f3',
                QPalette.Text: '#111111', QPalette.Button: '#f5f6f7',
                QPalette.ButtonText: '#111111', QPalette.ToolTipBase: '#ffffff',
                QPalette.ToolTipText: '#111111', QPalette.Highlight: '#d4e7e8',
                QPalette.HighlightedText: '#111111', QPalette.Mid: '#d4d9dd',
                QPalette.Dark: '#bbc3c9',
            }
            for role, value in colors.items():
                palette.setColor(role, QColor(value))
        palette.setColor(QPalette.PlaceholderText, QColor('#929ba3' if self.is_dark else '#777d84'))
        self.app.setPalette(palette)
        for window in self.app.topLevelWidgets():
            self._style_widget(window)
            for widget in window.findChildren(QObject):
                if hasattr(widget, 'styleSheet'):
                    self._style_widget(widget)


def theme_manager(app):
    manager = getattr(app, '_graph_builder_theme_manager', None)
    if manager is None:
        manager = ThemeManager(app)
        app._graph_builder_theme_manager = manager
        manager.apply(str(settings().value('appearance/theme', 'Light')))
    return manager
