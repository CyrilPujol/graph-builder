"""First-run example graph and compact in-window tutorial panel."""
from __future__ import annotations

from math import cos, pi, sin

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from graph_builder_core.geometry.curves import _set_edge_curve_points
from graph_builder_core.model.document import empty_graph
from graph_builder_core.model.operations import flip_edge


TUTORIAL_STEPS = (
    ('Add the missing center', 'create_vertex',
     'Click the empty space to add a vertex.'),
    ('Move the selection', 'move_vertex',
     'Click to select and drag the selected vertex to move it.<br>'
     'You can also select and move multiple vertices.'),
    ('Change its style', 'change_appearance',
     'Change the vertex’s style. Double-click the vertex to see its properties '
     'or press S to cycle styles.'),
    ('Add edges', 'create_edge',
     'Right-drag or Ctrl-drag between vertices to create or remove an edge.'),
    ('Curve an edge', 'curve_edge',
     'Click an edge to select it, then drag it to bend it. '
     'Or use Appearances → Curve point.'),
    ('Explore the menus', 'menu_any',
     'Click any menu above to see its controls.<br><br>'
     '<b>File</b> saves, opens, and exports drawings.<br>'
     '<b>Edition</b> handles undo, selection, and transformations.<br>'
     '<b>Structure</b> changes vertices, edges, graph type, and regions.<br>'
     '<b>Layout</b> offers grid guides and automatic ways to position vertices.<br>'
     '<b>Appearances</b> controls labels, styles, and curve points.<br>'
     '<b>Properties</b> computes graph measures and bounds, and tests graph relations.<br>'
     '<b>Standard graphs</b> adds familiar graph families.<br>'
     '<b>Custom</b> holds functions added by a Python script.'),
    ('Your canvas is ready', None,
     'Keep exploring this drawing. File → New starts a blank canvas, and the ? '
     'button can replay this tour or show the quick controls.'),
)


def tutorial_graph():
    """A curved Mycielski graph of C5 missing its central vertex."""
    graph = empty_graph(num_vertex_styles=5)
    outer_colors = (1, 2, 3, 1, 2)
    outer_radius, inner_radius = 205.0, 103.0
    for index in range(5):
        angle = -pi / 2 + 2 * pi * index / 5
        x, y = cos(angle), sin(angle)
        graph.add_node(str(index), position=(outer_radius*x, outer_radius*y),
                       style=outer_colors[index], label=str(index))
        graph.add_node(str(index + 5), position=(inner_radius*x, inner_radius*y),
                       style=outer_colors[index], label=str(index + 5))
    for index in range(5):
        neighbor = (index + 1) % 5
        flip_edge(graph, str(index), str(neighbor))
        midpoint_angle = -pi / 2 + 2 * pi * (index + .5) / 5
        _set_edge_curve_points(graph, str(index), str(neighbor),
                               [(224*cos(midpoint_angle), 224*sin(midpoint_angle))])
        for neighbor in ((index - 1) % 5, (index + 1) % 5):
            flip_edge(graph, str(index + 5), str(neighbor))
    return graph


class TutorialPanel(QFrame):
    """A compact tour that advances after real editor actions and allows skipping."""
    finished = Signal()
    step_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step = 0
        self.completed = set()
        self._pending_events = set()
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self.advance)
        self.setObjectName('tutorialPanel')
        self.setStyleSheet('''
            QFrame#tutorialPanel { background: #f7faf9; border: 0; }
            QLabel#eyebrow { color: #167f79; font-size: 11px; font-weight: 700; }
            QLabel#title { color: #172b36; font-size: 21px; font-weight: 700; }
            QLabel#body { color: #33434d; font-size: 14px; }
            QLabel#progress { color: #687982; font-size: 12px; }
            QPushButton#nextButton { color: white; background: #167f79;
                                     border: 0; border-radius: 5px;
                                     padding: 8px 13px; font-weight: 600; }
            QPushButton#nextButton:hover { background: #106a65; }
            QPushButton#quietButton { color: #536670; background: transparent;
                                      border: 0; padding: 8px; }
            QPushButton#quietButton:hover { color: #172b36; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 16)
        layout.setSpacing(10)
        eyebrow = QLabel('GRAPH BUILDER · QUICK TOUR')
        eyebrow.setObjectName('eyebrow')
        layout.addWidget(eyebrow)
        self.title = QLabel()
        self.title.setObjectName('title')
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.progress = QLabel()
        self.progress.setObjectName('progress')
        layout.addWidget(self.progress)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, len(TUTORIAL_STEPS))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(7)
        self.progress_bar.setStyleSheet('''
            QProgressBar { border: 0; background: #dbe8e5; border-radius: 3px; }
            QProgressBar::chunk { background: #167f79; border-radius: 3px; }
        ''')
        layout.addWidget(self.progress_bar)
        self.body = QLabel()
        self.body.setObjectName('body')
        self.body.setWordWrap(True)
        layout.addWidget(self.body)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setStyleSheet('color: #167f79; font-size: 13px; font-weight: 600;')
        layout.addWidget(self.result)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.skip_button = QPushButton('Skip tour')
        self.skip_button.setObjectName('quietButton')
        self.skip_button.clicked.connect(self.finished)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        self.previous_button = QPushButton('←  Previous')
        self.previous_button.setObjectName('quietButton')
        self.previous_button.clicked.connect(self.previous)
        buttons.addWidget(self.previous_button)
        self.next_button = QPushButton()
        self.next_button.setObjectName('nextButton')
        self.next_button.clicked.connect(self.advance)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)
        self._refresh()

    def observe(self, move):
        if self._advance_timer.isActive():
            self._pending_events.add(move)
            return
        if move != TUTORIAL_STEPS[self.step][1]:
            return
        self.completed.add(self.step)
        self._refresh()
        self._advance_timer.start(1000)

    def restart(self):
        self._advance_timer.stop()
        self.step = 0
        self.completed.clear()
        self._pending_events.clear()
        self._refresh()

    def stop(self):
        self._advance_timer.stop()
        self._pending_events.clear()

    def previous(self):
        if self.step == 0:
            return
        self._advance_timer.stop()
        self._pending_events.clear()
        self.step -= 1
        self._refresh()
        self.step_changed.emit(self.step)

    def advance(self):
        pending = self._pending_events.copy() if self.sender() is self._advance_timer else set()
        self._advance_timer.stop()
        self._pending_events.clear()
        if self.step == len(TUTORIAL_STEPS) - 1:
            self.finished.emit()
        else:
            self.step += 1
            self._refresh()
            self.step_changed.emit(self.step)
            if TUTORIAL_STEPS[self.step][1] in pending:
                self.observe(TUTORIAL_STEPS[self.step][1])

    def _refresh(self):
        title, action, explanation = TUTORIAL_STEPS[self.step]
        self.title.setText(title)
        self.progress.setText(f'Step {self.step + 1} of {len(TUTORIAL_STEPS)}')
        self.progress_bar.setValue(self.step + 1)
        self.body.setText(explanation)
        done = self.step in self.completed
        self.result.setText('✓ Done' if done else '')
        last = self.step == len(TUTORIAL_STEPS) - 1
        self.next_button.setText('Finish' if last else 'Next  →' if done else 'Skip step  →')
        self.previous_button.setEnabled(self.step > 0)
        self.skip_button.setVisible(not last)
