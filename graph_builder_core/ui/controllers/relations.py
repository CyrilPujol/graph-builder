"""RelationsController methods hosted by GraphBuilderQt."""
from __future__ import annotations

import json

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QToolButton

from graph_builder_core.algorithms.metrics import OPTIMIZATION_TIMEOUT_MS, topology_payload
from graph_builder_core.algorithms.products import PRODUCTS, generate_product
from graph_builder_core.extensions import public_graph
from graph_builder_core.model.operations import full_join
from graph_builder_core.ui.workers import prepare_worker, start_worker, release_worker


class RelationsController:
    def _clear_full_join(self):
        previous = self._full_join_first
        self._full_join_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.full_join_action.setChecked(False)
        self._set_action_tooltip(self.full_join_action)
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _clear_product(self):
        previous = self._product_first
        self._product_first = frozenset()
        self._product_kind = None
        self.product_button.setChecked(False)
        self.product_button.setText('Product')
        self.product_button.setPopupMode(QToolButton.InstantPopup)
        self.product_button.setToolTip('Choose a product of two selected vertex sets.')
        if previous:
            self.statusBar().clearMessage()
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _product_button_clicked(self):
        if self._product_first:
            self.product_button.setChecked(True)
            self.product_selection()
        else:
            self.product_button.setChecked(False)
            self.product_button.showMenu()

    def start_product(self, kind):
        self._cancel_staged_extension()
        if self._product_first and self._product_kind == kind:
            self.product_selection()
            return
        if self._product_first:
            self._product_kind = kind
            self.product_button.setText(f'{PRODUCTS[kind][0]} ✓')
            self.product_button.setPopupMode(QToolButton.DelayedPopup)
            self.product_button.setToolTip(
                f'Select the second factor, then click here or press Enter to make the {kind} product.')
            self.report(f'Switched to {PRODUCTS[kind][0]} product. Select the second factor.', 5)
            return
        selected = set(self.selection.nodes)
        if not selected:
            self.report('Select the vertices of the first factor.', 4)
            return
        if self._full_join_first:
            self._clear_full_join()
        if self._morphism_first or self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
        if self._minor_first or self._minor_process is not None:
            self._clear_minor(cancel_process=True)
        if self._subgraph_first or self._subgraph_process is not None:
            self._clear_subgraph(cancel_process=True)
        self._product_first = frozenset(selected)
        self._product_kind = kind
        self.product_button.setChecked(True)
        self.product_button.setText(f'{PRODUCTS[kind][0]} ✓')
        self.product_button.setPopupMode(QToolButton.DelayedPopup)
        self.product_button.setToolTip(
            f'Select the second factor, then click here or press Enter to make the {kind} product.')
        message = 'First factor marked. Select the second factor, then click the highlighted button or press Enter.'
        self._request_next_selection('Product', message=message)

    def product_selection(self, checked=False):
        if not self._product_first:
            self._product_button_clicked()
            return
        second = set(self.selection.nodes)
        if not second:
            self.report('Select at least one vertex for the second factor. Esc cancels.', 5)
            return
        try:
            generated = generate_product(self.graph, self._product_first, second,
                                         self._product_kind)
        except ValueError as error:
            self.report(str(error), 5)
            return
        kind = self._product_kind
        self._clear_product()
        new_nodes = self._insert_generated_graph(generated, arrange_parallel=True)
        self.report(f'Added the {kind} product with {len(new_nodes)} vertices.', 5)

    def full_join_selection(self, checked=False):
        """Capture one vertex set, then join it to the next selected set."""
        self._cancel_staged_extension()
        second = set(self.selection.nodes)
        if not self._full_join_first:
            if self._product_first:
                self._clear_product()
            if self._morphism_first or self._morphism_process is not None:
                self._clear_morphism(cancel_process=True)
            if self._minor_first or self._minor_process is not None:
                self._clear_minor(cancel_process=True)
            if self._subgraph_first or self._subgraph_process is not None:
                self._clear_subgraph(cancel_process=True)
            if not second:
                self.full_join_action.setChecked(False)
                self.report('Select at least one vertex for the first set.', 4)
                return
            self._full_join_first = frozenset(second)
            self.full_join_action.setChecked(True)
            self.full_join_action.setToolTip(
                'Full join — J\nSelect the second vertex set, then click again. Esc cancels.')
            self._request_next_selection('Full join')
            return
        if not second:
            self.full_join_action.setChecked(True)
            self.report('Select at least one vertex for the second set. Esc cancels.', 5)
            return
        first = self._full_join_first
        self._clear_full_join()
        added = full_join(self.graph, first, second, self.edge_color)
        self.rebuild_scene()
        self.commit_change()
        self.report(f'Full join added {added} edge{"" if added == 1 else "s"}.', 5)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def _clear_morphism(self, cancel_process=False):
        if cancel_process and self._morphism_process is not None:
            process = self._morphism_process
            self._morphism_process = None
            process.kill()
            process.waitForFinished(100)
            release_worker(process)
            process.deleteLater()
        previous = self._morphism_first
        self._morphism_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.morphism_action.setChecked(False)
        self._set_action_tooltip(self.morphism_action)
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _clear_minor(self, cancel_process=False):
        if cancel_process and self._minor_process is not None:
            process = self._minor_process
            self._minor_process = None
            process.kill()
            process.waitForFinished(100)
            release_worker(process)
            process.deleteLater()
        previous = self._minor_first
        self._minor_first = frozenset()
        if previous:
            self.statusBar().clearMessage()
        self.minor_action.setChecked(False)
        self._set_action_tooltip(self.minor_action)
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def _clear_subgraph(self, cancel_process=False):
        if cancel_process and self._subgraph_process is not None:
            process = self._subgraph_process
            self._subgraph_process = None
            process.kill()
            process.waitForFinished(100)
            release_worker(process)
            process.deleteLater()
        previous = self._subgraph_first
        self._subgraph_first = frozenset()
        self._subgraph_kind = None
        if previous:
            self.statusBar().clearMessage()
        self.subgraph_action.setChecked(False)
        self.induced_subgraph_action.setChecked(False)
        for node in previous:
            item = self.node_items.get(node)
            if item is not None and item.scene() is self.scene:
                item.update()

    def subgraph_selection(self, kind):
        """Capture host and pattern, then find an injective subgraph witness."""
        self._cancel_staged_extension()
        action = self.induced_subgraph_action if kind == 'Induced subgraph' else self.subgraph_action
        if self._subgraph_process is not None:
            self._clear_subgraph(cancel_process=True)
            self.report(f'{kind} search stopped.', 4)
            self.update_actions()
            return
        selected = set(self.selection.nodes)
        if not self._subgraph_first:
            if not selected:
                action.setChecked(False)
                self.report('Select the host graph first.', 4)
                return
            if self._product_first:
                self._clear_product()
            if self._full_join_first:
                self._clear_full_join()
            if self._morphism_first or self._morphism_process is not None:
                self._clear_morphism(cancel_process=True)
            if self._minor_first or self._minor_process is not None:
                self._clear_minor(cancel_process=True)
            self._subgraph_first = frozenset(selected)
            self._subgraph_kind = kind
            action.setChecked(True)
            message = f'Host marked. Select a pattern, then click {kind} again or press Enter.'
            self._request_next_selection(kind, message=message)
            return
        if kind != self._subgraph_kind:
            self._subgraph_kind = kind
            self.subgraph_action.setChecked(kind == 'Subgraph')
            self.induced_subgraph_action.setChecked(kind == 'Induced subgraph')
            self.report(f'Switched to {kind}. Select the pattern, then press Enter.', 5)
            return
        if not selected:
            action.setChecked(True)
            self.report('Select at least one pattern vertex. Esc cancels.', 5)
            return
        sources, targets = set(self._subgraph_first), selected
        topology = topology_payload(public_graph(self.graph))
        payload = topology | {'source_nodes': sorted(sources, key=str),
                              'target_nodes': sorted(targets, key=str)}
        process = prepare_worker(self, payload)
        self._subgraph_process = process
        process.finished.connect(lambda code, status: self._finish_subgraph(
            process, code, sources, targets, topology, kind))
        process.errorOccurred.connect(lambda error: self._subgraph_worker_error(process, error))
        start_worker(process, kind)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS, lambda: self._timeout_subgraph(process))
        self.report(f'Computing {kind.lower()}. Click again or press Esc to stop.', 6)
        self.update_actions()

    def _subgraph_worker_error(self, process, error):
        if process is self._subgraph_process and error == QProcess.FailedToStart:
            self._clear_subgraph(cancel_process=True)
            self.report('Could not start the subgraph search.', 6)
            self.update_actions()

    def _timeout_subgraph(self, process):
        if process is self._subgraph_process:
            self._clear_subgraph(cancel_process=True)
            self.report('Subgraph search stopped after one minute.', 6)
            self.update_actions()

    def _finish_subgraph(self, process, exit_code, sources, targets, topology, kind):
        if process is not self._subgraph_process:
            return
        self._subgraph_process = None
        try:
            result = json.loads(process._result_path.read_text(encoding='utf-8')) if exit_code == 0 else {
                'error': bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                         or 'The search stopped unexpectedly.'}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = {'error': 'The subgraph search returned an unreadable result.'}
        release_worker(process)
        process.deleteLater()
        self._clear_subgraph()
        self.update_actions()
        if topology_payload(public_graph(self.graph)) != topology:
            self.report('The graph changed during the search. Please try again.', 7)
            return
        if 'error' in result:
            self.report(result['error'], 8)
            return
        if result['status'] == 'none':
            self.report(f'The first graph does not contain the second as a {kind.lower()}.', 6)
            return
        from graph_builder_core.algorithms.subgraph import lift_subgraph_styles
        auto_colored = lift_subgraph_styles(self.graph, sources, targets, result['mapping'],
                                            induced=kind == 'Induced subgraph')
        self.rebuild_scene()
        self.commit_change()
        self.report(f'{kind} found. ' + ('One style highlights the copy.' if auto_colored else
                                       'Styles from the pattern show the copy.'), 6)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def morphism_selection(self, checked=False):
        """Capture induced G and H, then solve without blocking the canvas."""
        self._cancel_staged_extension()
        if self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
            self.report('Morphism search stopped.', 4)
            self.update_actions()
            return
        selected = set(self.selection.nodes)
        if not self._morphism_first:
            if self._product_first:
                self._clear_product()
            if self._full_join_first:
                self._clear_full_join()
            if self._minor_first or self._minor_process is not None:
                self._clear_minor(cancel_process=True)
            if self._subgraph_first or self._subgraph_process is not None:
                self._clear_subgraph(cancel_process=True)
            if not selected:
                self.morphism_action.setChecked(False)
                self.report('Select at least one vertex for G.', 4)
                return
            self._morphism_first = frozenset(selected)
            self.morphism_action.setChecked(True)
            self.morphism_action.setToolTip(
                'Select the vertices of H, then click Morphism again. Esc cancels.')
            message = 'G marked. Select vertices for H, then click Morphism again. Esc cancels.'
            self._request_next_selection('Morphism', message=message)
            return
        if not selected:
            self.morphism_action.setChecked(True)
            self.report('Select at least one vertex for H. Esc cancels.', 5)
            return
        self.morphism_action.setChecked(True)
        self.morphism_action.setToolTip('Computing a morphism. Click again or press Esc to stop.')
        self._start_morphism_search(set(self._morphism_first), selected)

    def _start_morphism_search(self, sources, targets):
        graph = public_graph(self.graph)
        topology = topology_payload(graph)
        payload = topology | {'source_nodes': sorted(sources, key=str),
                              'target_nodes': sorted(targets, key=str)}
        process = prepare_worker(self, payload)
        self._morphism_process = process
        process.finished.connect(lambda code, status: self._finish_morphism(
            process, code, sources, targets, topology))
        process.errorOccurred.connect(lambda error: self._morphism_worker_error(process, error))
        kind = 'Morphism'
        start_worker(process, kind)
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS, lambda: self._timeout_morphism(process))
        self.report('Computing a morphism. Click Morphism again to stop.', 6)
        self.update_actions()

    def minor_selection(self, checked=False):
        """Capture host G and pattern H, then test their undirected minor relation."""
        self._cancel_staged_extension()
        if self._minor_process is not None:
            self._clear_minor(cancel_process=True)
            self.report('Minor search stopped.', 4)
            self.update_actions()
            return
        selected = set(self.selection.nodes)
        if not self._minor_first:
            if self._product_first:
                self._clear_product()
            if self._full_join_first:
                self._clear_full_join()
            if self._morphism_first or self._morphism_process is not None:
                self._clear_morphism(cancel_process=True)
            if self._subgraph_first or self._subgraph_process is not None:
                self._clear_subgraph(cancel_process=True)
            if not selected:
                self.minor_action.setChecked(False)
                self.report('Select the host graph first.', 4)
                return
            self._minor_first = frozenset(selected)
            self.minor_action.setChecked(True)
            message = 'Host marked. Select a pattern graph, then click Minor again. Esc cancels.'
            self._request_next_selection('Minor', message=message)
            return
        if not selected:
            self.minor_action.setChecked(True)
            self.report('Select at least one vertex for the pattern.', 5)
            return
        self.minor_action.setChecked(True)
        sources, targets = set(self._minor_first), selected
        topology = topology_payload(public_graph(self.graph))
        payload = topology | {'source_nodes': sorted(sources, key=str),
                              'target_nodes': sorted(targets, key=str)}
        process = prepare_worker(self, payload)
        self._minor_process = process
        process.finished.connect(lambda code, status: self._finish_minor(
            process, code, sources, targets, topology))
        process.errorOccurred.connect(lambda error: self._minor_worker_error(process, error))
        start_worker(process, 'Minor')
        QTimer.singleShot(OPTIMIZATION_TIMEOUT_MS, lambda: self._timeout_minor(process))
        self.report('Computing a minor. Click Minor again or press Esc to stop.', 6)
        self.update_actions()

    def _minor_worker_error(self, process, error):
        if process is self._minor_process and error == QProcess.FailedToStart:
            self._clear_minor(cancel_process=True)
            self.report('Could not start the minor solver.', 6)
            self.update_actions()

    def _timeout_minor(self, process):
        if process is self._minor_process:
            self._clear_minor(cancel_process=True)
            self.report('Minor search stopped after one minute.', 6)
            self.update_actions()

    def _finish_minor(self, process, exit_code, sources, targets, topology):
        if process is not self._minor_process:
            return
        self._minor_process = None
        try:
            result = json.loads(process._result_path.read_text(encoding='utf-8')) if exit_code == 0 else {
                'error': bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                         or 'The solver stopped unexpectedly.'}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = {'error': 'The minor solver returned an unreadable result.'}
        release_worker(process)
        process.deleteLater()
        self._clear_minor()
        self.update_actions()
        if topology_payload(public_graph(self.graph)) != topology:
            self.report('The graph changed during the search. Please try Minor again.', 7)
            return
        if 'error' in result:
            self.report(result['error'], 8)
            return
        if result['status'] == 'none':
            self.report('The first graph does not contain the second as a minor.', 6)
            return
        if result['status'] == 'timeout':
            self.report('No answer within one minute. This does not disprove the minor.', 8)
            return
        from graph_builder_core.algorithms.minor import lift_minor_styles
        auto_colored = lift_minor_styles(self.graph, sources, targets, result['branch_sets'])
        self.rebuild_scene()
        self.commit_change()
        message = ('Minor found. Distinct styles show its branch sets.' if auto_colored else
                   'Minor found. Styles from the pattern show its branch sets.')
        self.report(message, 6)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)

    def _morphism_worker_error(self, process, error):
        if process is self._morphism_process and error == QProcess.FailedToStart:
            self._clear_morphism(cancel_process=True)
            self.report('Could not start the morphism solver.', 6)
            self.update_actions()

    def _timeout_morphism(self, process):
        if process is self._morphism_process:
            self._clear_morphism(cancel_process=True)
            self.report('Morphism search stopped after one minute.', 6)
            self.update_actions()

    def _finish_morphism(self, process, exit_code, sources, targets, topology):
        if process is not self._morphism_process:
            return
        self._morphism_process = None
        try:
            result = json.loads(process._result_path.read_text(encoding='utf-8')) if exit_code == 0 else {
                'error': bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
                         or 'The solver stopped unexpectedly.'}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = {'error': 'The morphism solver returned an unreadable result.'}
        release_worker(process)
        process.deleteLater()
        self._clear_morphism()
        self.update_actions()
        if topology_payload(public_graph(self.graph)) != topology:
            self.report('The graph changed during the search. Please try Morphism again.', 7)
            return
        if 'error' in result:
            self.report(result['error'], 8)
            return
        if result['status'] == 'none':
            self.report('No morphism from G to H exists.', 6)
            return
        if result['status'] == 'timeout':
            self.report('No answer within one minute. This does not prove that no morphism exists.', 8)
            return
        from graph_builder_core.algorithms.morphism import lift_morphism_styles
        auto_colored = lift_morphism_styles(self.graph, sources, targets, result['mapping'])
        self.rebuild_scene()
        self.commit_change()
        message = ('Morphism shown. H received distinct vertex styles.' if auto_colored else
                   'Morphism shown with styles lifted from H.')
        self.report(message, 6)
        self.view.viewport().repaint()
        QTimer.singleShot(0, self.view.viewport().update)
