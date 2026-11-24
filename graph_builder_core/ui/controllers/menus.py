"""MenusController methods hosted by GraphBuilderQt."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea,
    QSpinBox, QStackedWidget, QTabBar, QTextBrowser, QTextEdit, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from graph_builder_core.algorithms.metrics import BOUND_PROBLEMS, INFO_DEFINITIONS
from graph_builder_core.ui.icons import _gear_icon, _search_icon, _transformation_icon
from graph_builder_core.ui.extension_menus import build_extension_menu
from graph_builder_core.ui.picture_preview import PicturePreview
from graph_builder_core.ui.tutorial import TutorialPanel
from graph_builder_core.ui.widgets import CollapsibleTabWidget, StepControl
from graph_builder_core.version import APP_VERSION


class MenusController:
    def _build_controls(self):
        """A compact menu row with one context-sensitive button row beneath it."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tabs = CollapsibleTabWidget(container)
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(True)
        tabs.setStyleSheet('''
            QTabWidget::pane { background: #f5f6f7; border: 0; }
            QTabBar::tab { color: #111111; background: #e6e7e9; padding: 5px 10px; }
            QTabBar::tab:selected { color: #111111; background: #f5f6f7; }
            QTabBar[menuOpen="false"]::tab:selected { background: #e6e7e9; }
            QTabBar::tab:disabled { color: #8a8f96; }
        ''')
        self.menu_tabs = tabs
        utility_button_style = '''
            QToolButton { color: #111111; background: #e6e7e9;
                          border: 1px solid #c4c9ce; border-radius: 12px;
                          font-weight: bold; }
            QToolButton:hover { background: #d4e7e8; }
        '''
        self.preferences_button = QToolButton(tabs.tabBar())
        self.preferences_button.setIcon(_gear_icon())
        self.preferences_button.setIconSize(QSize(24, 24))
        self.preferences_button.setToolTip('Preferences: keyboard shortcuts and theme')
        self.preferences_button.setAccessibleName('Preferences')
        self.preferences_button.setFixedSize(25, 25)
        self.preferences_button.setStyleSheet(utility_button_style)
        self.preferences_button.clicked.connect(self.open_preferences)
        self.search_button = QToolButton(tabs.tabBar())
        self.search_button.setIcon(_search_icon())
        self.search_button.setIconSize(QSize(20, 20))
        self.search_button.setToolTip('Find a button or control')
        self.search_button.setAccessibleName('Find a control')
        self.search_button.setFixedSize(25, 25)
        self.search_button.setStyleSheet(utility_button_style)
        self.search_button.clicked.connect(self.open_action_search)
        self.help_button = QToolButton(tabs.tabBar())
        self.help_button.setText('?')
        self.help_button.setToolTip('Show the controls guide')
        self.help_button.setAccessibleName('Controls guide')
        self.help_button.setFixedSize(25, 25)
        help_font = self.help_button.font()
        help_font.setPixelSize(14)
        self.help_button.setFont(help_font)
        self.help_button.setStyleSheet(utility_button_style)

        def row(name, actions=()):
            toolbar = QToolBar(name, tabs)
            toolbar.setMovable(False)
            toolbar.setFloatable(False)
            toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
            toolbar.setStyleSheet('''
                QToolBar { border: 0; padding: 2px 2px 2px 8px; background: #f5f6f7; }
                QToolBar QLabel { color: #111111; }
                QToolBar QLabel:disabled { color: #777d84; }
                QToolBar > QToolButton { border: 1px solid #d0d4d9; border-radius: 4px;
                                       color: #111111; background: #f5f6f7;
                                       padding: 4px 7px; margin-right: 3px; }
                QToolBar > QToolButton:hover:enabled { background: #e6ecee; }
                QToolBar > QToolButton:checked { color: #111111; background: #d4e7e8;
                                                 border-color: #96b9bc; }
                QToolBar > QToolButton:disabled { color: #777d84; background: #f1f2f3;
                                                  border-color: #777d84; }
                QToolBar::separator { background: #c4c9ce; width: 1px;
                                      margin: 5px 7px; }
            ''')
            toolbar.addActions(actions)
            tabs.addTab(toolbar, name)
            return toolbar

        file_row = row('File', (self.new_action, self.open_action, self.save_action,
                                self.save_as_action, self.export_action,
                                self.export_picture_action))
        left_utilities = QWidget(tabs.tabBar())
        left_layout = QHBoxLayout(left_utilities)
        left_layout.setContentsMargins(8, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.preferences_button)
        tabs.tabBar().setTabButton(0, QTabBar.LeftSide, left_utilities)

        basic_row = row('Edition', (self.undo_action, self.redo_action,
                                  self.copy_action, self.paste_action,
                                  self.select_all_action, self.select_colors_action,
                                  self.select_neighbours_action,
                                  self.delete_action))
        self.paired_extension_controls = []
        self.transformation_controls = []
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and not definition.pair_id:
                basic_row.addAction(action)
        pairs = {}
        for definition, action in self.extension_actions:
            if definition.group == 'basic' and definition.pair_id:
                pairs.setdefault(definition.pair_id, []).append((definition, action))
        for pair_id, pair in pairs.items():
            if pair_id == 'transformation':
                if len(pair) != 7:
                    raise ValueError('Transformation needs seven actions')
                label_action = basic_row.addWidget(QLabel('  Transformation:', basic_row))
                control = QWidget(basic_row)
                buttons = QHBoxLayout(control)
                buttons.setContentsMargins(0, 0, 0, 0)
                buttons.setSpacing(2)
                for (_, action), kind in zip(pair, ('rotate_left', 'rotate_right',
                                                     'flip_horizontal', 'flip_vertical',
                                                     'half_turn', 'grow', 'shrink')):
                    button = QToolButton(control)
                    button.setToolTip(action.toolTip())
                    button.setEnabled(action.isEnabled())
                    button.clicked.connect(action.trigger)
                    action.changed.connect(lambda button=button, action=action:
                                           button.setEnabled(action.isEnabled()))
                    button.setFixedSize(30, 30)
                    button.setStyleSheet('''
                        QToolButton { border: 1px solid #9ba2a9; border-radius: 4px;
                                      color: #111111; background: #f5f6f7; padding: 0; }
                        QToolButton:hover:enabled { background: #e6ecee; }
                        QToolButton:disabled { color: #777d84; background: #f1f2f3;
                                               border-color: #d0d4d9; }
                    ''')
                    button.setIcon(_transformation_icon(kind))
                    button.setProperty('transformationKind', kind)
                    button.setIconSize(QSize(24, 24))
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    buttons.addWidget(button)
                control_action = basic_row.addWidget(control)
                self.transformation_controls.append((label_action, control_action,
                                                     control, tuple(action for _, action in pair)))
                continue
            if len(pair) != 2:
                raise ValueError('Paired actions must have exactly two members')
            label = pair[0][0].pair_label or pair[0][0].pair_id
            label_widget = QLabel(f'  {label}:', basic_row)
            label_action = basic_row.addWidget(label_widget)
            control = StepControl(pair[0][1], pair[1][1], basic_row,
                                  show_disabled_labels=pair[0][0].pair_id == 'rotate')
            control_action = basic_row.addWidget(control)
            self.paired_extension_controls.append((label_action, control_action,
                                                    control, pair[0][1], pair[1][1]))

        edition_row = row('Structure', (self.directed_action, self.multiedges_action, self.loops_action))
        edition_row.addSeparator()
        edition_row.addAction(self.cut_action)
        edition_row.addAction(self.full_join_action)
        self.full_join_button = edition_row.widgetForAction(self.full_join_action)
        from graph_builder_core.ui.widgets import style_staged_button
        style_staged_button(self.full_join_button)
        edition_row.addActions(tuple(action for definition, action in self.extension_actions
                                     if definition.group == 'edition' and not definition.pair_id))
        edition_row.addSeparator()
        product_menu = QMenu(edition_row)
        product_menu.addActions(tuple(self.product_actions.values()))
        self.product_button = QToolButton(edition_row)
        self.product_button.setText('Product')
        self.product_button.setCheckable(True)
        self.product_button.setToolTip('Choose a product of two selected vertex sets.')
        self.product_button.setFixedSize(140, 30)
        self.product_button.setPopupMode(QToolButton.InstantPopup)
        self.product_button.setMenu(product_menu)
        self.product_button.clicked.connect(self._product_button_clicked)
        self.product_button.setStyleSheet('''
            QToolButton { color: #111111; background: #f5f6f7;
                          border: 1px solid #b8bec4; border-radius: 4px;
                          padding: 3px 15px 3px 5px; }
            QToolButton::menu-indicator { subcontrol-origin: padding;
                                          subcontrol-position: right center; right: 5px; }
            QToolButton:checked { color: #111111; background: #fff1d8;
                                  border: 2px solid #a76a12; font-weight: 700; }
        ''')
        edition_row.addWidget(self.product_button)

        grid_row = row('Layout', (self.fit_action, self.grid_off_action,
                                self.grid_automatic_action,
                                self.grid_axis_action,
                                self.grid_square_action, self.grid_radial_action,
                                self.grid_triangular_action))
        grid_row.insertSeparator(self.grid_off_action)
        self.grid_options_separator = grid_row.addSeparator()
        self.automatic_actions = (self.arrange_action, self.pin_action, self.unpin_action,
                                  self.clear_pins_action, self.live_layout_action)
        grid_row.addActions(self.automatic_actions)
        grid_row.addAction(self.axis_snap_action)
        self.grid_unit_label = QLabel(grid_row)
        self.grid_unit_label_action = grid_row.addWidget(self.grid_unit_label)
        self.grid_unit_control = StepControl(self.grid_down_action, self.grid_up_action, grid_row)
        self.grid_unit_control_action = grid_row.addWidget(self.grid_unit_control)
        self.radial_label = QLabel(grid_row)
        self.radial_label_action = grid_row.addWidget(self.radial_label)
        self.radial_control = StepControl(self.radial_down_action, self.radial_up_action, grid_row)
        self.radial_control_action = grid_row.addWidget(self.radial_control)

        properties_row = row('Appearances', (self.make_region_action, self.labels_action, self.add_curve_action,
                                             self.rename_action, self.remove_coloring_action))
        properties_row.addWidget(QLabel('  Style:', properties_row))
        self.type_control = StepControl(self.previous_type_action, self.next_type_action,
                                        properties_row)
        properties_row.addWidget(self.type_control)
        self.style_menu = QMenu(properties_row)
        self.style_menu.addActions((self.properties_action, self.styles_action,
                               self.copy_style_action, self.paste_style_action))
        from graph_builder_core.ui.widgets import menu_button
        self.style_button = menu_button('Styles', self.style_menu, properties_row)
        self.style_button.setMinimumWidth(92)
        properties_row.addWidget(self.style_button)
        self.vertex_colors_label = QLabel(properties_row)
        properties_row.addWidget(self.vertex_colors_label)
        self.vertex_colors_control = StepControl(self.vertex_colors_down_action,
                                                  self.vertex_colors_up_action, properties_row)
        properties_row.addWidget(self.vertex_colors_control)
        self.edge_colors_label = QLabel(properties_row)
        properties_row.addWidget(self.edge_colors_label)
        self.edge_colors_control = StepControl(self.edge_colors_down_action,
                                                self.edge_colors_up_action, properties_row)
        properties_row.addWidget(self.edge_colors_control)

        info_row = row('Properties', (self.subgraph_action, self.induced_subgraph_action,
                                      self.morphism_action, self.minor_action))
        for action in (self.subgraph_action, self.induced_subgraph_action,
                       self.morphism_action, self.minor_action):
            button = info_row.widgetForAction(action)
            button.setFixedSize(button.sizeHint().width() + 8, button.sizeHint().height())
            button.setStyleSheet(self.full_join_button.styleSheet())
        info_row.addSeparator()
        info_row.addActions(tuple(self.info_actions.values()))
        self.info_scope = QComboBox()
        self.info_scope.addItems(('Whole graph', 'Selection'))
        self.info_scope.setStyleSheet('QComboBox { color: #111111; background: #f5f6f7; '
                                     'border: 1px solid #b8bec4; border-radius: 4px; padding: 3px 8px; } '
                                     'QComboBox QAbstractItemView { color: #111111; background: white; }')
        self.info_scope.currentIndexChanged.connect(self._info_scope_changed)
        info_row.addSeparator()
        info_row.addAction(self.house_of_graphs_action)

        standard_row = row('Standard graphs')
        self.standard_graph_choice = QComboBox(standard_row)
        self.standard_graph_choice.setMinimumWidth(190)
        self.standard_graph_choice.setStyleSheet('''
            QComboBox { color: #111111; background: #f5f6f7;
                        border: 1px solid #b8bec4; border-radius: 4px;
                        padding: 3px 8px; }
            QComboBox QAbstractItemView { color: #111111; background: #ffffff;
                                         selection-color: #111111;
                                         selection-background-color: #d4e7e8; }
        ''')
        choice_palette = self.standard_graph_choice.palette()
        for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
            choice_palette.setColor(role, QColor('#111111'))
        choice_palette.setColor(QPalette.Button, QColor('#f5f6f7'))
        choice_palette.setColor(QPalette.Base, QColor('#ffffff'))
        self.standard_graph_choice.setPalette(choice_palette)
        self.standard_parameter_stack = QStackedWidget(standard_row)
        self.standard_parameter_inputs = {}
        for definition in self.standard_graphs:
            self.standard_graph_choice.addItem(definition.title, definition.key)
            page = QWidget(self.standard_parameter_stack)
            fields = QHBoxLayout(page)
            fields.setContentsMargins(0, 0, 0, 0)
            fields.setSpacing(5)
            inputs = {}
            for parameter in definition.parameters:
                fields.addWidget(QLabel(parameter.label + ':', page))
                if parameter.kind == 'probability':
                    control = QDoubleSpinBox(page)
                    control.setDecimals(3)
                    control.setSingleStep(.05)
                else:
                    control = QSpinBox(page)
                    if parameter.kind == 'optional_seed':
                        control.setSpecialValueText('Random')
                control.setRange(parameter.minimum, parameter.maximum)
                control.setValue(parameter.default)
                control.setFixedWidth(82 if parameter.kind == 'optional_seed' else 66)
                control.valueChanged.connect(self._update_standard_graph_form)
                fields.addWidget(control)
                inputs[parameter.key] = control
            self.standard_parameter_inputs[definition.key] = inputs
            self.standard_parameter_stack.addWidget(page)
        standard_row.addWidget(self.standard_graph_choice)
        standard_row.addWidget(self.standard_parameter_stack)
        self.standard_add_action = self._action('Add graph', lambda: self.add_standard_graph())
        self.standard_add_action.setProperty('description',
            'Insert the chosen graph at the center of the view and select its vertices.')
        self._set_action_tooltip(self.standard_add_action)
        standard_row.addAction(self.standard_add_action)
        self.standard_info_label = QLabel(standard_row)
        self.standard_info_label.setStyleSheet('color: #555c63; padding-left: 8px;')
        standard_row.addWidget(self.standard_info_label)
        self.standard_graph_choice.currentIndexChanged.connect(self._change_standard_graph)
        self._change_standard_graph()

        self.extension_texts = []
        self.extension_steps = []
        self.extension_search_controls = []
        for menu in self.extra_menus:
            build_extension_menu(self, menu, row(menu.name))

        custom = [action for definition, action in self.extension_actions
                  if definition.group not in ('basic', 'edition')
                  and not definition.group.startswith('menu:')]
        custom_row = row('Custom', custom)
        if not custom:
            custom_row.addWidget(QLabel(
                'No custom actions. Run a Python script to add your own functions.',
                custom_row))
            help_action = self._action('How to add functions', self.show_custom_help)
            help_action.setProperty('description',
                'Learn how to add functions with a personal Python script.')
            self._set_action_tooltip(help_action)
            custom_row.addAction(help_action)
        right_utilities = QWidget(tabs.tabBar())
        right_layout = QHBoxLayout(right_utilities)
        right_layout.setContentsMargins(0, 0, 8, 0)
        right_layout.setSpacing(3)
        right_layout.addWidget(self.search_button)
        right_layout.addWidget(self.help_button)
        tabs.tabBar().setTabButton(tabs.count() - 1, QTabBar.RightSide, right_utilities)
        tabs.open_tab(0)
        layout.addWidget(tabs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(container)
        self.info_dock = QDockWidget('Graph properties', self)
        self.info_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.info_dock.setMinimumWidth(315)
        self.info_text = QTextEdit(self.info_dock)
        self.info_text.setReadOnly(True)
        self.info_text.viewport().installEventFilter(self)
        self.info_text.setStyleSheet('QTextEdit { color: #111111; background: #ffffff; padding: 8px; }')
        self.bounds_panel = QWidget(self.info_dock)
        self.bounds_panel.setStyleSheet('QWidget#boundsPanel { background: #ffffff; }')
        self.bounds_panel.setObjectName('boundsPanel')
        bounds_layout = QVBoxLayout(self.bounds_panel)
        bounds_layout.setContentsMargins(10, 10, 10, 10)
        bounds_layout.setSpacing(10)
        self.bound_heading = QLabel(self.bounds_panel)
        self.bound_heading.setStyleSheet('color: #111111; font-weight: 600;')
        bounds_layout.addWidget(self.bound_heading)
        self.bound_labels = {}
        self.bound_solve_buttons = {}
        self.bound_color_buttons = {}
        self._bound_tooltip_rows = {}
        for problem in BOUND_PROBLEMS:
            line = QWidget(self.bounds_panel)
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 3, 0, 3)
            label = QLabel(line)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            label.setStyleSheet('color: #111111;')
            definition = INFO_DEFINITIONS.get({
                'clique': 'Clique number ω', 'independent': 'Independence number α',
                'chromatic': 'Chromatic number', 'edge_chromatic': 'Edge chromatic number',
                'vertex_cover': 'Minimum vertex cover', 'edge_cover': 'Minimum edge cover ρ',
                'matching': 'Maximum matching ν', 'domination': 'Domination number',
                'domatic': 'Domatic number', 'treewidth': 'Tree-width',
            }[problem])
            label.setToolTip(definition)
            line.setToolTip(definition)
            for widget in (line, label):
                widget.setMouseTracking(True)
                widget.installEventFilter(self)
                self._bound_tooltip_rows[widget] = (line, label)
            line_layout.addWidget(label, 1)
            controls = QVBoxLayout()
            controls.setSpacing(4)
            solve = QToolButton(line)
            solve.setText('Compute')
            solve.setToolTip('Search for up to one minute. You can stop earlier.')
            solve.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                'border: 1px solid #b8bec4; border-radius: 4px; padding: 4px; } '
                                'QToolButton:disabled { color: #777777; border-color: #d5d5d5; }')
            solve.clicked.connect(lambda checked=False, key=problem: self.bound_button_clicked(key))
            controls.addWidget(solve)
            color = QToolButton(line)
            color.setText('Show')
            color.setToolTip('Show the solution on the canvas. Undo restores the previous drawing.')
            color.setStyleSheet(solve.styleSheet())
            color.clicked.connect(lambda checked=False, key=problem: self.show_bound_solution(key))
            color.hide()
            controls.addWidget(color)
            line_layout.addLayout(controls)
            bounds_layout.addWidget(line)
            self.bound_labels[problem] = label
            self.bound_solve_buttons[problem] = solve
            self.bound_color_buttons[problem] = color
        self.bound_note = QLabel(self.bounds_panel)
        self.bound_note.setWordWrap(True)
        self.bound_note.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.bound_note.setStyleSheet('color: #555c63;')
        bounds_layout.addWidget(self.bound_note)
        bounds_layout.addStretch()
        self.bounds_scroll = QScrollArea(self.info_dock)
        self.bounds_scroll.setWidgetResizable(True)
        self.bounds_scroll.setFrameShape(QFrame.NoFrame)
        self.bounds_scroll.setStyleSheet('QScrollArea { background: #ffffff; border: 0; }')
        self.bounds_scroll.setWidget(self.bounds_panel)
        self.info_stack = QStackedWidget(self.info_dock)
        self.info_stack.addWidget(self.info_text)
        self.info_stack.addWidget(self.bounds_scroll)
        self.custom_parameter_panel = QWidget(self.info_dock)
        self.custom_parameter_panel.setObjectName('customParameterPanel')
        self.custom_parameter_panel.setStyleSheet(
            'QWidget#customParameterPanel { background: #ffffff; } '
            'QWidget#customParameterPanel QLabel { color: #111111; }')
        custom_layout = QVBoxLayout(self.custom_parameter_panel)
        custom_layout.setContentsMargins(10, 10, 10, 10)
        custom_layout.setSpacing(10)
        self.custom_parameter_heading = QLabel(self.custom_parameter_panel)
        self.custom_parameter_heading.setStyleSheet('color: #111111; font-weight: 600;')
        custom_layout.addWidget(self.custom_parameter_heading)
        self.custom_parameter_rows = []
        for index, definition in enumerate(self.custom_parameters):
            line = QWidget(self.custom_parameter_panel)
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(0, 3, 0, 3)
            text = QLabel(line)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            text.setToolTip(definition.description)
            line_layout.addWidget(text, 1)
            compute = QToolButton(line)
            compute.setText('Compute')
            compute.setToolTip('Run the optional deeper computation.')
            compute.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                  'border: 1px solid #b8bec4; border-radius: 4px; padding: 4px; }')
            compute.clicked.connect(lambda checked=False, index=index: self.compute_custom_parameter(index))
            compute.setVisible(definition.compute is not None)
            line_layout.addWidget(compute)
            show = QToolButton(line)
            show.setText('Show')
            show.setToolTip('Show this result on the graph. Undo restores the drawing.')
            show.setStyleSheet(compute.styleSheet())
            show.clicked.connect(lambda checked=False, index=index: self.show_custom_parameter(index))
            show.setVisible(definition.show is not None)
            line_layout.addWidget(show)
            custom_layout.addWidget(line)
            self.custom_parameter_rows.append((text, compute, show))
        custom_layout.addStretch()
        self.custom_parameter_scroll = QScrollArea(self.info_dock)
        self.custom_parameter_scroll.setWidgetResizable(True)
        self.custom_parameter_scroll.setFrameShape(QFrame.NoFrame)
        self.custom_parameter_scroll.setStyleSheet('QScrollArea { background: #ffffff; border: 0; }')
        self.custom_parameter_scroll.setWidget(self.custom_parameter_panel)
        self.info_stack.addWidget(self.custom_parameter_scroll)
        info_container = QWidget(self.info_dock)
        info_container.setStyleSheet('background: #ffffff;')
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        scope_row = QWidget(info_container)
        scope_layout = QHBoxLayout(scope_row)
        scope_layout.setContentsMargins(10, 8, 10, 8)
        scope_layout.addWidget(QLabel('Show:', scope_row))
        self.info_scope.setParent(scope_row)
        scope_layout.addWidget(self.info_scope, 1)
        info_layout.addWidget(scope_row)
        self.perfect_compute_button = QToolButton(info_container)
        self.perfect_compute_button.setText('Compute perfect graph')
        self.perfect_compute_button.setToolTip('Check for an induced odd hole or antihole, with a one-minute limit.')
        self.perfect_compute_button.setStyleSheet(
            'QToolButton { color: #111111; background: #f5f6f7; '
            'border: 1px solid #b8bec4; border-radius: 4px; padding: 5px 8px; '
            'margin: 2px 10px; } QToolButton:hover { background: #e6ecee; }')
        self.perfect_compute_button.clicked.connect(self.compute_perfect_graph)
        info_layout.addWidget(self.perfect_compute_button)
        self.perfect_compute_button.hide()
        info_layout.addWidget(self.info_stack, 1)
        self.info_outdated_bar = QWidget(info_container)
        refresh_layout = QHBoxLayout(self.info_outdated_bar)
        refresh_layout.setContentsMargins(10, 5, 10, 8)
        refresh_label = QLabel('Outdated — graph or selection changed', self.info_outdated_bar)
        refresh_label.setStyleSheet('color: #555c63;')
        refresh_layout.addWidget(refresh_label, 1)
        self.info_refresh_button = QToolButton(self.info_outdated_bar)
        self.info_refresh_button.setText('⟳')
        self.info_refresh_button.setToolTip('Refresh these metrics')
        self.info_refresh_button.setStyleSheet('QToolButton { color: #111111; background: #f5f6f7; '
                                              'border: 1px solid #b8bec4; border-radius: 4px; '
                                              'font-size: 18px; min-width: 24px; min-height: 24px; }')
        self.info_refresh_button.clicked.connect(self.refresh_graph_info)
        refresh_layout.addWidget(self.info_refresh_button)
        info_layout.addWidget(self.info_outdated_bar)
        self.info_outdated_bar.hide()
        self.info_dock.setWidget(info_container)
        self.addDockWidget(Qt.RightDockWidgetArea, self.info_dock)
        self.info_dock.hide()
        self.help_dock = QDockWidget('Controls', self)
        self.help_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.help_dock.setMinimumWidth(290)
        self.help_text = QTextBrowser(self.help_dock)
        self.help_text.setStyleSheet('QTextBrowser { color: #111111; background: #ffffff; padding: 8px; }')
        self.help_text.setOpenExternalLinks(True)
        self.help_text.setHtml(f'''
            <h3>Quick controls</h3>
            <p><b>Create:</b> Click empty space for a vertex. Secondary-drag
            between vertices to add or remove an edge. Alt-click inside a region to add a vertex there.
            Secondary-click a vertex to delete it or press Delete.</p>
            <p><b>Select:</b> Click an object, drag a rectangle in empty space,
            or secondary-drag there for a lasso.</p>
            <p><b>Move and navigate:</b> Drag one or multiple vertices to move them.
            Press Space to fit the graph in view. Alt+drag to pan. Mouse wheel to zoom.</p>
            <p><b>Edit:</b> Double-click a vertex or edge to edit its label and style. Basic styles can be edited in Appearances. Use S to change style.
            Use Edition or Structure for graph operations.</p>
            <p><small>Secondary-click means right-click, or Ctrl-click on a
            trackpad.</small></p>
            <h3>Essential menus</h3>
            <p><b>File</b> saves, loads and exports.<br>
            <b>Edition</b> has undo, selection and transformations.<br>
            <b>Structure</b> has graph operations, graph types, and regions.<br>
            <b>Layout</b> has Fit graph, manual, automatic, and guided positioning.<br>
            <b>Appearances</b> has labels, styles and curves.<br>
            <b>Standard graphs</b> inserts familiar graph families.<br>
            <b>Properties</b> computes graph measures and tests graph relations.<br>
            <b>Custom</b> shows actions added by your Python script.</p>
            <p>The ⚙ button before File opens Preferences for keyboard shortcuts and theme.</p>
            <a name="custom-buttons"></a><h3>Add your own functions</h3>
            <p>The downloaded app does not load personal Python code. To add actions,
            parameters, or extension menus, install the library and launch it from your own script.
            See <a href="https://github.com/CyrilPujol/graph-builder/blob/main/docs/CUSTOM_PYTHON.md">the Custom Python guide</a> for setup and examples.</p>
            <h3>About</h3>
            <p>Created by Cyril Pujol.<br>
            <a href="https://github.com/CyrilPujol/graph-builder">GitHub</a> ·
            <a href="https://www.irif.fr/~cpujol/">Webpage</a></p>
            <p><small>Version {APP_VERSION}</small></p>
        ''')
        help_content = QWidget(self.help_dock)
        help_layout = QVBoxLayout(help_content)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help_layout.setSpacing(0)
        self.replay_tutorial_button = QToolButton(help_content)
        self.replay_tutorial_button.setText('↻  Replay tutorial…')
        self.replay_tutorial_button.setToolTip('Start the quick tour again with its example graph')
        self.replay_tutorial_button.setStyleSheet('''
            QToolButton { color: #176f6b; background: #edf6f4; border: 0;
                          text-align: left; padding: 10px 12px; font-weight: 600; }
            QToolButton:hover { background: #dcefeb; }
        ''')
        self.replay_tutorial_button.clicked.connect(self.replay_tutorial)
        help_layout.addWidget(self.replay_tutorial_button)
        help_layout.addWidget(self.help_text, 1)
        self.help_dock.setWidget(help_content)
        self.addDockWidget(Qt.RightDockWidgetArea, self.help_dock)
        self.help_dock.hide()
        self.tutorial_dock = QDockWidget('Getting started', self)
        self.tutorial_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.tutorial_dock.setMinimumWidth(300)
        self.tutorial_panel = TutorialPanel(self.tutorial_dock)
        self.tutorial_panel.finished.connect(self.finish_tutorial)
        self.tutorial_dock.setWidget(self.tutorial_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tutorial_dock)
        self.tutorial_dock.hide()
        self.tutorial_active = False
        self.picture_dock = QDockWidget('Picture preview', self)
        self.picture_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.picture_dock.setMinimumWidth(340)
        self.picture_preview = PicturePreview(self.picture_dock)
        self.picture_preview.save_requested.connect(self._save_picture_preview)
        self.picture_dock.setWidget(self.picture_preview)
        self.addDockWidget(Qt.RightDockWidgetArea, self.picture_dock)
        self.picture_dock.hide()
        self.add_curve_action.triggered.connect(
            lambda checked=False: self._observe_tutorial('curve_edge'))
        tabs.tabBarClicked.connect(self._observe_tutorial_menu)
        self.help_button.clicked.connect(self.toggle_help)
        # Actions in inactive tabs still need their keyboard shortcuts active.
        for _, action in self._shortcut_registry.values():
            if not action.shortcut().isEmpty():
                self.addAction(action)
        self._sync_controls()
