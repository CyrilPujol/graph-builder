"""Render public ExtensionMenu declarations with the editor's standard controls."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QMenu, QSlider, QToolButton

from graph_builder_core.extensions import public_graph
from graph_builder_core.ui.widgets import StepControl, menu_button, style_staged_button


def build_extension_menu(window, menu, toolbar):
    """Build one menu without extension code knowing about Qt or window state."""
    by_action = {id(definition): action for definition, action in window.extension_actions}
    for item in menu.items:
        if item.kind == 'button':
            action = by_action[id(item.action)]
            toolbar.addAction(action)
            if item.action.selections > 1:
                style_staged_button(toolbar.widgetForAction(action))
        elif item.kind == 'separator':
            toolbar.addSeparator()
        elif item.kind == 'text':
            label = QLabel(toolbar)
            label.setText(item.label)
            toolbar.addWidget(label)
            if item.other is not None:
                window.extension_texts.append((label, item.other))
        elif item.kind == 'step':
            toolbar.addWidget(QLabel(f'  {item.label}:', toolbar))
            decrease = by_action[id(item.action)]
            increase = by_action[id(item.other)]
            control = StepControl(decrease, increase, toolbar)
            toolbar.addWidget(control)
            window.extension_steps.append((control, decrease, increase))
            window.extension_search_controls.extend(((menu.name, decrease.text(), control.decrease, decrease),
                                                     (menu.name, increase.text(), control.increase, increase)))
        elif item.kind == 'choice':
            toolbar.addWidget(QLabel(f'  {item.label}:', toolbar))
            control = QComboBox(toolbar)
            control.addItems([str(option) for option in item.options])
            control.setCurrentIndex(item.options.index(menu.value(item.key)))
            control.currentIndexChanged.connect(
                lambda index, menu=menu, item=item: menu.state.__setitem__(item.key, item.options[index]))
            toolbar.addWidget(control)
            window.extension_search_controls.append((menu.name, item.label, control, None))
        elif item.kind == 'input':
            toolbar.addWidget(QLabel(f'  {item.label}:', toolbar))
            control = QLineEdit(menu.value(item.key), toolbar)
            control.setPlaceholderText(item.other)
            control.setFixedWidth(100)
            control.textChanged.connect(
                lambda value, menu=menu, key=item.key: menu.state.__setitem__(key, value))
            toolbar.addWidget(control)
            window.extension_search_controls.append((menu.name, item.label, control, None))
        elif item.kind == 'toggle':
            control = QToolButton(toolbar)
            control.setText(item.label)
            control.setCheckable(True)
            control.setChecked(menu.value(item.key))
            control.toggled.connect(
                lambda checked, menu=menu, key=item.key: menu.state.__setitem__(key, checked))
            if item.action is not None:
                control.toggled.connect(lambda checked, action=item.action: window.run_extension(action))
            if item.when is not None:
                if not hasattr(window, 'extension_toggles'):
                    window.extension_toggles = []
                window.extension_toggles.append((control, menu, item))
            toolbar.addWidget(control)
            window.extension_search_controls.append((menu.name, item.label, control, None))
        elif item.kind == 'slider':
            toolbar.addWidget(QLabel(f'  {item.label}:', toolbar))
            control = QSlider(Qt.Horizontal, toolbar)
            control.setRange(item.minimum, item.maximum)
            control.setValue(menu.value(item.key))
            control.setFixedWidth(105)
            value = QLabel(str(menu.value(item.key)), toolbar)
            value.setMinimumWidth(22)
            control.valueChanged.connect(
                lambda number, menu=menu, key=item.key, value=value:
                (menu.state.__setitem__(key, number), value.setText(str(number))))
            toolbar.addWidget(control)
            toolbar.addWidget(value)
            window.extension_search_controls.append((menu.name, item.label, control, None))
        elif item.kind == 'submenu':
            drop_down = QMenu(toolbar)
            for definition in item.options:
                action = by_action[id(definition)]
                drop_down.addAction(action)
                window.addAction(action)
            control = menu_button(item.label, drop_down, toolbar)
            control.setCheckable(True)
            staged_labels = [action.display_name(window.context()) + ' ✓'
                             for action in item.options if action.selections > 1]
            if staged_labels:
                style_staged_button(control, staged_labels, dropdown=True)
            control.clicked.connect(lambda checked=False: (
                window.run_extension(window._staged_extension)
                if window._staged_extension is not None else None))
            if not hasattr(window, 'extension_submenus'):
                window.extension_submenus = []
            window.extension_submenus.append((control, item))
            toolbar.addWidget(control)
            window.extension_search_controls.append((menu.name, item.label, control, None))
            window.extension_search_controls.extend(
                (menu.name, definition.display_name(window.context()), control,
                 by_action[id(definition)]) for definition in item.options)
        else:
            raise ValueError(f'Unknown extension control {item.kind!r}')


def refresh_extension_controls(window):
    for control, menu, item in getattr(window, 'extension_toggles', ()):
        checked = bool(item.when(public_graph(window.graph)))
        menu.state[item.key] = checked
        previous = control.blockSignals(True)
        control.setChecked(checked)
        control.blockSignals(previous)
    for control, item in getattr(window, 'extension_submenus', ()):
        active = next((action for action in item.options
                       if action is window._staged_extension), None)
        control.setChecked(active is not None)
        control.setText(active.display_name(window.context()) + ' ✓' if active else item.label)
        control.setPopupMode(QToolButton.DelayedPopup if active else QToolButton.InstantPopup)
    for label, callback in getattr(window, 'extension_texts', ()):
        label.setText(str(callback(public_graph(window.graph))))
    for control, decrease, increase in getattr(window, 'extension_steps', ()):
        control.set_limits(decrease.isEnabled(), increase.isEnabled())
