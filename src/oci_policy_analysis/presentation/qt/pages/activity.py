"""Load progress and retained errors, separate from the live component log."""

from PySide6.QtWidgets import QPlainTextEdit


class LoadActivityPage(QPlainTextEdit):
    """Display bounded stage history without coupling to a loading thread."""

    def __init__(self) -> None:
        """Build an empty, read-only activity view."""
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText('Load stages and errors appear here. No load has started.')
        self.document().setMaximumBlockCount(2000)
