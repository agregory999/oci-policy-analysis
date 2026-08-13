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
        """Return the existing effective-permissions report as an export artifact."""
        payload = PermissionsReportService(self.context).get_export_payload()
        grant_rows = payload.get('grant_rows') or []
        return self._report_payload(
            'permissions',
            'Effective Permissions Report',
            [
                {
                    'summary': payload.get('summary') or {},
                    'grant_rows': payload.get('grant_rows') or [],
                    'effective_permissions': payload.get('report') or {},
                }
            ],
            item_label='Effective grant rows',
            item_count=len(grant_rows),
            counts={'effective_grant_rows': len(grant_rows)},
        )

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Generate one supported report by its stable identifier."""
        generators = {
            'full-overlaps': self.get_overlap_report,
            'policy-inventory': self.get_policy_inventory_report,
            'permissions': self.get_permissions_report,
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
            f"# {report.get('title') or 'OCI Policy Analysis Report'}",
            '',
            f"**Generated from data as of:** {report.get('generated_at') or 'Unknown'}  ",
            f"**{report.get('item_label') or 'Items'}:** {report.get('item_count', report.get('finding_count', 0))}",
        ]
        for label, value in (report.get('counts') or {}).items():
            if str(label).replace('_', ' ').casefold() == str(report.get('item_label') or '').casefold():
                continue
            lines.append(f"**{str(label).replace('_', ' ').title()}:** {value}")
        if report.get('report_id') == 'permissions':
            finding = next(iter(report.get('findings') or []), {})
            summary = finding.get('summary') or {}
            lines.extend(['', '## Effective Permission Summary', ''])
            lines.extend(f'- **{key}:** {value}' for key, value in summary.items())
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
                lines.extend(['', f'## Compartment: {compartment_label}', ''])
                lines.append(f"OCID: {finding.get('ocid') or 'Unknown'}  ")
                lines.append(self._tags_markdown(finding.get('tags') or {}))
                for policy in finding.get('policies') or []:
                    lines.extend(['', f"### Policy: {policy.get('name') or 'Unknown Policy'}", ''])
                    lines.append(f"OCID: {policy.get('ocid') or 'Unknown'}  ")
                    lines.append(self._tags_markdown(policy.get('tags') or {}))
                    for statement in policy.get('statements') or []:
                        lines.extend(['', 'Statement:', ''])
                        lines.extend(f'    {line}' for line in str(statement).splitlines())
                continue
            candidate = finding.get('candidate') or {}
            lines.extend(
                [
                    '',
                    f"## {number}. {candidate.get('policy_name') or 'Unknown Policy'}",
                    '',
                    f"**Effective path:** {candidate.get('effective_path') or 'Unknown'}  ",
                    f"**Statement:** `{candidate.get('statement_text') or candidate.get('internal_id') or 'Unknown'}`",
                ]
            )
            for overlap_number, overlap in enumerate(finding.get('overlaps') or [], start=1):
                permissions = ', '.join(overlap.get('permission_overlap') or []) or 'Not resolved'
                lines.extend(
                    [
                        '',
                        f'### Potential Overlap {overlap_number}',
                        '',
                        f"**Policy:** {overlap.get('superseded_by') or 'Unknown'}  ",
                        f"**Confidence:** {overlap.get('confidence') or 'Unknown'}  ",
                        f'**Permissions:** `{permissions}`  ',
                        f"**Reason:** {overlap.get('reason') or 'None provided'}",
                    ]
                )
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _tags_markdown(tags: dict[str, Any]) -> str:
        """Format a display tag map as one regular Markdown text line."""
        if not tags:
            return 'Tags: None'
        return 'Tags: ' + ', '.join(f'{key}: {value}' for key, value in tags.items())

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
