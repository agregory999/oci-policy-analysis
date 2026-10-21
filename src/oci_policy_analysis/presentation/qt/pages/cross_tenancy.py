"""Native cross-tenancy graph and parsed evidence over the shared projection."""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.cross_tenancy_analysis_service import CrossTenancyAnalysisService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import label


class CrossTenancyPage(QWidget):
    """Inspect local parsed trust and association evidence without remote lookups.

    Attributes:
        details_requested: Source or relationship evidence for the shared drawer.
        payload: Detached service projection for the current loaded snapshot.
        tables: Parsed source tables, keyed by projection section.

    Notes:
        A local Admit or Endorse does not prove reciprocal remote permission.
        The complete tenancy map is scrollable. Entity and finding tables retain
        all projected evidence, including unresolved definitions.
    """

    details_requested = Signal(object, str)

    def __init__(self) -> None:
        """Build a selectable, zoomable native graph and read-only evidence tabs."""
        super().__init__()
        self.context = None
        self.payload = {}
        self.selection_keys = None
        self._drawing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(label('Relationship / entity', 'muted'))
        self.relationship = QComboBox()
        self.relationship.setMinimumWidth(240)
        controls.addWidget(self.relationship, 1)
        generate = QPushButton('Generate single Cross-Tenancy Policy')
        generate.clicked.connect(self._show_single_policy)
        controls.addWidget(generate)
        reset = QPushButton('Clear selection')
        reset.clicked.connect(self.clear_selection)
        controls.addWidget(reset)
        for title, callback in (
            ('−', lambda: self.view.scale(0.8, 0.8)),
            ('+', lambda: self.view.scale(1.25, 1.25)),
            ('Fit', self.fit_graph),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = label('Load a snapshot to inspect cross-tenancy policies.', 'muted', wrap=True)
        layout.addWidget(self.status)
        layout.addWidget(
            label(
                'Local evidence only. Remote reciprocal policies are not verified. Arrows show Admit (incoming), '
                'Endorse (outgoing), or association participants; conditions and exclusions still apply.',
                'notice',
                wrap=True,
            )
        )
        split = QSplitter(Qt.Orientation.Vertical)
        graph_panel = QWidget()
        graph_layout = QVBoxLayout(graph_panel)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setMinimumHeight(180)
        graph_layout.addWidget(self.view, 1)
        paging = QHBoxLayout()
        self.graph_status = label('', 'muted')
        paging.addWidget(self.graph_status, 1)
        graph_layout.addLayout(paging)
        split.addWidget(graph_panel)
        evidence = QWidget()
        lower = QVBoxLayout(evidence)
        lower.setContentsMargins(0, 8, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter displayed cross-tenancy evidence…')
        self.search.setClearButtonEnabled(True)
        lower.addWidget(self.search)
        self.tabs = QTabWidget()
        self.tables = {}
        self.statements_table = StatementTable((('Policy Name', 'policy_name'), ('Statement', 'statement_text')))
        self.statements_table.setColumnWidth(0, 240)
        self.statements_table.details_requested.connect(self._statement_details)
        self.tables['statements'] = self.statements_table
        self.tabs.addTab(self.statements_table, 'Statements')
        self.entities = RecordTable(
            (
                ('Type', 'kind'),
                ('Name', 'name'),
                ('Tenancy', 'tenancy_display'),
                ('Defined OCID', 'defined_ocid'),
                ('Ownership evidence', 'ownership_basis'),
            ),
            details_title='Cross-tenancy entity details',
        )
        self.entities.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Cross-tenancy entity details')
        )
        self.entities.selectionModel().selectionChanged.connect(self._entity_selected)
        self.tabs.addTab(self.entities, 'Entities / definitions')
        self.findings = RecordTable(
            (
                ('Type', 'Type'),
                ('Severity', 'Severity'),
                ('Policy', 'Policy Name'),
                ('Issue', 'Issue'),
                ('Statement', 'Statement Text'),
            ),
            details_title='Cross-tenancy finding details',
        )
        self.findings.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Cross-tenancy finding details')
        )
        self.findings.selectionModel().selectionChanged.connect(self._finding_selected)
        self.tabs.addTab(self.findings, 'Findings')
        lower.addWidget(self.tabs, 1)
        self.counts = label('', 'muted', wrap=True)
        lower.addWidget(self.counts)
        split.addWidget(evidence)
        split.setSizes([300, 400])
        layout.addWidget(split, 1)
        self.relationship.currentIndexChanged.connect(self._relationship_changed)
        self.scene.selectionChanged.connect(self._graph_selected)
        self.search.textChanged.connect(self._filter)
        self.tabs.currentChanged.connect(lambda *_: self.details_requested.emit(None, ''))

    def set_context(self, context) -> None:
        """Reproject the current snapshot and clear stale graph and source selections.

        Args:
            context: Loaded application context, or None to clear the page.
        """
        self.context = context
        self.details_requested.emit(None, '')
        self.payload = (
            CrossTenancyAnalysisService(
                context.policy_repo,
                (getattr(context.intelligence, 'overlay', {}) or {}).get('cross_tenancy_findings', []),
                getattr(context, 'cross_tenancy_corpus', None),
            ).get_analysis_payload()
            if context
            else {}
        )
        self.selection_keys = None
        self.search.clear()
        graph = self.payload.get('relationship_graph') or {}
        self.relationship.blockSignals(True)
        self.relationship.clear()
        self.relationship.addItem('All relationships', None)
        for node in graph.get('tenancies', []):
            self.relationship.addItem(f'Tenancy · {node["alias"]}', node)
        for link in graph.get('links', []):
            kind = 'Association' if link.get('association') else 'Trust'
            self.relationship.addItem(f'{kind} · {link["alias"]} · {link["direction"]}', link)
        entities = [dict(row) for row in graph.get('subnodes', [])]
        for row in graph.get('defined_entities', []):
            entities.append(
                {
                    **row,
                    'kind': row.get('defined_type'),
                    'name': row.get('defined_name'),
                    'ownership_basis': (
                        'Unused definition; ownership not inferred'
                        if row.get('orphan')
                        else 'Defined in a source policy'
                    ),
                }
            )
        tenancy_nodes = {str(row.get('alias') or '').casefold(): row for row in graph.get('tenancies', [])}
        for definition in self.payload.get('defines', []):
            if str(definition.get('defined_type') or '').casefold() == 'tenancy':
                alias = str(definition.get('defined_name') or '')
                node = tenancy_nodes.get(alias.casefold(), {})
                entities.append(
                    {
                        **definition,
                        'kind': 'tenancy',
                        'name': alias,
                        'tenancy_alias': alias,
                        'statement_keys': node.get('statement_keys') or [definition.get('stable_key')],
                        'ownership_basis': 'Defined in a source policy',
                    }
                )
        definitions = {}
        for definition in self.payload.get('defines', []):
            definitions.setdefault(
                (
                    str(definition.get('defined_type') or '').casefold(),
                    str(definition.get('defined_name') or '').casefold(),
                ),
                set(),
            ).add(str(definition.get('ocid_alias') or ''))
        for row in entities:
            ocids = definitions.get(
                (str(row.get('kind') or '').casefold(), str(row.get('name') or '').casefold()), set()
            )
            row['defined_ocid'] = row.get('ocid_alias') or ', '.join(sorted(ocids - {''}))
            row['tenancy_display'] = (
                f'{(self.payload.get("local_tenancy") or {}).get("name") or "This tenancy"} (local)'
                if row.get('tenancy_alias') == 'local'
                else row.get('tenancy_alias') or 'Unresolved'
            )
            self.relationship.addItem(
                f'{row.get("kind")} · {row.get("name")} · {row.get("tenancy_alias") or "unplaced"}', row
            )
        self.relationship.blockSignals(False)
        self.entities.model.replace(entities)
        findings = [dict(row) for row in self.payload.get('findings', [])]
        findings.extend(self._unknown_findings(findings))
        self.findings.model.replace(findings)
        counts = self.payload.get('counts') or {}
        self.status.setText(
            ' · '.join(
                f'{title}: {counts.get(key, 0):,}'
                for key, title in (
                    ('defines', 'Defines'),
                    ('admit', 'Admit'),
                    ('endorse', 'Endorse'),
                    ('unknown', 'Unresolved'),
                    ('findings', 'Findings'),
                )
            )
        )
        self._draw_graph()
        self._filter()

    def _unknown_findings(self, findings=()):
        """Add unclassified and unresolved source evidence not already in findings."""
        seen = {source_id for finding in findings for source_id in finding.get('source_ids') or [] if source_id}
        rows = []
        for row in self.payload.get('unknown_statements', []) or []:
            source_id = row.get('stable_key')
            if source_id and source_id in seen:
                continue
            if source_id:
                seen.add(source_id)
            rows.append(
                {
                    'Type': 'Unresolved statement',
                    'Severity': 'Review',
                    'Policy Name': row.get('policy_name') or 'Unnamed policy',
                    'Issue': 'Statement is not a parsed Define, Admit, or Endorse statement.',
                    'Statement Text': row.get('statement_text') or '',
                    'source_ids': [source_id] if source_id else [],
                }
            )
        for row in [
            *(self.payload.get('admit_statements', []) or []),
            *(self.payload.get('endorse_statements', []) or []),
        ]:
            source_id = row.get('stable_key')
            unresolved = [
                reference
                for reference in row.get('external_tenancies') or []
                if reference.get('status') in {'unresolved', 'ambiguous'}
            ]
            if not unresolved or (source_id and source_id in seen):
                continue
            aliases = ', '.join(str(reference.get('alias') or 'unknown') for reference in unresolved)
            ambiguous = any(reference.get('status') == 'ambiguous' for reference in unresolved)
            rows.append(
                {
                    'Type': 'Ambiguous tenancy reference' if ambiguous else 'Unresolved tenancy reference',
                    'Severity': 'Review',
                    'Policy Name': row.get('policy_name') or 'Unnamed policy',
                    'Issue': f'Tenancy alias cannot be uniquely resolved: {aliases}.',
                    'Statement Text': row.get('statement_text') or '',
                    'source_ids': [source_id] if source_id else [],
                }
            )
            if source_id:
                seen.add(source_id)
        return rows

    def _statement_details(self, record):
        title = f'{record.get("kind") or "Cross-tenancy"} statement details' if record else ''
        self.details_requested.emit(record, title)

    def _show_single_policy(self):
        generated = CrossTenancyAnalysisService.generate_single_policy(self.payload)
        dialog = QDialog(self)
        dialog.setWindowTitle('Single Cross-Tenancy Policy')
        dialog.resize(860, 620)
        layout = QVBoxLayout(dialog)
        note = label(
            f'Included: {generated["included"]} valid, resolved Define / Admit / Endorse statements from all loaded policies. '
            f'Not included: {generated["invalid_or_unparsed"]} invalid or unparsed, '
            f'{generated["unresolved_or_ambiguous"]} unresolved or ambiguous, and '
            f'{generated["unclassified"]} unclassified statements.',
            'notice',
            wrap=True,
        )
        layout.addWidget(note)
        policies = generated.get('policies') or [{'name': 'CrossTenancy-01', 'text': generated.get('text', '')}]
        selector = QComboBox()
        selector.addItems(
            [f'{item["name"]} · {item.get("included", len(item["text"].splitlines()))} statements' for item in policies]
        )
        selector.setVisible(len(policies) > 1)
        layout.addWidget(selector)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(policies[0]['text'] or 'No valid, resolved cross-tenancy statements are available.')
        selector.currentIndexChanged.connect(lambda index: text.setPlainText(policies[index]['text']))
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = buttons.addButton('Copy policy', QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(policies[selector.currentIndex()]['text']))
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def clear_selection(self) -> None:
        """Restore all source evidence without changing loaded tenancy data."""
        self.relationship.setCurrentIndex(0)
        self.scene.clearSelection()
        self.entities.clearSelection()
        self.findings.clearSelection()
        self.selection_keys = None
        self.details_requested.emit(None, '')
        self._filter()

    def refresh_graph(self) -> None:
        """Redraw the current graph using the inherited appearance preferences."""
        self._draw_graph()

    def fit_graph(self) -> None:
        """Fit the complete tenancy map while retaining manual zoom controls."""
        self.view.fitInView(
            self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio
        )

    def _relationship_changed(self, *_args):
        record = self.relationship.currentData()
        self._select(record)

    def _select(self, record):
        self.details_requested.emit(None, '')
        self.selection_keys = set(record.get('statement_keys') or []) if record else None
        alias = str(record.get('alias') or '') if record else ''
        if record and record.get('graph_role') == 'local':
            self.selection_keys = {
                key
                for node in (self.payload.get('relationship_graph') or {}).get('subnodes', [])
                if node.get('tenancy_alias') == 'local'
                for key in node.get('statement_keys') or []
            }
        if alias and self.selection_keys is not None:
            self.selection_keys.update(
                row.get('stable_key')
                for row in self.payload.get('defines', [])
                if str(row.get('defined_type') or '').casefold() == 'tenancy'
                and str(row.get('defined_name') or '').casefold() == alias.casefold()
            )
        if self.selection_keys:
            related = set(self.selection_keys)
            for entity in (self.payload.get('relationship_graph') or {}).get('defined_entities', []):
                entity_keys = set(entity.get('statement_keys') or [])
                if entity_keys & related:
                    related.update(entity_keys)
            for tenancy in (self.payload.get('relationship_graph') or {}).get('tenancies', []):
                if set(tenancy.get('statement_keys') or []) & related:
                    related.update(tenancy.get('statement_keys') or [])
            self.selection_keys = related
        self._filter()

    def _entity_selected(self, *_args):
        rows = self.entities.selected_records()
        if rows:
            self._select(rows[0])

    def _finding_selected(self, *_args):
        rows = self.findings.selected_records()
        if rows:
            finding = rows[0]
            keys = set(finding.get('source_ids') or [])
            if keys:
                self.selection_keys = keys
                self._filter()
            self.details_requested.emit(finding, 'Cross-tenancy finding details')

    def _graph_selected(self):
        if self._drawing:
            return
        selected = self.scene.selectedItems()
        if selected:
            self._select(selected[0].data(0))

    def _filter(self, *_args):
        rows = [
            *self.payload.get('defines', []),
            *self.payload.get('admit_statements', []),
            *self.payload.get('endorse_statements', []),
        ]
        selected = [row for row in rows if self.selection_keys is None or row.get('stable_key') in self.selection_keys]
        self.statements_table.model.replace(selected)
        self.statements_table.proxy.setFilterFixedString(self.search.text())
        shown, total = self.statements_table.proxy.rowCount(), len(rows)
        for table in (self.entities, self.findings):
            table.proxy.setFilterFixedString(self.search.text())
        self.counts.setText(
            f'{shown:,} shown / {total:,} Define, Admit, and Endorse statements · '
            'Click a graph item to filter; right-click a statement for details.'
        )
        tab_index = self.tabs.indexOf(self.statements_table)
        filtered = self.selection_keys is not None or bool(self.search.text())
        self.tabs.setTabText(tab_index, 'Statements (Filtered)' if filtered else 'Statements (All)')

    def _node(self, x, y, title, record, *, entities=(), width=260):
        palette = self.palette()
        metrics = QFontMetrics(self.font())
        aliases = [
            metrics.elidedText(str(line), Qt.TextElideMode.ElideRight, width - 24) for line in title.splitlines()
        ]
        shown_entities = list(entities[:3])
        entity_lines = [
            f'↳ {entity.get("kind", "entity")}: {entity.get("name", "")} · {entity.get("ownership_basis", "related")}'
            for entity in shown_entities
        ]
        if len(entities) > len(shown_entities):
            entity_lines.append(f'↳ +{len(entities) - len(shown_entities)} more entities')
        entity_lines = [metrics.elidedText(line, Qt.TextElideMode.ElideRight, width - 24) for line in entity_lines]
        height = max(70, metrics.lineSpacing() * (len(aliases) + len(entity_lines)) + 18)
        item = self.scene.addRect(x, y, width, height, QPen(palette.text().color()), QBrush(palette.base().color()))
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        item.setData(0, record)
        item.setToolTip(title + ('\n' + '\n'.join(entity_lines) if entity_lines else ''))
        text = self.scene.addSimpleText('\n'.join([*aliases, *entity_lines]), self.font())
        text.setBrush(palette.text())
        text.setParentItem(item)
        text.setPos(x + 8, y + 6)
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return height

    def _draw_graph(self):
        self._drawing = True
        try:
            self.scene.clear()
            self.view.setBackgroundBrush(self.palette().window())
            graph = self.payload.get('relationship_graph') or {}
            all_tenancies = graph.get('tenancies', [])
            links = graph.get('links', [])
            subnodes = graph.get('subnodes', [])
            local = self.payload.get('local_tenancy') or {}
            incoming_aliases = {
                str(link.get('alias') or '').casefold() for link in links if link.get('direction') == 'incoming'
            }
            outgoing_aliases = {
                str(link.get('alias') or '').casefold() for link in links if link.get('direction') == 'outgoing'
            }
            association_aliases = {str(link.get('alias') or '').casefold() for link in links if link.get('association')}
            tenancy_by_alias = {str(node.get('alias') or '').casefold(): node for node in all_tenancies}
            incoming = [tenancy_by_alias[key] for key in sorted(incoming_aliases) if key in tenancy_by_alias]
            outgoing = [
                tenancy_by_alias[key] for key in sorted(outgoing_aliases - incoming_aliases) if key in tenancy_by_alias
            ]
            # Association participants are shown on both sides to make their two-sided role explicit.
            for key in sorted(association_aliases):
                if key in tenancy_by_alias:
                    if tenancy_by_alias[key] not in incoming:
                        incoming.append(tenancy_by_alias[key])
                    if tenancy_by_alias[key] not in outgoing:
                        outgoing.append(tenancy_by_alias[key])
            known = incoming_aliases | outgoing_aliases | association_aliases
            unknown_nodes = [node for node in all_tenancies if str(node.get('alias') or '').casefold() not in known]
            unknown_rows = self.payload.get('unknown_statements', [])
            # A source may be unparsed before the projector can infer a remote alias.
            resolved_aliases = {str(node.get('alias') or '').casefold() for node in all_tenancies}
            for index, statement in enumerate(unknown_rows):
                for external in statement.get('external_tenancies') or []:
                    alias = str(external.get('alias') or '').strip()
                    if alias and alias.casefold() not in resolved_aliases:
                        unknown_nodes.append(
                            {
                                'id': f'unresolved:{alias.casefold()}:{index}',
                                'alias': alias,
                                'resolved': False,
                                'special': bool(external.get('special')),
                                'statement_keys': [statement.get('stable_key')],
                            }
                        )
                        resolved_aliases.add(alias.casefold())
                if not statement.get('external_tenancies'):
                    unknown_nodes.append(
                        {
                            'id': f'unresolved:source:{index}',
                            'alias': 'Unresolved tenancy reference',
                            'resolved': False,
                            'special': False,
                            'statement_keys': [statement.get('stable_key')],
                        }
                    )
            unknown_nodes = [*unknown_nodes]

            def owned(alias):
                return [
                    node for node in subnodes if str(node.get('tenancy_alias') or '').casefold() == alias.casefold()
                ]

            def unknown_evidence(alias):
                keys = set()
                if alias:
                    keys.update(
                        row.get('stable_key')
                        for row in unknown_rows
                        if alias.casefold()
                        in {str(item.get('alias') or '').casefold() for item in row.get('external_tenancies') or []}
                    )
                return keys

            for x, title in (
                (0, 'Admit Tenancy (controls us)'),
                (470, 'Our tenancy'),
                (940, 'Endorse Tenancy (we control)'),
            ):
                heading = self.scene.addSimpleText(title, self.font())
                heading.setBrush(self.palette().text())
                heading.setPos(x, 0)
            row_gap = max(132, QFontMetrics(self.font()).lineSpacing() * 5 + 24)
            unresolved_incoming = [node for node in incoming if not node.get('resolved') and not node.get('special')]
            left_rows = [node for node in incoming if node not in unresolved_incoming]
            left_rows.extend(unresolved_incoming)
            left_rows.extend(unknown_nodes)
            right_rows = outgoing
            row_count = max(1, len(left_rows), len(right_rows))
            local_y = 45 + (row_count - 1) * row_gap * 0.25
            local_box = self._node(
                470,
                local_y,
                f'{local.get("name") or "Local tenancy"}\n(local)',
                {**local, 'graph_role': 'local'},
                entities=owned('local'),
            )
            line_pen = QPen(self.palette().highlight().color(), 2)
            unknown_pen = QPen(self.palette().mid().color(), 2, Qt.PenStyle.DashLine)

            def place_remote(node, index, side, kind):
                alias = str(node.get('alias') or 'Unresolved tenancy')
                y = 45 + index * row_gap
                entities = owned(alias)
                status = (
                    'resolved' if node.get('resolved') else 'special reference' if node.get('special') else 'unresolved'
                )
                x = 0 if side == 'left' else 940
                record = {**node, 'graph_role': kind}
                height = self._node(x, y, f'{alias}\n{status} · {kind}', record, entities=entities)
                source_keys = set(node.get('statement_keys') or [])
                if kind == 'other / unresolved':
                    source_keys.update(unknown_evidence(alias))
                matching_links = [
                    link
                    for link in links
                    if str(link.get('alias') or '').casefold() == alias.casefold()
                    and (
                        link.get('direction') == ('incoming' if side == 'left' else 'outgoing')
                        or link.get('association')
                    )
                ]
                if not matching_links and source_keys:
                    matching_links = [
                        {
                            'alias': alias,
                            'direction': 'incoming' if side == 'left' else 'outgoing',
                            'association': False,
                            'statement_keys': sorted(source_keys),
                            'count': len(source_keys),
                            'id': node.get('id'),
                        }
                    ]
                for offset, link in enumerate(matching_links):
                    local_point = QPointF(730 if side == 'right' else 470, local_y + local_box / 2 + offset * 4)
                    remote_point = QPointF(
                        x + (260 if side == 'left' else 0), y + min(height / 2 + offset * 4, height - 12)
                    )
                    start, end = (remote_point, local_point) if side == 'left' else (local_point, remote_point)
                    if link.get('association'):
                        # Two arrows show that an association involves both tenancy scopes.
                        self._arrow(start, end, link, line_pen)
                        self._arrow(end, start, link, line_pen)
                    else:
                        self._arrow(
                            start,
                            end,
                            link,
                            unknown_pen
                            if kind == 'other / unresolved' or link.get('direction') == 'unknown'
                            else line_pen,
                        )

            for index, node in enumerate(left_rows):
                is_unknown = node in unknown_nodes or (not node.get('resolved') and not node.get('special'))
                place_remote(node, index, 'left', 'other / unresolved' if is_unknown else 'Admit tenancy')
            for index, node in enumerate(right_rows):
                place_remote(node, index, 'right', 'Endorsed tenancy')
            self.graph_status.setText(
                f'{len(all_tenancies):,} referenced tenancies · {len(links):,} trust or association links · '
                f'{len(subnodes):,} inferred entities · '
                f'{len(unknown_nodes) + len(unresolved_incoming):,} other / unresolved · '
                'Select a node or arrow to filter statements'
            )
            self.view.setSceneRect(self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))
            self.view.resetTransform()
        finally:
            self._drawing = False

    def _arrow(self, start, end, record, pen):
        line = self.scene.addLine(start.x(), start.y(), end.x(), end.y(), pen)
        line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        line.setData(0, record)
        line.setToolTip(f'{record.get("alias", "Tenancy relationship")} · {record.get("count", 0)} source statements')
        direction = end - start
        angle = __import__('math').atan2(direction.y(), direction.x())
        from math import cos, pi, sin

        points = [
            end,
            *[
                QPointF(end.x() - 12 * cos(angle + turn), end.y() - 12 * sin(angle + turn))
                for turn in (-pi / 6, pi / 6)
            ],
        ]
        arrow = self.scene.addPolygon(QPolygonF(points), pen, QBrush(pen.color()))
        arrow.setParentItem(line)
        arrow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        kind = (
            'Association'
            if record.get('association')
            else 'Admit'
            if record.get('direction') == 'incoming'
            else 'Endorse'
        )
        caption = self.scene.addSimpleText(f'{kind} · {record.get("count", 0)}', self.font())
        caption.setBrush(self.palette().text())
        caption.setPos((start.x() + end.x()) / 2, (start.y() + end.y()) / 2 - 18)
        caption.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
