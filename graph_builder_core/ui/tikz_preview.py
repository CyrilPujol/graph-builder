"""Selectable, scrollable TikZ export preview inside the editor window."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class TikzPreview(QWidget):
    """Keep Save and Copy tied to the exact source displayed in the preview."""

    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.code = QPlainTextEdit(self)
        self.code.setReadOnly(True)
        self.code.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.code.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.code.setAccessibleName('TikZ source code')
        self.code.setToolTip('Select text to copy it, or use Copy to copy the whole code.')
        layout.addWidget(self.code, 1)
        buttons = QHBoxLayout()
        self.save_button = QPushButton('Save…', self)
        self.save_button.setToolTip('Save the displayed TikZ source to a .tex file')
        self.save_button.clicked.connect(self.save_requested)
        buttons.addWidget(self.save_button)
        self.copy_button = QPushButton('Copy', self)
        self.copy_button.setToolTip('Copy the whole TikZ source')
        self.copy_button.clicked.connect(self.copy_all)
        buttons.addWidget(self.copy_button)
        layout.addLayout(buttons)

    def set_code(self, source):
        self.code.setPlainText(source)

    def source(self):
        return self.code.toPlainText()

    def copy_all(self):
        QApplication.clipboard().setText(self.source())
