"""In-window preview of the actual LaTeX-rendered picture."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .picture_export import PictureExportError, convert_picture_pdf

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:
    QPdfDocument = None


class PicturePreview(QWidget):
    """Show a rendered PDF and offer a save action."""

    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document = QPdfDocument(self) if QPdfDocument is not None else None
        self._pixmap = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.picture = QLabel(self)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumSize(220, 180)
        self.picture.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.picture.setStyleSheet('background: white; border: 1px solid #d5dcdf;')
        layout.addWidget(self.picture, 1)
        self.save_button = QPushButton('Save…', self)
        self.save_button.clicked.connect(self.save_requested)
        layout.addWidget(self.save_button)

    def show_pdf(self, path):
        """Load the PDF produced by the same render used for the final file."""
        if self._document is not None:
            self._document.close()
            error = self._document.load(str(Path(path)))
            if error != QPdfDocument.Error.None_ or self._document.pageCount() < 1:
                raise PictureExportError(f'Could not display the rendered PDF: {error}')
            page = self._document.pagePointSize(0)
            scale = min(2.0, 1600 / max(page.width(), page.height(), 1))
            size = QSize(max(1, round(page.width() * scale)),
                         max(1, round(page.height() * scale)))
            image = self._document.render(0, size)
            if image.isNull():
                raise PictureExportError('Could not display the rendered PDF page.')
            self._pixmap = QPixmap.fromImage(image)
        else:
            preview_png = Path(path).with_suffix('.png')
            try:
                convert_picture_pdf(path, preview_png, dpi=144)
            except PictureExportError:
                self._pixmap = QPixmap()
                self.picture.setText('Picture preview needs Poppler.\nYou can still save as PDF.')
                return
            self._pixmap = QPixmap(str(preview_png))
            if self._pixmap.isNull():
                raise PictureExportError('Could not display the rendered PNG preview.')
        self.picture.clear()
        self._fit_picture()

    def close_pdf(self):
        if self._document is not None:
            self._document.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_picture()

    def _fit_picture(self):
        if not self._pixmap.isNull():
            self.picture.setPixmap(self._pixmap.scaled(
                self.picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
