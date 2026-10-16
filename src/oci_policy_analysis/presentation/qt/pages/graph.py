"""Native Qt graph of shared-core source grants, with evidence and exclusions."""

import json
from dataclasses import asdict
from html import escape

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.policy_graph_service import PolicyGraphService
from oci_policy_analysis.application.services.prospective_workbench_service import ProspectiveWorkbenchService
from oci_policy_analysis.presentation.qt.tables import StatementTable
from oci_policy_analysis.presentation.qt.themes import theme_color
from oci_policy_analysis.presentation.qt.widgets import label

logger = get_logger(component='qt.pages.graph')


class PolicyGraphPage(QWidget):
    """Draw principal → source grant → path relationships using native Qt items.

    Attributes:
        statements: Related source records with complete selected permission facts.
        details_requested: Explicit statement inspection request for the shared drawer.
        focus_dynamic_group: Request to focus a selected statement's dynamic group.

    Notes:
        Uses PolicyGraphService over the current corpus. Shows at most twelve
        grants per page, with explicit pagination. Edges represent direct source
        contributions, not inheritance, evaluated conditions, or OCI decisions.
    """

    details_requested = Signal(object)
    focus_dynamic_group = Signal(dict)

    def __init__(self) -> None:
        """Create independent search controls, canvas, and evidence inspectors."""
        super().__init__()
        self.theme = 'Light'
        self.color_theme = 'Forest'
        self.context = None
        self.include_prospective = False
        self.page = 1
        self.result = {'total': 0, 'grants': []}
        self.visible_grants = []
        self._corpus = None
        self._graph_query = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        fields = QGridLayout()
        self.filters = {}
        for index, (key, title) in enumerate(
            [
                ('principal', 'Principal / group'),
                ('path', 'Effective / grant path'),
                ('resource', 'Resource or expanded permission'),
                ('query', 'Policy, statement, or ID'),
            ]
        ):
            field = QLineEdit()
            field.setPlaceholderText(title)
            field.returnPressed.connect(self.search)
            self.filters[key] = field
            fields.addWidget(field, index // 2, index % 2)
        layout.addLayout(fields)
        controls = QHBoxLayout()
        self.effect = QComboBox()
        self.effect.addItems(['All effects', 'allow', 'deny'])
        controls.addWidget(self.effect)
        search = QPushButton('Search graph')
        search.clicked.connect(self.search)
        controls.addWidget(search)
        reset = QPushButton('Reset')
        reset.clicked.connect(self.reset_filters)
        controls.addWidget(reset)
        controls.addStretch()
        for title, callback in [
            ('−', lambda: self.view.scale(0.8, 0.8)),
            ('+', lambda: self.view.scale(1.25, 1.25)),
            ('Fit', self.fit_graph),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.summary = label('No snapshot loaded.', 'muted', wrap=True)
        layout.addWidget(self.summary)
        layout.addWidget(
            label(
                'PRINCIPAL  →  SOURCE GRANT  →  EFFECTIVE PATH · Select a node for related statements; drag to pan.',
                'eyebrow',
                wrap=True,
            )
        )
        split = QSplitter(Qt.Orientation.Vertical)
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._selection_changed)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setBackgroundBrush(QColor('#f5f6f2'))
        self.view.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        split.addWidget(self.view)
        tabs = QTabWidget()
        related = QWidget()
        related_layout = QVBoxLayout(related)
        related_layout.setContentsMargins(0, 8, 0, 0)
        self.selection_summary = label('Select a graph node to see related statements.', 'muted', wrap=True)
        related_layout.addWidget(self.selection_summary)
        self.statements = StatementTable()
        self.statements.details_requested.connect(self.details_requested.emit)
        self.statements.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
        related_layout.addWidget(self.statements)
        tabs.addTab(related, 'Related statements')
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('Select a source-grant node to inspect conditions, permissions, and provenance.')
        tabs.addTab(self.detail, 'Selected evidence')
        self.exclusions = QPlainTextEdit()
        self.exclusions.setReadOnly(True)
        tabs.addTab(self.exclusions, 'Excluded source evidence')
        split.addWidget(tabs)
        split.setSizes([380, 260])
        layout.addWidget(split, 1)
        pager = QHBoxLayout()
        self.previous = QPushButton('← Previous')
        self.previous.clicked.connect(lambda: self._turn_page(-1))
        self.next = QPushButton('Next →')
        self.next.clicked.connect(lambda: self._turn_page(1))
        pager.addWidget(self.previous)
        self.page_label = label('No snapshot', 'muted')
        pager.addWidget(self.page_label)
        pager.addStretch()
        pager.addWidget(self.next)
        layout.addLayout(pager)
        layout.addWidget(
            label(
                'Direct grants · Conditions retained · Excluded statements available in the source browser.',
                'notice',
                wrap=True,
            )
        )
        self.previous.setEnabled(False)
        self.next.setEnabled(False)

    def set_theme(self, theme: str, color_theme: str = 'Forest') -> None:
        """Recolor the canvas and graph nodes without querying or reloading data."""
        self.theme = theme
        self.color_theme = color_theme
        self.view.setBackgroundBrush(QColor(theme_color('#f5f6f2', theme, color_theme)))
        self._draw()

    def set_context(self, context) -> None:
        """Bind the current corpus, including retained excluded source evidence."""
        self.context = context
        self.search()

    def search(self) -> None:
        """Search a fresh service bound to the current snapshot and reset pagination."""
        self.page = 1
        self._refresh()

    def reset_filters(self) -> None:
        """Clear graph search independently of policy-browser filters."""
        for field in self.filters.values():
            field.clear()
        self.effect.setCurrentIndex(0)
        self.search()

    def _turn_page(self, delta: int) -> None:
        self.page = max(1, self.page + delta)
        self._refresh()

    def _refresh(self) -> None:
        try:
            corpus = self.context.corpus if self.context else None
            if self.context and self.include_prospective:
                corpus = self.context.simulation.get_corpus(include_prospective=True)
            self._corpus = corpus
            self.statements.model.replace([])
            self.selection_summary.setText('Select a graph node to see related statements.')
            exclusions = corpus.exclusions if corpus else ()
            self.exclusions.setPlainText(
                f'{len(exclusions):,} exclusions in the displayed corpus. Showing the first 200.\n\n'
                + json.dumps([asdict(item) for item in exclusions[:200]], indent=2, ensure_ascii=False)
            )
            self._graph_query = {key: field.text().strip() for key, field in self.filters.items()}
            self._graph_query['effect'] = self.effect.currentText() if self.effect.currentIndex() else ''
            self.result = PolicyGraphService(corpus).get_page(**self._graph_query, page=self.page)
            self.visible_grants = self.result['grants']
            self.detail.clear()
            self._draw()
            total = self.result['total']
            self.previous.setEnabled(self.page > 1)
            self.next.setEnabled(self.page * 12 < total)
            self.page_label.setText(
                f'Page {self.page} of {max(1, (total + 11) // 12)} · {len(self.visible_grants)} visible grants'
            )
            summary = self.result['summary']
            self.summary.setText(
                f'{total:,} matching grants · {summary["direct_facts"]:,} direct permission facts · {summary["exclusions"]:,} source exclusions. Direct contributions from this snapshot.'
                + (' Prospective what-if grants included.' if self.include_prospective else '')
            )
            logger.info(
                'Graph rendered: page=%d grants=%d matches=%d exclusions=%d',
                self.page,
                len(self.visible_grants),
                total,
                summary['exclusions'],
            )
        except Exception:
            logger.exception('Could not project policy graph')
            self.scene.clear()
            self.visible_grants = []
            self.summary.setText('Graph could not be built. See Qt logging for details.')
            self.previous.setEnabled(False)
            self.next.setEnabled(False)

    def _node(self, x: float, y: float, title: str, subtitle: str, color: str, evidence: dict):
        path = QPainterPath()
        path.addRoundedRect(x, y, 265, 84, 9, 9)
        node = self.scene.addPath(
            path,
            QPen(QColor(theme_color('#a9bfb5', self.theme, self.color_theme))),
            QBrush(QColor(theme_color(color, self.theme, self.color_theme))),
        )
        node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        node.setData(0, evidence)
        node.setToolTip(escape(title + '\n' + subtitle))
        for offset, text in [(15, title), (45, subtitle)]:
            item = self.scene.addSimpleText(text[:33] + ('…' if len(text) > 33 else ''))
            item.setBrush(QColor(theme_color('#243d39', self.theme, self.color_theme)))
            item.setPos(x + 12, y + offset)
            item.setParentItem(node)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return node

    def _edge(self, x1: float, y1: float, x2: float, y2: float) -> None:
        path = QPainterPath(QPointF(x1, y1))
        path.cubicTo(x1 + 48, y1, x2 - 48, y2, x2, y2)
        edge = self.scene.addPath(path, QPen(QColor(theme_color('#6c9584', self.theme, self.color_theme)), 2))
        edge.setZValue(-1)
        self.scene.addPolygon(
            QPolygonF([QPointF(x2, y2), QPointF(x2 - 9, y2 - 5), QPointF(x2 - 9, y2 + 5)]),
            QPen(Qt.PenStyle.NoPen),
            QBrush(QColor(theme_color('#6c9584', self.theme, self.color_theme))),
        )

    def _draw(self) -> None:
        self.scene.clear()
        if not self.visible_grants:
            text = self.scene.addSimpleText('No matching grants. Check filters or excluded evidence.')
            text.setBrush(QColor(theme_color('#243d39', self.theme, self.color_theme)))
            self.fit_graph()
            return
        principals = {}
        paths = {}
        for index, grant in enumerate(self.visible_grants):
            principals.setdefault(grant['principal'], []).append(index)
            paths.setdefault(grant['path'], []).append(index)
        # Keep shared endpoint nodes at distinct rows to avoid overlapping labels.
        principal_y = {key: index * 125 for index, key in enumerate(principals)}
        path_y = {key: index * 125 for index, key in enumerate(paths)}
        for key, indexes in principals.items():
            self._node(
                0,
                principal_y[key],
                key,
                f'{len(indexes)} visible source grants',
                '#d8ebe1',
                {'principal': key, 'grants': [self.visible_grants[i] for i in indexes]},
            )
        for key, indexes in paths.items():
            self._node(
                720,
                path_y[key],
                key,
                f'{len(indexes)} visible source grants',
                '#e7ecdf',
                {'path': key, 'grants': [self.visible_grants[i] for i in indexes]},
            )
        for index, grant in enumerate(self.visible_grants):
            y = index * 125
            color = '#f0dfd8' if grant['effect'] == 'deny' else '#f4edda'
            suffix = ' · conditional' if grant['condition_clause'] else ''
            self._node(
                360,
                y,
                ('[Prospective] ' if grant.get('prospective') else '')
                + ('Conditional · ' if grant['condition_clause'] else '')
                + (grant['policy_name'] or grant['statement_id']),
                f'{grant["effect"]} {grant["resource"]} · {len(grant["permissions"])} permissions{suffix}',
                color,
                grant,
            )
            self._edge(265, principal_y[grant['principal']] + 42, 360, y + 42)
            self._edge(625, y + 42, 720, path_y[grant['path']] + 42)
        self._fit_width()

    def showEvent(self, event) -> None:
        """Size the canvas after its page receives a real viewport geometry."""
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_width)

    def _fit_width(self) -> None:
        bounds = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self.scene.setSceneRect(bounds)
        self.view.resetTransform()
        factor = min(1.0, max(0.1, (self.view.viewport().width() - 20) / max(1, bounds.width())))
        self.view.scale(factor, factor)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())

    def fit_graph(self) -> None:
        """Fit the current page of nodes while retaining native pan and zoom controls."""
        bounds = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self.scene.setSceneRect(bounds)
        self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _selection_changed(self) -> None:
        selected = self.scene.selectedItems()
        self.detail.setPlainText(json.dumps(selected[0].data(0), indent=2, ensure_ascii=False) if selected else '')
        self.statements.model.replace([])
        if not selected or self.context is None:
            self.selection_summary.setText('Select a graph node to see related statements.')
            return
        evidence = selected[0].data(0)
        service = PolicyGraphService(self._corpus)
        # Retrieve matches across pages so one visible node can reveal every
        # statement contributing to its principal/resource/action/path combination.
        grants = service.get_page(**self._graph_query, all_results=True)['grants']
        keys = ('principal', 'path', 'resource', 'effect') if 'statement_id' in evidence else ('principal', 'path')
        grants = [row for row in grants if all(row[key] == evidence[key] for key in keys if key in evidence)]
        sources = list(self.context.policy_repo.regular_statements)
        if self.include_prospective and self.context.policy_repo.tenancy_ocid:
            sources.extend(ProspectiveWorkbenchService(self.context).statement_views())
        rows = service.get_statement_evidence(grants, source_statements=sources)
        self.statements.model.replace(rows)
        selection = ' · '.join(str(evidence[key]) for key in keys if key in evidence)
        fact_count = sum(len(row['permission_facts']) for row in rows)
        self.selection_summary.setText(
            f'{selection}\n{len(rows):,} related statements · {fact_count:,} direct permission facts across all pages. '
            'Right-click a statement for details and complete facts. Conditions remain unevaluated.'
        )
