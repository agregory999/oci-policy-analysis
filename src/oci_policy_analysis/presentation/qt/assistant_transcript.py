"""Bounded native Markdown transcript for the embedded assistant."""

from PySide6.QtGui import (
    QFontDatabase,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PySide6.QtWidgets import QTextBrowser


class AssistantTranscript(QTextBrowser):
    """Render streamed Markdown while retaining literal questions and role accents.

    External resources and automatic link navigation are disabled. The transcript
    stays in memory and retains at most one million characters of visible text.
    """

    _limit = 1000000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setUndoRedoEnabled(False)
        self.document().setDocumentMargin(12)
        self._answer_start = None
        self._answer_text = ''

    def loadResource(self, resource_type, name):
        """Keep Markdown images from loading local or remote resources."""
        return None

    def _end_cursor(self):
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.setCharFormat(QTextCharFormat())
        return cursor

    def append_literal(self, text):
        """Append session/status text without interpreting markup."""
        cursor = self._end_cursor()
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.insertText(text)
        self._trim()

    def begin_answer(self, question, assistant='Codex'):
        """Append a literal question and an italic label for the selected assistant.

        Args:
            question: User text, never interpreted as markup.
            assistant: Literal role label for this answer.
        """
        self.finish_answer()
        self.append_literal('You')
        cursor = self._end_cursor()
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.insertText(question)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        role = QTextCharFormat()
        role.setFontItalic(True)
        cursor.insertText(assistant, role)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        self._answer_start = QTextCursor(cursor)
        self._answer_start.setKeepPositionOnInsert(True)
        self._trim()

    def append_stream(self, text):
        """Re-render only the current answer as buffered Markdown chunks arrive."""
        if self._answer_start is None:
            self._answer_start = self._end_cursor()
            self._answer_start.setKeepPositionOnInsert(True)
        self._answer_text = (self._answer_text + text)[-self._limit :]
        scrollbar = self.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 4
        previous = scrollbar.value()
        cursor = QTextCursor(self._answer_start)
        cursor.clearSelection()
        cursor.setKeepPositionOnInsert(False)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        answer = QTextDocument()
        answer.setDefaultFont(self.font())
        answer.setMarkdown(
            self._answer_text,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        block = answer.begin()
        while block.isValid():
            fragment = block.begin()
            while not fragment.atEnd():
                span = fragment.fragment()
                if 'monospace' in (span.charFormat().fontFamilies() or []):
                    code = QTextCursor(answer)
                    code.setPosition(span.position())
                    code.setPosition(span.position() + span.length(), QTextCursor.MoveMode.KeepAnchor)
                    style = QTextCharFormat()
                    style.setFontFamilies(fixed_font.families())
                    style.setFontFixedPitch(True)
                    code.mergeCharFormat(style)
                fragment += 1
            block = block.next()
        cursor.insertFragment(QTextDocumentFragment(answer))
        cursor.endEditBlock()
        self._trim()
        scrollbar.setValue(scrollbar.maximum() if follow else previous)

    def finish_answer(self):
        """Seal the current answer, including interrupted or failed responses."""
        self._answer_start = None
        self._answer_text = ''

    def _trim(self):
        excess = self.document().characterCount() - self._limit
        if excess > 0:
            cursor = QTextCursor(self.document())
            cursor.setPosition(excess, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
