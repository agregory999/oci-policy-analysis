"""On-demand report generation services."""

from __future__ import annotations

from typing import Any

import markdown2

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.permissions_report_service import PermissionsReportService


class ReportsService:
    """Generate explicit, read-only reports without changing normal analysis.

    Args:
        context: Shared application context.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the report service.

        Args:
            context: Shared application context.
        """
        self.context = context
        self.logger = get_logger(component='reports_service')

    def get_overlap_report(self) -> dict[str, Any]:
        """Run the expensive overlap analysis and return its full JSON report.

        Returns:
            dict[str, Any]: Metadata and all candidate-to-overlap findings.
        """
        engine = self.context.intelligence
        repo = self.context.policy_repo
        self.logger.info('Generating on-demand full overlap report')
        engine.analyze_policy_overlap()
        statements = {
            str(statement.get('internal_id') or ''): statement
            for statement in (getattr(repo, 'regular_statements', []) or [])
        }
        findings = []
        for entry in engine.overlay.get('overlaps', []) or []:
            statement = statements.get(str(entry.get('statement_internal_id') or ''))
            findings.append(
                {
                    'candidate': statement or {'internal_id': entry.get('statement_internal_id') or ''},
                    'overlaps': entry.get('overlaps') or [],
                }
            )
        return {
            'report_id': 'full-overlaps',
            'title': 'Full Policy Overlap Report',
            'generated_at': getattr(repo, 'data_as_of', None),
            'finding_count': len(findings),
            'item_label': 'Overlap candidates',
            'item_count': len(findings),
            'findings': findings,
        }

    def get_policy_inventory_report(self) -> dict[str, Any]:
        """Return the loaded compartment, policy, and statement hierarchy.

        Returns:
            dict[str, Any]: Inventory grouped as compartment, policy, and statements.
        """
        repo = self.context.policy_repo
        compartments = list(getattr(repo, 'compartments', []) or [])
        policies = list(getattr(repo, 'policies', []) or [])
        statements = list(getattr(repo, 'regular_statements', []) or [])
        policies_by_compartment: dict[str, list[dict[str, Any]]] = {}
        for policy in policies:
            policies_by_compartment.setdefault(str(policy.get('compartment_ocid') or ''), []).append(policy)
        statements_by_policy: dict[tuple[str, str], list[str]] = {}
        for statement in statements:
            key = (str(statement.get('compartment_ocid') or ''), str(statement.get('policy_ocid') or ''))
            statements_by_policy.setdefault(key, []).append(str(statement.get('statement_text') or ''))

        findings = []
        for compartment in sorted(
            compartments,
            key=lambda item: str(
                item.get('hierarchy_path') or item.get('path') or item.get('compartment_path') or item.get('name') or ''
            ).casefold(),
        ):
            compartment_id = str(compartment.get('id') or '')
            inventory_policies = []
            for policy in sorted(
                policies_by_compartment.get(compartment_id, []),
                key=lambda item: str(item.get('policy_name') or '').casefold(),
            ):
                policy_id = str(policy.get('policy_ocid') or '')
                policy_statements = statements_by_policy.get((compartment_id, policy_id), [])
                inventory_policies.append(
                    {
                        'name': str(policy.get('policy_name') or '(Unnamed Policy)'),
                        'ocid': policy_id,
                        'tags': self._display_tags(policy),
                        'statements': sorted((text for text in policy_statements if text), key=str.casefold),
                    }
                )
            findings.append(
                {
                    'name': str(compartment.get('name') or '(Unnamed Compartment)'),
                    'path': str(
                        compartment.get('hierarchy_path')
                        or compartment.get('path')
                        or compartment.get('compartment_path')
                        or compartment.get('name')
                        or ''
                    ),
                    'ocid': compartment_id,
                    'tags': self._display_tags(compartment),
                    'policies': inventory_policies,
                }
            )
        return self._report_payload(
            'policy-inventory',
            'Policy Inventory Report',
            findings,
            item_label='Compartments',
            item_count=len(compartments),
            counts={'compartments': len(compartments), 'policies': len(policies), 'statements': len(statements)},
        )

    @staticmethod
    def _display_tags(item: dict[str, Any]) -> dict[str, str]:
        """Return the display tag map used by the Policy Inventory report."""
        tags = item.get('tags') or {}
        if not isinstance(tags, dict):
            return {}
        return {str(key): str(value) for key, value in sorted(tags.items(), key=lambda entry: str(entry[0]).casefold())}

    def get_permissions_report(self) -> dict[str, Any]:
        """Return the existing effective-permissions report as an export artifact.

        Equivalent grants are consolidated for this report only.  The native
        permissions report deliberately retains every source row for detail
        and CSV workflows; an on-demand report is more useful when it presents
        one effective grant with its contributing statements collected beneath
        it.
        """
        payload = PermissionsReportService(self.context).get_export_payload()
        source_grant_rows = [row for row in (payload.get('grant_rows') or []) if isinstance(row, dict)]
        grant_rows = self._consolidate_grant_rows(source_grant_rows)
        summary = dict(payload.get('summary') or {})
        summary['source_grant_row_count'] = len(source_grant_rows)
        summary['effective_grant_row_count'] = len(grant_rows)
        return self._report_payload(
            'permissions',
            'Effective Permissions Report',
            [
                {
                    'summary': summary,
                    'grant_rows': grant_rows,
                    'effective_permissions': payload.get('report') or {},
                }
            ],
            item_label='Effective grant rows',
            item_count=len(grant_rows),
            counts={
                'effective_grant_rows': len(grant_rows),
                'source_grant_rows': len(source_grant_rows),
            },
        )

    def get_supersession_report(self) -> dict[str, Any]:
        """Return complete-supersession findings grouped by effective path.

        Supersession analysis runs with the normal policy-intelligence
        strategies.  This report is a read-only rendering of that evidence;
        it does not rerun or alter analysis when the user opens it.
        """
        repo = self.context.policy_repo
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}
        statements = {
            str(statement.get('internal_id') or ''): statement
            for statement in (getattr(repo, 'regular_statements', []) or [])
            if isinstance(statement, dict)
        }
        by_path: dict[str, list[dict[str, Any]]] = {}
        for finding in overlay.get('supersessions', []) or []:
            if not isinstance(finding, dict):
                continue
            candidate = statements.get(str(finding.get('statement_internal_id') or ''))
            if not candidate:
                continue
            path = str(candidate.get('effective_path') or candidate.get('compartment_path') or 'Unknown')
            by_path.setdefault(path, []).append(
                {
                    'candidate': candidate,
                    'classification': str(finding.get('classification') or 'Supersession'),
                    'reason': str(finding.get('notes') or ''),
                    'candidate_permissions': list(finding.get('candidate_permissions') or []),
                    'evidence': list(finding.get('evidence') or []),
                }
            )
        findings = [
            {
                'path': path,
                'name': self._compartment_name(path),
                'supersessions': sorted(
                    entries,
                    key=lambda entry: (
                        str((entry.get('candidate') or {}).get('policy_name') or '').casefold(),
                        str((entry.get('candidate') or {}).get('statement_text') or '').casefold(),
                    ),
                ),
            }
            for path, entries in sorted(by_path.items(), key=lambda entry: entry[0].casefold())
        ]
        supersession_count = sum(len(finding['supersessions']) for finding in findings)
        return self._report_payload(
            'supersession',
            'Policy Supersession Report',
            findings,
            item_label='Superseded statements',
            item_count=supersession_count,
            counts={'compartments_with_supersession': len(findings), 'superseded_statements': supersession_count},
        )

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Generate one supported report by its stable identifier."""
        generators = {
            'full-overlaps': self.get_overlap_report,
            'policy-inventory': self.get_policy_inventory_report,
            'permissions': self.get_permissions_report,
            'supersession': self.get_supersession_report,
        }
        generator = generators.get(report_id)
        if generator is None:
            raise ValueError(f'Unsupported report: {report_id}')
        return generator()

    def _report_payload(
        self,
        report_id: str,
        title: str,
        findings: list[dict[str, Any]],
        *,
        item_label: str,
        item_count: int | None = None,
        counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Build common metadata for a report payload."""
        return {
            'report_id': report_id,
            'title': title,
            'generated_at': getattr(self.context.policy_repo, 'data_as_of', None),
            'finding_count': len(findings),
            'item_label': item_label,
            'item_count': item_count
            if item_count is not None
            else int((counts or {}).get('statements', len(findings))),
            'counts': counts or {},
            'findings': findings,
        }

    def to_markdown(self, report: dict[str, Any]) -> str:
        """Convert a report's native JSON structure into readable Markdown.

        Args:
            report: Generated report payload.

        Returns:
            str: Deterministic Markdown suitable for preview or download.
        """
        lines = [
            f'# {self._markdown_text(report.get("title") or "OCI Policy Analysis Report")}',
            '',
            f'**Generated from data as of:** {self._markdown_text(report.get("generated_at") or "Unknown")}  ',
            f'**{self._markdown_text(report.get("item_label") or "Items")}:** {report.get("item_count", report.get("finding_count", 0))}',
        ]
        for label, value in (report.get('counts') or {}).items():
            if str(label).replace('_', ' ').casefold() == str(report.get('item_label') or '').casefold():
                continue
            lines.append(
                f'**{self._markdown_text(str(label).replace("_", " ").title())}:** {self._markdown_text(value)}'
            )
        if report.get('report_id') == 'permissions':
            finding = next(iter(report.get('findings') or []), {})
            summary = finding.get('summary') or {}
            lines.extend(['', '## Effective Permission Summary', ''])
            lines.extend(
                f'- **{self._markdown_text(key)}:** {self._markdown_text(value)}' for key, value in summary.items()
            )
            lines.extend(
                [
                    '',
                    'The native JSON download includes the complete effective-permission hierarchy and grant rows.',
                ]
            )
            return '\n'.join(lines) + '\n'
        for number, finding in enumerate(report.get('findings') or [], start=1):
            if report.get('report_id') == 'policy-inventory':
                compartment_label = finding.get('path') or finding.get('name') or 'Unknown Compartment'
                lines.extend(['', f'## Compartment: {self._markdown_text(compartment_label)}', ''])
                lines.append(f'OCID: {self._markdown_text(finding.get("ocid") or "Unknown")}  ')
                lines.append(self._tags_markdown(finding.get('tags') or {}))
                for policy in finding.get('policies') or []:
                    lines.extend(['', f'### Policy: {self._markdown_text(policy.get("name") or "Unknown Policy")}', ''])
                    lines.append(f'OCID: {self._markdown_text(policy.get("ocid") or "Unknown")}  ')
                    lines.append(self._tags_markdown(policy.get('tags') or {}))
                    for statement in policy.get('statements') or []:
                        lines.extend(['', 'Statement:', ''])
                        lines.extend(f'    {line}' for line in str(statement).splitlines())
                continue
            if report.get('report_id') == 'supersession':
                path = str(finding.get('path') or 'Unknown Compartment')
                name = str(finding.get('name') or self._compartment_name(path))
                compartment_label = path if name == path else f'{path} ({name})'
                lines.extend(['', f'## Compartment: {self._markdown_text(compartment_label)}', ''])
                for supersession_number, supersession in enumerate(finding.get('supersessions') or [], start=1):
                    candidate = supersession.get('candidate') or {}
                    permissions = ', '.join(supersession.get('candidate_permissions') or []) or 'Not resolved'
                    lines.extend(
                        [
                            f'### {supersession_number}. {self._markdown_text(candidate.get("policy_name") or "Unknown Policy")}',
                            '',
                            f'**Superseded statement:** {self._markdown_code(candidate.get("statement_text") or candidate.get("internal_id") or "Unknown")}  ',
                            f'**Classification:** {self._markdown_text(supersession.get("classification") or "Supersession")}  ',
                            f'**Permissions covered:** {self._markdown_code(permissions)}  ',
                            f'**Why:** {self._markdown_text(supersession.get("reason") or "All candidate permissions are covered by applicable unconditional statements.")}',
                        ]
                    )
                    for evidence_number, evidence in enumerate(supersession.get('evidence') or [], start=1):
                        evidence_permissions = ', '.join(evidence.get('covered_permissions') or []) or 'Not resolved'
                        conditional_note = ' (conditional; review only)' if evidence.get('conditional') else ''
                        lines.extend(
                            [
                                '',
                                f'#### Superseding statement {evidence_number}: {self._markdown_text(evidence.get("policy_name") or "Unknown Policy")}{conditional_note}',
                                '',
                                f'**Statement:** {self._markdown_code(evidence.get("statement_text") or evidence.get("internal_id") or "Unknown")}  ',
                                f'**Effective path:** {self._markdown_text(evidence.get("effective_path") or "Unknown")}  ',
                                f'**Relationship:** {self._markdown_text(evidence.get("relationship") or "Applicable scope")}  ',
                                f'**Permissions covering candidate:** {self._markdown_code(evidence_permissions)}',
                            ]
                        )
                continue
            candidate = finding.get('candidate') or {}
            compartment_path = str(candidate.get('effective_path') or candidate.get('compartment_path') or 'Unknown')
            compartment_name = self._compartment_name(compartment_path)
            compartment_label = (
                compartment_path if compartment_name == compartment_path else f'{compartment_path} ({compartment_name})'
            )
            lines.extend(
                [
                    '',
                    f'## {number}. Compartment: {self._markdown_text(compartment_label)}',
                    '',
                    f'**Policy:** {self._markdown_text(candidate.get("policy_name") or "Unknown Policy")}  ',
                    f'**Statement:** {self._markdown_code(candidate.get("statement_text") or candidate.get("internal_id") or "Unknown")}',
                ]
            )
            for overlap_number, overlap in enumerate(finding.get('overlaps') or [], start=1):
                permissions = ', '.join(overlap.get('permission_overlap') or []) or 'Not resolved'
                lines.extend(
                    [
                        '',
                        f'### Potential Overlap {overlap_number}',
                        '',
                        f'**Policy:** {self._markdown_text(overlap.get("superseded_by") or "Unknown")}  ',
                        f'**Confidence:** {self._markdown_text(overlap.get("confidence") or "Unknown")}  ',
                        f'**Permissions:** {self._markdown_code(permissions)}  ',
                        f'**Reason:** {self._markdown_text(overlap.get("reason") or "None provided")}',
                    ]
                )
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _tags_markdown(tags: dict[str, Any]) -> str:
        """Format a display tag map as one regular Markdown text line."""
        if not tags:
            return 'Tags: None'
        return 'Tags: ' + ', '.join(
            f'{ReportsService._markdown_text(key)}: {ReportsService._markdown_text(value)}'
            for key, value in tags.items()
        )

    @staticmethod
    def _markdown_text(value: object) -> str:
        """Escape report data so Markdown renderers preserve it as literal text."""
        text = str(value)
        text = text.replace('\\', '\\\\')
        for character in '`*_{}[]<>':
            text = text.replace(character, f'\\{character}')
        return text

    @staticmethod
    def _markdown_code(value: object) -> str:
        """Format arbitrary report data as a safe inline code span."""
        return '`' + str(value).replace('`', '\\`') + '`'

    @staticmethod
    def _compartment_name(path: object) -> str:
        """Return the final display segment of a compartment path."""
        segments = [segment for segment in str(path or '').strip('/').split('/') if segment]
        return segments[-1] if segments else str(path or 'Unknown Compartment')

    @staticmethod
    def _consolidate_grant_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge duplicate effective grants while retaining every source statement."""
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for row in rows:
            key = tuple(
                str(row.get(field) or '')
                for field in ('effective_path', 'principal_key', 'action', 'resource', 'permission', 'conditional')
            )
            grouped.setdefault(key, []).append(row)

        consolidated: list[dict[str, Any]] = []
        for key in sorted(grouped, key=lambda item: tuple(part.casefold() for part in item)):
            source_rows = grouped[key]
            representative = dict(source_rows[0])
            sources_by_id: dict[tuple[str, str, str, str], dict[str, Any]] = {}
            for row in source_rows:
                source = {
                    'grant_path': str(row.get('grant_path') or ''),
                    'policy_name': str(row.get('policy_name') or ''),
                    'statement_id': str(row.get('statement_id') or ''),
                    'statement_text': str(row.get('statement_text') or ''),
                }
                sources_by_id[tuple(source.values())] = source
            sources = sorted(
                sources_by_id.values(),
                key=lambda item: (
                    item['grant_path'].casefold(),
                    item['policy_name'].casefold(),
                    item['statement_text'].casefold(),
                ),
            )
            grant_paths = sorted({source['grant_path'] for source in sources if source['grant_path']}, key=str.casefold)
            original_subject_keys = sorted(
                {str(row.get('original_subject_key') or '') for row in source_rows if row.get('original_subject_key')},
                key=str.casefold,
            )
            representative['grant_path'] = grant_paths[0] if len(grant_paths) == 1 else 'Multiple'
            representative['grant_paths'] = grant_paths
            representative['inherited'] = any(bool(row.get('inherited')) for row in source_rows)
            representative['inherited_from'] = ', '.join(
                sorted(
                    {str(row.get('inherited_from') or '') for row in source_rows if row.get('inherited_from')},
                    key=str.casefold,
                )
            )
            representative['original_subject_keys'] = original_subject_keys
            representative['source_statement_count'] = len(sources)
            representative['source_statements'] = sources
            if len(sources) != 1:
                representative['policy_name'] = ', '.join(
                    sorted({source['policy_name'] for source in sources if source['policy_name']}, key=str.casefold)
                )
                representative['statement_id'] = ''
                representative['statement_text'] = ''
            consolidated.append(representative)
        return consolidated

    def with_rendered_formats(self, report: dict[str, Any]) -> dict[str, Any]:
        """Attach Markdown and safe preview HTML to a native report payload.

        Args:
            report: Native JSON report payload.

        Returns:
            dict[str, Any]: Report payload with Markdown and rendered HTML.
        """
        rendered = dict(report)
        markdown = self.to_markdown(report)
        rendered['markdown'] = markdown
        html = markdown2.markdown(markdown, safe_mode='escape')
        # tkhtmlview recognizes pre/code but its default fixed-font discovery is unreliable
        # on some macOS Tk installations. An explicit lowercase family is recognized by
        # the renderer's CSS parser and preserves portable HTML semantics elsewhere.
        rendered['markdown_html'] = html.replace(
            '<pre><code>', '<pre style="font-family: courier"><code style="font-family: courier">'
        )
        return rendered
