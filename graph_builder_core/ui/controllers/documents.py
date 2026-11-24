"""DocumentController methods hosted by GraphBuilderQt."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from graph_builder_core.algorithms.metrics import topology_payload
from graph_builder_core.extensions import public_graph
from graph_builder_core.io.graphml import convert_from_file, write_graph_file
from graph_builder_core.io.picture import convert_picture_pdf, render_picture_pdf
from graph_builder_core.io.tikz import write_tikz
from graph_builder_core.model.document import _deserialize_graph, _serialize_graph, empty_graph


def _default_file_folder():
    location = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    desktop = Path(location) if location else None
    return desktop if desktop is not None and desktop.is_dir() else Path.home()


class DocumentController:
    def commit_change(self):
        state = _serialize_graph(self.graph)
        if state != self._history[self._history_index]:
            if not self._preserve_bound_revert:
                self._reset_bound_revert()
            topology = topology_payload(public_graph(self.graph))
            if topology != self._info_topology or (
                    self._info_kind == 'Custom' and not self._preserve_custom_result):
                self._invalidate_info()
            self._info_topology = topology
            self._history = self._history[:self._history_index + 1]
            self._history.append(copy.deepcopy(state))
            if len(self._history) > 200:
                self._history.pop(0)
            self._history_index = len(self._history) - 1
        self._update_title()
        self.update_actions()

    def _update_title(self):
        dirty = _serialize_graph(self.graph) != self._saved_state
        title = self.path.name if self.path else 'Untitled graph'
        self.setWindowTitle(f'{title}{" •" if dirty else ""} — Graph Builder')

    def _restore(self, index):
        self._reset_bound_revert()
        if self.region_path is not None:
            self._cancel_region_path()
        self._clear_full_join()
        self._clear_morphism(cancel_process=True)
        self._clear_minor(cancel_process=True)
        self._clear_subgraph(cancel_process=True)
        self._clear_product()
        self._history_index = index
        self.graph = _deserialize_graph(copy.deepcopy(self._history[index]))
        topology = topology_payload(public_graph(self.graph))
        if topology != self._info_topology or self._info_kind == 'Custom':
            self._invalidate_info()
        self._info_topology = topology
        self.selection.clear()
        self.rebuild_scene()
        self._update_title()
        self.update_actions()

    def undo(self):
        if self._history_index > 0:
            self._restore(self._history_index - 1)

    def redo(self):
        if self._history_index < len(self._history) - 1:
            self._restore(self._history_index + 1)

    def _reset_history(self):
        self._reset_bound_revert()
        if self.region_path is not None:
            self._cancel_region_path()
        self._clear_full_join()
        self._clear_morphism(cancel_process=True)
        self._clear_minor(cancel_process=True)
        self._clear_subgraph(cancel_process=True)
        self._clear_product()
        self._invalidate_info()
        self._info_topology = topology_payload(public_graph(self.graph))
        state = copy.deepcopy(_serialize_graph(self.graph))
        self._history = [state]
        self._history_index = 0
        self._saved_state = copy.deepcopy(state)
        self._update_title()
        self.update_actions()

    def _may_replace_document(self):
        if _serialize_graph(self.graph) == self._saved_state:
            return True
        answer = QMessageBox.question(self, 'Unsaved changes', 'Save changes to this graph?',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                      QMessageBox.Save)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_file()
        return True

    def new_file(self):
        if not self._may_replace_document():
            return
        self.finish_tutorial()
        self.graph = empty_graph()
        self.path = None
        self.selection.clear()
        self.rebuild_scene()
        self._reset_history()

    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Open graph', str(self.path.parent if self.path else _default_file_folder()),
                                                   'Graphs (*.graphml *.g6 *.graph6 *.s6 *.sparse6 *.d6 *.digraph6);;GraphML files (*.graphml);;Graph6 family (*.g6 *.graph6 *.s6 *.sparse6 *.d6 *.digraph6);;All files (*)')
        if filename:
            self.open_path(filename)

    def open_path(self, filename):
        """Open a file chosen in the editor or delivered by the desktop OS."""
        path = Path(filename).resolve()
        if not path.is_file():
            QMessageBox.critical(self, 'Could not open graph', f'File not found: {path}')
            return False
        try:
            from graph_builder_core.io.compact_graphs import COMPACT_SUFFIXES, editor_graph, read_compact_graphs
            if path.suffix.lower() in COMPACT_SUFFIXES:
                graphs = read_compact_graphs(path)
                index = 1
                if len(graphs) > 1:
                    index, accepted = QInputDialog.getInt(
                        self, 'Choose graph', f'This file contains {len(graphs)} graphs. Open graph:',
                        1, 1, len(graphs))
                    if not accepted:
                        return False
                graph = editor_graph(graphs[index - 1], {})
            else:
                graph = convert_from_file(path)
        except Exception as error:
            QMessageBox.critical(self, 'Could not open graph', str(error))
            return False
        if not self._may_replace_document():
            return False
        self.finish_tutorial()
        self.graph = graph
        self.path = path if path.suffix.lower() == '.graphml' else None
        self.selection.clear()
        self.rebuild_scene()
        self._reset_history()
        self.fit_graph()
        return True

    def save_file(self):
        if self.path is None:
            return self.save_as()
        try:
            write_graph_file(self.graph, self.path)
        except Exception as error:
            QMessageBox.critical(self, 'Could not save graph', str(error))
            return False
        self._saved_state = copy.deepcopy(_serialize_graph(self.graph))
        self._update_title()
        self.report(f'Saved {self.path.name}', 3)
        return True

    def save_as(self):
        proposed = str(self.path if self.path else _default_file_folder() / 'graph.graphml')
        filename, _ = QFileDialog.getSaveFileName(self, 'Save graph', proposed,
                                                   'GraphML files (*.graphml);;All files (*)')
        if not filename:
            return False
        old_path = self.path
        self.path = Path(filename)
        if not self.path.suffix:
            self.path = self.path.with_suffix('.graphml')
        if self.save_file():
            return True
        self.path = old_path
        return False

    def export_tikz(self):
        proposed = str((self.path or _default_file_folder() / 'graph.graphml').with_suffix('.tex'))
        filename, _ = QFileDialog.getSaveFileName(self, 'Export to TikZ', proposed,
                                                   'TikZ files (*.tex);;All files (*)')
        if filename:
            path = Path(filename)
            if not path.suffix:
                path = path.with_suffix('.tex')
            try:
                write_tikz(self.graph, path)
            except Exception as error:
                QMessageBox.critical(self, 'Could not export TikZ', str(error))
                return
            self.report(f'Exported {path.name}', 3)

    def export_picture(self):
        temporary = tempfile.TemporaryDirectory(prefix='graph-builder-preview-')
        try:
            pdf = render_picture_pdf(self.graph, Path(temporary.name) / 'picture.pdf')
            self.picture_preview.show_pdf(pdf)
        except Exception as error:
            temporary.cleanup()
            QMessageBox.critical(self, 'Could not export picture', str(error))
            return
        previous = self._picture_temp
        self._picture_temp = temporary
        if previous is not None:
            previous.cleanup()
        self.info_dock.hide()
        self.help_dock.hide()
        self.tutorial_dock.hide()
        self.picture_dock.show()
        self.picture_dock.raise_()
        self.report('Picture ready to preview and save', 3)

    def _save_picture_preview(self):
        if self._picture_temp is None:
            return
        proposed = str((self.path or _default_file_folder() / 'graph.graphml').with_suffix('.png'))
        filters = ('PNG image (*.png);;SVG vector image (*.svg);;PDF document (*.pdf);;PDF (Ipe compatible) (*.pdf)')
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, 'Save picture', proposed, filters)
        if not filename:
            return
        path = Path(filename)
        suffix_by_filter = {'PNG image (*.png)': '.png',
                            'SVG vector image (*.svg)': '.svg',
                            'PDF document (*.pdf)': '.pdf',
                            'PDF (Ipe compatible) (*.pdf)': '.pdf'}
        selected_suffix = suffix_by_filter.get(selected_filter, '.png')
        if path.suffix.lower() != selected_suffix:
            path = path.with_suffix(selected_suffix)
        try:
            convert_picture_pdf(Path(self._picture_temp.name) / 'picture.pdf', path,
                                ipe_compatible='Ipe compatible' in selected_filter)
        except Exception as error:
            QMessageBox.critical(self, 'Could not save picture', str(error))
            return
        self.report(f'Exported {path.name}', 3)

    def closeEvent(self, event):
        if self.return_graph_on_close and self.path is None:
            event.accept()
        elif self.path is not None and _serialize_graph(self.graph) != self._saved_state:
            if self.save_file():
                event.accept()
            else:
                event.ignore()
        elif self._may_replace_document():
            event.accept()
        else:
            event.ignore()
        if event.isAccepted() and self._picture_temp is not None:
            self.picture_preview.close_pdf()
            self._picture_temp.cleanup()
            self._picture_temp = None
        if event.isAccepted() and self._info_process is not None:
            self._info_request_id += 1
            process = self._info_process
            process.kill()
            process.waitForFinished(100)
            self._release_info_process(process)
            self._info_process = None
        if event.isAccepted() and self._morphism_process is not None:
            self._clear_morphism(cancel_process=True)
        if event.isAccepted() and self._minor_process is not None:
            self._clear_minor(cancel_process=True)
        if event.isAccepted() and self._subgraph_process is not None:
            self._clear_subgraph(cancel_process=True)
