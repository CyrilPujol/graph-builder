"""Search the editor's visible controls without changing the graph."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QVBoxLayout, QWidget


@dataclass(frozen=True)
class SearchableControl:
    menu: str
    name: str
    widget: QWidget
    shortcut: str = ''


class ActionSearchDialog(QDialog):
    """A small action finder. Activating a result locates, but never runs, it."""

    chosen = Signal(int)

    def __init__(self, controls: list[SearchableControl], parent=None):
        super().__init__(parent)
        self.controls = controls
        self.setWindowTitle('Find a control')
        self.resize(410, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Find a button or control'))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('Search actions…')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.results = QListWidget(self)
        layout.addWidget(self.results, 1)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._choose_current)
        self.results.itemActivated.connect(self._choose_item)
        self._filter('')
        self.search.setFocus()

    def _filter(self, query):
        words = query.casefold().split()
        self.results.clear()
        for index, control in enumerate(self.controls):
            searchable = f'{control.menu} {control.name} {control.shortcut}'.casefold()
            if all(word in searchable for word in words):
                label = f'{control.menu}  ›  {control.name}'
                if control.shortcut:
                    label += f'    ({control.shortcut})'
                self.results.addItem(label)
                self.results.item(self.results.count() - 1).setData(Qt.UserRole, index)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _choose_current(self):
        self._choose_item(self.results.currentItem())

    def _choose_item(self, item):
        if item is None:
            return
        self.chosen.emit(item.data(Qt.UserRole))
        self.accept()
