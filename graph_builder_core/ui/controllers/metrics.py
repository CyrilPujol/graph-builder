"""MetricsController methods hosted by GraphBuilderQt."""
from __future__ import annotations

import json
import re
import copy
import inspect

from PySide6.QtCore import QProcess, QRect, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import QApplication, QToolTip

from graph_builder_core.algorithms.metrics import (
    ANALYSIS_TIMEOUT_MS, OPTIMIZATION_TIMEOUT_MS, BOUND_PROBLEMS, BOUND_SYMBOLS,
    SHOWABLE_BOUNDS, DIRECT_BOUNDS, INFO_DEFINITIONS, topology_payload,
)
from graph_builder_core.extensions import ParameterResult, normalize_graph, public_graph
from graph_builder_core.actions import Action
from graph_builder_core.model.edges import edge_data, visible_edges
from graph_builder_core.model.document import _deserialize_graph, _serialize_graph
from graph_builder_core.model.regions import add_region, regions, remove_regions
from graph_builder_core.model.selection import selected_vertices
from graph_builder_core.model.styles import use_basic_style
from graph_builder_core.ui.workers import prepare_worker, start_worker, release_worker


class MetricsController:
    def _info_definition_at(self, position):
        """Return the definition and visible line area under a viewport point."""
        block = self.info_text.cursorForPosition(position).block()
        definition = INFO_DEFINITIONS.get(block.text().partition(':')[0])
        if not definition:
            return None
        first = QTextCursor(block)
        last = QTextCursor(block)
        last.setPosition(block.position() + len(block.text()))
        top = self.info_text.cursorRect(first).top()
        bottom = self.info_text.cursorRect(last).bottom()
        area = QRect(0, top, self.info_text.viewport().width(), bottom - top + 1)
        return (definition, area) if area.contains(position) else None

    def _reset_bound_revert(self):
        self._bound_revert_state = None
        self._bound_revert_problem = None
        if hasattr(self, 'bound_color_buttons'):
            for button in self.bound_color_buttons.values():
                button.setText('Show')
                button.setToolTip('Show the solution on the canvas.')
        if hasattr(self, 'custom_parameter_rows'):
            for _, _, button in self.custom_parameter_rows:
                button.setText('Show')
                button.setToolTip('Show this result on the graph. Undo restores the drawing.')

    def _revert_shown_result(self):
        custom_result = isinstance(self._bound_revert_problem, str) and self._bound_revert_problem.startswith('custom:')
        self.graph = _deserialize_graph(copy.deepcopy(self._bound_revert_state))
        self._reset_bound_revert()
        self.rebuild_scene()
        self._preserve_custom_result = custom_result
        try:
            self.commit_change()
        finally:
            self._preserve_custom_result = False
        self.report('Previous appearance restored.')

    def _display_info(self, kind, scope, lines):
        if self._info_tooltip_text is not None:
            QToolTip.hideText()
            self._info_tooltip_text = None
        self.info_text.setPlainText(f'{kind} · {scope}\n\n' + '\n'.join(lines))
        self.perfect_compute_button.setVisible(
            kind in ('Classes', 'Structure') and
            any(line.startswith('Perfect: Unknown') for line in lines))
        self.perfect_compute_button.setText('Compute perfect graph')
        if kind == 'Bounds' and len(lines) >= len(BOUND_PROBLEMS):
            self._bound_results = {}
            self.bound_heading.setText(f'Bounds · {scope}')
            for index, problem in enumerate(BOUND_PROBLEMS):
                quick_line = lines[index]
                self._bound_quick_lines[problem] = quick_line
                self.bound_labels[problem].setText(quick_line)
                self.bound_solve_buttons[problem].setEnabled(True)
                self.bound_solve_buttons[problem].setText('Compute')
                exact_value = re.search(
                    rf'{re.escape(BOUND_SYMBOLS[problem])}: (\d+)$', quick_line)
                quick_proved = bool(exact_value)
                self.bound_solve_buttons[problem].setVisible(
                    problem not in DIRECT_BOUNDS and not quick_proved)
                self.bound_color_buttons[problem].setVisible(
                    (bool(exact_value) and int(exact_value.group(1)) > 0)
                    or self._bound_revert_problem == problem)
                self.bound_color_buttons[problem].setText(
                    'Revert' if self._bound_revert_problem == problem else 'Show')
            self.bound_note.setText('\n'.join(lines[len(BOUND_PROBLEMS):]))
            self.info_stack.setCurrentWidget(self.bounds_scroll)
        else:
            self.info_stack.setCurrentWidget(self.info_text)
        self.help_dock.hide()
        self.picture_dock.hide()
        self.tikz_dock.hide()
        self.info_dock.show()
        self._info_has_result = True
        self._info_outdated = False
        self.info_outdated_bar.hide()
        if kind == 'Bounds' and len(lines) >= len(BOUND_PROBLEMS) and self._pending_bound_problem:
            problem = self._pending_bound_problem
            self._pending_bound_problem = None
            QTimer.singleShot(0, lambda: self.solve_bound(problem))

    def _invalidate_info(self):
        self._info_request_id += 1
        self._pending_bound_problem = None
        self._pending_show_problem = None
        self._bound_results = {}
        self.perfect_compute_button.hide()
        if hasattr(self, 'bound_color_buttons'):
            for button in self.bound_color_buttons.values():
                button.hide()
            if self.info_stack.currentWidget() is self.bounds_scroll:
                for problem, button in self.bound_solve_buttons.items():
                    button.setText('Compute')
                    button.setEnabled(True)
                    button.setVisible(problem not in DIRECT_BOUNDS)
        if self._info_process is not None:
            process = self._info_process
            self._info_process = None
            process.kill()
            process.waitForFinished(100)
            self._release_info_process(process)
            process.deleteLater()
            self.info_text.setPlainText('Graph properties\n\nOutdated — graph or selection changed. Run again.')
            self._info_has_result = True
            self._info_outdated = True
        if self._info_has_result and not self._info_outdated:
            self.info_text.append('\nOutdated — graph or selection changed. Run again.')
            self._info_outdated = True
        if self._info_outdated:
            self.info_outdated_bar.show()

    def refresh_graph_info(self):
        if self._info_kind is None:
            return
        if self.info_scope.currentIndex() and not selected_vertices(self.selection):
            self.info_text.setPlainText('Select vertices to inspect their properties.')
            self.info_stack.setCurrentWidget(self.info_text)
            self.info_outdated_bar.hide()
            return
        self.show_graph_info(self._info_kind)

    def _info_scope_changed(self):
        self._invalidate_info()
        self.update_actions()
        self.refresh_graph_info()

    def show_graph_info(self, kind):
        scope_nodes = selected_vertices(self.selection) if self.info_scope.currentIndex() else None
        if scope_nodes is not None and not scope_nodes:
            return
        graph = public_graph(self.graph)
        if scope_nodes is not None:
            graph = graph.subgraph(scope_nodes).copy()
        scope = (f'selection ({len(scope_nodes)} '
                 f'{"vertex" if len(scope_nodes) == 1 else "vertices"})'
                 if scope_nodes is not None else 'whole graph')
        self._info_kind = kind
        self._info_selection_nodes = set(scope_nodes) if scope_nodes is not None else None
        self._info_request_id += 1
        request_id = self._info_request_id
        if self._info_process is not None:
            previous = self._info_process
            previous.kill()
            previous.waitForFinished(100)
            self._release_info_process(previous)
            previous.deleteLater()
            self._info_process = None
        if kind == 'Custom':
            self._show_custom_parameters(graph, scope)
            return
        self._info_has_result = False
        self._bound_results = {}
        self.perfect_compute_button.hide()
        self.info_outdated_bar.hide()
        self.info_text.setPlainText(f'{kind} · {scope}\n\nCalculating…')
        self.info_stack.setCurrentWidget(self.info_text)
        self.help_dock.hide()
        self.picture_dock.hide()
        self.tikz_dock.hide()
        self.info_dock.show()
        process = prepare_worker(self, topology_payload(graph))
        process._bound_problem = None
        self._info_process = process
        process.finished.connect(lambda exit_code, exit_status: self._finish_graph_info(
            request_id, process, kind, scope, exit_code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, kind, scope, error))
        start_worker(process, kind)
        timeout_ms = ANALYSIS_TIMEOUT_MS
        QTimer.singleShot(timeout_ms,
                          lambda: self._timeout_graph_info(request_id, process, kind, scope))

    def _show_custom_parameters(self, graph, scope):
        """Run quick user measures and present optional Compute and Show controls."""
        self._custom_parameter_values = {}
        self.custom_parameter_heading.setText(f'Custom · {scope}')
        for index, definition in enumerate(self.custom_parameters):
            result = ParameterResult()
            arguments = {'result': result} if 'result' in inspect.signature(definition.quick).parameters else {}
            result.value = definition.quick(graph.copy(), **arguments)
            self._custom_parameter_values[index] = result
            label, compute, show = self.custom_parameter_rows[index]
            label.setText(f'{definition.name}: {result.value}')
            compute.setVisible(definition.compute is not None)
            show.setVisible(definition.show is not None)
            reverting = self._bound_revert_problem == f'custom:{index}'
            show.setText('Revert' if reverting else 'Show')
            show.setEnabled(reverting or definition.compute is None or result.data is not None)
        self.info_stack.setCurrentWidget(self.custom_parameter_scroll)
        self.help_dock.hide()
        self.picture_dock.hide()
        self.tikz_dock.hide()
        self.info_dock.show()
        self._info_has_result = True
        self._info_outdated = False
        self.info_outdated_bar.hide()

    def _custom_parameter_graph(self):
        graph = public_graph(self.graph)
        if self._info_selection_nodes is not None:
            graph = graph.subgraph(self._info_selection_nodes).copy()
        return graph

    def compute_custom_parameter(self, index):
        if self._info_outdated:
            self.refresh_graph_info()
        definition = self.custom_parameters[index]
        if definition.compute is None:
            return
        previous = self._custom_parameter_values[index]
        result = ParameterResult(previous.value)
        arguments = {'result': result} if 'result' in inspect.signature(definition.compute).parameters else {}
        result.value = definition.compute(self._custom_parameter_graph(), **arguments)
        result.computed = True
        self._custom_parameter_values[index] = result
        label, _, show = self.custom_parameter_rows[index]
        label.setText(f'{definition.name}: {result.value}')
        show.setEnabled(True)

    def show_custom_parameter(self, index):
        key = f'custom:{index}'
        if self._bound_revert_problem == key and self._bound_revert_state is not None:
            self._revert_shown_result()
            return
        if self._info_outdated:
            self.refresh_graph_info()
        definition = self.custom_parameters[index]
        if definition.show is None:
            return
        result = self._custom_parameter_values[index]
        if definition.compute is not None and not result.computed and result.data is None:
            self.report('Compute this parameter before showing its result.')
            return

        def invoke(context):
            graph = public_graph(context.graph)
            parameters = inspect.signature(definition.show).parameters
            arguments = {}
            if 'result' in parameters and list(parameters).index('result') >= 2:
                arguments['result'] = result
            if 'selection' in parameters:
                arguments['selection'] = (set(self._info_selection_nodes)
                                          if self._info_selection_nodes is not None else None)
            shown = definition.show(graph, result.value, **arguments)
            center = tuple(self.view.mapToScene(self.view.viewport().rect().center()).toTuple())
            normalized, _ = normalize_graph(graph if shown is None else shown,
                                            context.graph, center)
            context.graph = normalized

        self.run_extension(Action(f'parameter:{index}', f'Show {definition.name}', None,
                                  invoke, lambda context: True), revert_key=key)

    def bound_button_clicked(self, problem):
        if self._info_process is not None and self._info_process._bound_problem == problem:
            self.stop_bound(problem)
        else:
            self.solve_bound(problem)

    def stop_bound(self, problem):
        process = self._info_process
        if process is None or process._bound_problem != problem:
            return
        self._info_request_id += 1
        self._info_process = None
        if self._pending_show_problem == problem:
            self._pending_show_problem = None
        process.kill()
        process.waitForFinished(100)
        self._release_info_process(process)
        process.deleteLater()
        self.bound_labels[problem].setText(self._bound_quick_lines.get(problem, '') + '\nStopped.')
        button = self.bound_solve_buttons[problem]
        button.setText('Compute')
        button.setVisible(problem not in DIRECT_BOUNDS)
        self.bound_color_buttons[problem].setVisible(problem in DIRECT_BOUNDS)
        self.info_text.setPlainText(self.bound_heading.text() + '\n\n' + '\n'.join(
            self.bound_labels[key].text() for key in BOUND_PROBLEMS))

    def solve_bound(self, problem):
        """Run only the requested invariant in the existing bounded worker."""
        if problem not in self.bound_labels:
            return
        if self._info_outdated:
            self._pending_bound_problem = problem
            self.refresh_graph_info()
            return
        graph = public_graph(self.graph)
        if self._info_selection_nodes is not None:
            graph = graph.subgraph(self._info_selection_nodes).copy()
        self._info_request_id += 1
        request_id = self._info_request_id
        if self._info_process is not None:
            previous = self._info_process
            self._info_process = None
            if self._pending_show_problem == previous._bound_problem:
                self._pending_show_problem = None
            previous.kill()
            previous.waitForFinished(100)
            self._release_info_process(previous)
            if previous._bound_problem:
                prior = previous._bound_problem
                self.bound_labels[prior].setText(self._bound_quick_lines.get(prior, '') + ' · Canceled')
                self.bound_solve_buttons[prior].setText('Compute')
                self.bound_solve_buttons[prior].show()
            previous.deleteLater()
        self.bound_solve_buttons[problem].setText('Stop')
        self.bound_solve_buttons[problem].setEnabled(True)
        self.bound_solve_buttons[problem].show()
        self.bound_color_buttons[problem].hide()
        self._bound_results.pop(problem, None)
        self.bound_labels[problem].setText(self.bound_labels[problem].text().split(' · ')[0]
                                           + ' · Computing…')
        process = prepare_worker(self, topology_payload(graph))
        process._bound_problem = problem
        self._info_process = process
        scope = (f'selection ({len(self._info_selection_nodes)} vertices)'
                 if self._info_selection_nodes is not None else 'whole graph')
        kind = f'Solve:{problem}'
        process.finished.connect(lambda exit_code, exit_status: self._finish_graph_info(
            request_id, process, kind, scope, exit_code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, kind, scope, error))
        start_worker(process, kind)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS,
                          lambda: self._timeout_graph_info(request_id, process, kind, scope))

    def _display_bound_solution(self, problem, payload):
        solve_button = self.bound_solve_buttons[problem]
        solve_button.setText('Compute')
        solve_button.setEnabled(True)
        solve_button.show()
        if 'error' in payload:
            if self._pending_show_problem == problem:
                self._pending_show_problem = None
            self._bound_results.pop(problem, None)
            self.bound_labels[problem].setText(
                self._bound_quick_lines.get(problem, '') + '\n' + payload['error'])
        else:
            payload['optimal'] = bool(payload.get('optimal') or payload['lower'] == payload['upper'])
            self._bound_results[problem] = payload
            symbol = BOUND_SYMBOLS[problem]
            value = (str(payload['lower']) if payload['lower'] == payload['upper'] else
                     f'{payload["lower"]} ≤ {symbol} ≤ {payload["upper"]}')
            note = f' ({payload["note"]})' if payload.get('note') and not payload['optimal'] else ''
            self.bound_labels[problem].setText(f'{payload["name"]}: {value}{note}')
            self.bound_color_buttons[problem].setVisible(
                problem in SHOWABLE_BOUNDS and bool(payload['witness']))
            if payload['optimal']:
                solve_button.hide()
            if self._pending_show_problem == problem:
                self._pending_show_problem = None
                if payload['witness']:
                    QTimer.singleShot(0, lambda: self.show_bound_solution(problem))
        self.info_text.setPlainText(self.bound_heading.text() + '\n\n' + '\n'.join(
            self.bound_labels[key].text() for key in BOUND_PROBLEMS)
            + ('\n' + self.bound_note.text() if self.bound_note.text() else ''))
        self._info_has_result = True

    def show_bound_solution(self, problem):
        """Show a solution witness with vertex or edge styles in one undoable change."""
        if self._bound_revert_problem == problem and self._bound_revert_state is not None:
            self._revert_shown_result()
            return
        result = self._bound_results.get(problem)
        if self._info_outdated:
            return
        if result is None:
            self._pending_show_problem = problem
            self.solve_bound(problem)
            return
        if not result['witness']:
            return
        before_show = copy.deepcopy(_serialize_graph(self.graph))
        scope = (set(self._info_selection_nodes) if self._info_selection_nodes is not None
                 else set(self.graph))
        witness = result['witness']
        if problem == 'treewidth':
            from graph_builder_core.model.palette import colormap_1
            remove_regions(self.graph, {region['id'] for region in regions(self.graph)
                                        if region.get('tag') == 'treewidth'})
            for index, bag in enumerate(witness['bags']):
                bag_vertices = set(bag['vertices'])
                nodes = [node for node in self.graph if node in bag_vertices]
                if not nodes:
                    continue
                rgb = colormap_1(index + 1)
                pastel = tuple(round(0.5 * channel + 0.5 * 255) for channel in rgb)
                fill = '#%02x%02x%02x' % pastel
                add_region(self.graph, mode='bag', nodes=nodes,
                           label='', margin=25,
                           style={'fill': fill, 'opacity': .3,
                                  'outline': '#687581', 'width': 1.5},
                           tag='treewidth')
            self.rebuild_scene()
            self._commit_bound_show(problem, before_show)
            self.report('Tree-decomposition bags shown as regions.')
            return
        if problem in ('chromatic', 'domatic'):
            colors = {node: int(color) + 1 for node, color in witness}
            count = max(colors.values(), default=0) + 1
        elif problem in ('clique', 'independent', 'vertex_cover', 'domination'):
            chosen = set(witness)
            colors = {node: int(node in chosen) for node in scope}
            count = 2
        else:
            colors = None
        if colors is not None:
            self.graph.graph['num_vertex_styles'] = max(self.graph.graph['num_vertex_styles'], count)
            for node, color in colors.items():
                if node not in scope or node not in self.graph:
                    continue
                attributes = self.graph.nodes[node]
                attributes['style'] = color
                use_basic_style(attributes, color)
        else:
            directed = self.graph.graph.get('graph_type') != 'graph'
            def identity(source, target, key):
                return (source, target, key) if directed else (frozenset((source, target)), key)
            if problem == 'edge_chromatic':
                edge_colors = {identity(*edge): int(color) + 1 for edge, color in witness}
            else:
                selected = {identity(*edge) for edge in witness}
                edge_colors = {edge: 1 for edge in selected}
            self.graph.graph['num_edge_styles'] = max(
                self.graph.graph['num_edge_styles'], max(edge_colors.values(), default=0) + 1, 2)
            for source, target, key, _ in visible_edges(self.graph):
                if source not in scope or target not in scope:
                    continue
                color = edge_colors.get(identity(source, target, key), 0)
                use_basic_style(edge_data(self.graph, source, target, key), color)
                if not directed and source != target:
                    use_basic_style(edge_data(self.graph, target, source, key), color)
        self.rebuild_scene()
        self._commit_bound_show(problem, before_show)
        self.report('Showing the solution. Click Revert to restore the previous appearance.')

    def _commit_bound_show(self, problem, before_show):
        self._reset_bound_revert()
        self._preserve_bound_revert = True
        self._preserve_custom_result = isinstance(problem, str) and problem.startswith('custom:')
        try:
            self.commit_change()
        finally:
            self._preserve_bound_revert = False
            self._preserve_custom_result = False
        self._bound_revert_state = before_show
        self._bound_revert_problem = problem
        button = (self.custom_parameter_rows[int(problem.partition(':')[2])][2]
                  if isinstance(problem, str) and problem.startswith('custom:')
                  else self.bound_color_buttons[problem])
        button.setText('Revert')
        button.setToolTip('Restore the appearance before Show.')

    def compute_perfect_graph(self):
        process = self._info_process
        if process is not None and getattr(process, '_perfect_check', False):
            self._info_request_id += 1
            self._info_process = None
            process.kill()
            process.waitForFinished(100)
            self._release_info_process(process)
            process.deleteLater()
            self.perfect_compute_button.setText('Compute perfect graph')
            self.report('Perfect-graph check stopped.')
            return
        if self._info_outdated:
            self.refresh_graph_info()
            return
        graph = public_graph(self.graph)
        if self._info_selection_nodes is not None:
            graph = graph.subgraph(self._info_selection_nodes).copy()
        self._info_request_id += 1
        request_id = self._info_request_id
        process = prepare_worker(self, topology_payload(graph))
        process._bound_problem = None
        process._perfect_check = True
        self._info_process = process
        self.perfect_compute_button.setText('Stop')
        process.finished.connect(lambda code, status: self._finish_graph_info(
            request_id, process, 'Perfect', '', code))
        process.errorOccurred.connect(lambda error: self._graph_info_process_error(
            request_id, process, 'Perfect', '', error))
        start_worker(process, 'Perfect')
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS,
                          lambda: self._timeout_graph_info(request_id, process, 'Perfect', ''))

    def _display_perfect_result(self, result):
        self.perfect_compute_button.setText('Compute perfect graph')
        if 'error' in result:
            self.report(result['error'], 8)
            return
        status = result.get('status', 'Unknown (time limit)')
        content = self.info_text.toPlainText()
        content = re.sub(r'^Perfect: .*$', f'Perfect: {status}', content, flags=re.MULTILINE)
        self.info_text.setPlainText(content)
        self.perfect_compute_button.setVisible(
            status in ('Unknown (time limit)', 'Unknown (exact check limited to 16 vertices)'))

    def color_bound_solution(self, problem):
        """Compatibility alias for scripts that called the former UI action."""
        self.show_bound_solution(problem)

    def open_house_of_graphs(self):
        """Search this graph on House of Graphs in the default browser."""
        from graph_builder_core.io.house_of_graphs import search_url
        graph = public_graph(self.graph)
        try:
            url = search_url(graph)
        except ValueError as error:
            self.report(str(error), 7)
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            QApplication.clipboard().setText(url)
            self.report('Could not open the browser. Search link copied to the clipboard.', 7)

    @staticmethod
    def _release_info_process(process):
        release_worker(process)

    def _finish_graph_info(self, request_id, process, kind, scope, exit_code):
        if request_id == self._info_request_id and self._info_process is process:
            self._info_process = None
            if exit_code == 0:
                try:
                    lines = json.loads(process._result_path.read_text(encoding='utf-8'))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    lines = (['Analysis returned an unreadable result.'] if not process._bound_problem
                             else {'error': 'Analysis returned an unreadable result.'})
            else:
                detail = bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                message = f'Analysis failed: {detail or "worker stopped unexpectedly"}'
                lines = {'error': message} if process._bound_problem else [message]
            if getattr(process, '_perfect_check', False):
                self._display_perfect_result(lines if isinstance(lines, dict) else
                                             {'error': '\n'.join(lines)})
            elif process._bound_problem:
                self._display_bound_solution(process._bound_problem, lines)
            else:
                self._display_info(kind, scope, lines)
        self._release_info_process(process)
        process.deleteLater()

    def _graph_info_process_error(self, request_id, process, kind, scope, error):
        if (request_id == self._info_request_id and self._info_process is process
                and error == QProcess.FailedToStart):
            self._info_process = None
            if getattr(process, '_perfect_check', False):
                self._display_perfect_result({'error': 'Could not start the perfect-graph check.'})
            elif process._bound_problem:
                self._display_bound_solution(process._bound_problem,
                                             {'error': 'Could not start the analysis process.'})
            else:
                self._display_info(kind, scope, ['Could not start the analysis process.'])
            self._release_info_process(process)
            process.deleteLater()

    def _timeout_graph_info(self, request_id, process, kind, scope):
        if request_id != self._info_request_id or self._info_process is not process:
            return
        self._info_request_id += 1
        self._info_process = None
        process.kill()
        process.waitForFinished(100)
        self._release_info_process(process)
        process.deleteLater()
        if getattr(process, '_perfect_check', False):
            self._display_perfect_result({'status': 'Unknown (time limit)'})
            return
        if process._bound_problem:
            self._display_bound_solution(process._bound_problem,
                                         {'error': 'Not computed within one minute.'})
            return
        self._display_info(kind, scope,
                           [f'Not computed within {ANALYSIS_TIMEOUT_MS / 1000:g} seconds.'])
