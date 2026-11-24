"""Reusable Qt controls."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QToolButton, QWidget


def menu_button(label, menu, parent=None):
    """Compact dropdown shared by core menus and extensions. Inherits the theme."""
    control = QToolButton(parent)
    control.setText(label)
    control.setFixedHeight(30)
    control.setStyleSheet(
        'QToolButton { padding: 3px 22px 3px 9px; } '
        'QToolButton::menu-indicator { subcontrol-origin: padding; '
        'subcontrol-position: right center; right: 7px; }')
    control.setMenu(menu)
    control.setPopupMode(QToolButton.InstantPopup)
    return control


def style_staged_button(control, labels=(), dropdown=False):
    """Highlight captured selections without changing the button's footprint."""
    font = QFont(control.font())
    font.setBold(True)
    metrics = QFontMetrics(font)
    captions = (control.text(), *labels)
    width = max(metrics.horizontalAdvance(text) for text in captions) + (38 if dropdown else 22)
    control.setFixedSize(max(width, control.sizeHint().width()), 30)
    control.setStyleSheet('''
        QToolButton { border: 1px solid #d0d4d9; border-radius: 4px;
                      color: #111111; background: #f5f6f7; padding: 4px 7px; }
        QToolButton:hover:enabled { background: #e6ecee; }
        QToolButton:checked { border: 2px solid #a76a12; font-weight: 700;
                              color: #111111; background: #fff1d8; padding: 3px 6px; }
        QToolButton:disabled { color: #777d84; background: #f1f2f3;
                               border-color: #777d84; }
    ''' + ('''
        QToolButton { padding-right: 22px; }
        QToolButton:checked { padding-right: 21px; }
        QToolButton::menu-indicator { subcontrol-origin: padding;
            subcontrol-position: right center; right: 7px; }
    ''' if dropdown else ''))


class StepControl(QWidget):
    """Stable-width decrement/increment pair with one shared container."""
    def __init__(self, decrease, increase, parent=None, show_disabled_labels=False):
        super().__init__(parent)
        self.show_disabled_labels = show_disabled_labels
        self.decrease = QToolButton(self)
        self.increase = QToolButton(self)
        for button, label, action in ((self.decrease, '-', decrease),
                                      (self.increase, '+', increase)):
            button.setText(label)
            button.setFixedSize(26, 24)
            font = button.font()
            font.setPixelSize(18)
            font.setBold(True)
            button.setFont(font)
            button.setToolTip(action.toolTip())
            button.clicked.connect(action.trigger)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)
        layout.addWidget(self.decrease)
        layout.addWidget(self.increase)
        self.setFixedSize(60, 30)
        self.setStyleSheet('''
            StepControl { border: 1px solid #7f858b; border-radius: 5px; }
            StepControl QToolButton { border: 0; border-radius: 3px; background: #e4e6e9;
                                      color: #111111; padding: 0; margin: 0; }
            StepControl QToolButton:hover:enabled { background: #d7dce0; }
            StepControl QToolButton:disabled { color: #777d84; background: #f0f1f2;
                                               border: 0; }
            StepControl:disabled { border-color: #d7dadd; }
        ''')

    def set_limits(self, can_decrease, can_increase):
        self.decrease.setEnabled(can_decrease)
        self.increase.setEnabled(can_increase)
        self.decrease.setText('-' if can_decrease or self.show_disabled_labels else ' ')
        self.increase.setText('+' if can_increase or self.show_disabled_labels else ' ')


class CollapsibleTabWidget(QTabWidget):
    """A compact tab row whose active tab can be clicked closed."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._open_index = -1
        self._last_open_index = -1
        self._previous_index = None
        self._last_tab_press_at = None
        self.tabBarClicked.connect(self._tab_clicked)

    def open_tab(self, index, *, cycling=False):
        self._open_index = index
        previous = self._last_open_index
        if previous >= 0 and previous != index:
            self._previous_index = previous
        if not cycling:
            self._last_tab_press_at = None
        self._last_open_index = index
        self.tabBar().setProperty('menuOpen', True)
        self.setMaximumHeight(16777215)
        self.setCurrentIndex(index)
        if self.currentWidget() is not None:
            self.currentWidget().show()
        self._refresh_tab_style()

    def close_tab(self):
        self._open_index = -1
        self._last_tab_press_at = None
        self.tabBar().setProperty('menuOpen', False)
        if self.currentWidget() is not None:
            self.currentWidget().hide()
        self.setMaximumHeight(self.tabBar().sizeHint().height() + 2)
        self._refresh_tab_style()

    def _refresh_tab_style(self):
        self.tabBar().style().unpolish(self.tabBar())
        self.tabBar().style().polish(self.tabBar())
        self.tabBar().update()

    def _tab_clicked(self, index):
        close = index == self._open_index
        QTimer.singleShot(0, self.close_tab if close else lambda: self.open_tab(index))

    def cycle_tab(self, direction=1):
        if not self.count():
            return
        now = time.monotonic()
        current = self.currentIndex()
        consecutive = (self._last_tab_press_at is not None
                       and now - self._last_tab_press_at < 0.6) #tab cycling max time
        if not consecutive and self._previous_index is not None:
            target = self._previous_index
        else:
            target = (current + direction) % self.count()
        self._last_tab_press_at = now
        self.open_tab(target, cycling=True)
