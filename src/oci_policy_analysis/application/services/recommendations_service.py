"""Service facade for read-only recommendations data shaping.

This service adapts policy intelligence overlay outputs into stable web payloads
for the recommendations page. It intentionally excludes mutable workbench
actions and focuses on display-only analytics.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.common.consolidation_opportunities import build_consolidation_opportunities
from oci_policy_analysis.application.core.engine.recommendation_actions import overly_broad_statement_guidance
from oci_policy_analysis.application.core.support.logger import get_logger


class RecommendationsService:
    """Provide read-only recommendations datasets for web consumers.

    Args:
        context: Shared application context.
    """

    STATEMENT_LIMIT = 500
    NEARING_THRESHOLD = 0.85

    def __init__(self, context: AppContext) -> None:
        """Initialize the recommendations service.

        Args:
            context: Shared application context.
        """
        self.context = context
        self.logger = get_logger(component='recommendations_service')

    def get_dashboard_payload(self) -> dict[str, Any]:
        """Return full recommendations dashboard payload.

        Returns:
            dict[str, Any]: Read-only recommendations sections for web display.
        """
        repo = self.context.policy_repo
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}

        if not overlay:
            self.logger.warning('Recommendations overlay is empty; returning dashboard payload with empty sections')

        self.logger.info(
            'Building recommendations dashboard payload for tenancy=%s data_as_of=%s',
            getattr(repo, 'tenancy_ocid', None),
            getattr(repo, 'data_as_of', None),
        )

        tenancy_policy_limits = self._tenancy_policy_limits_payload()
        payload = {
            'summary': list(overlay.get('recommendations', []) or []),
            'summary_counts': self._summary_counts(list(overlay.get('recommendations', []) or [])),
            'risk_policy': self._policy_risk_rows(),
            'risk_statement': self._statement_risk_rows(),
            'supersession': self._supersession_rows(),
            'consolidation': build_consolidation_opportunities(overlay, repo),
            'cleanup': self._cleanup_rows(),
            'limits': self._limits_rows(),
            'tenancy_policy_limits': tenancy_policy_limits,
            'meta': {
                'tenancy_ocid': getattr(repo, 'tenancy_ocid', None),
                'tenancy_name': getattr(repo, 'tenancy_name', None),
                'data_as_of': getattr(repo, 'data_as_of', None),
            },
        }

        self.logger.info(
            'Recommendations dashboard payload built: summary=%s risk_policy=%s risk_statement=%s supersession=%s consolidation=%s cleanup=%s limits=%s',
            len(payload['summary']),
            len(payload['risk_policy']),
            len(payload['risk_statement']),
            len(payload['supersession']),
            len(payload['consolidation']),
            len(payload['cleanup']),
            len(payload['limits']),
        )
        return payload

    def _tenancy_policy_limits_payload(self) -> dict[str, Any]:
        """Return snapshot-specific limits and whether this source may edit them."""
        repo = self.context.policy_repo
        limits = dict(getattr(repo, 'tenancy_policy_limits', {}) or {})
        offline_editable = bool(
            getattr(repo, 'current_cache_name', '') or getattr(repo, 'loaded_from_compliance_output', False)
        )
        if not offline_editable and getattr(repo, 'limits_client', None) and not limits:
            repo.fetch_tenancy_policy_statement_limits()
            limits = dict(getattr(repo, 'tenancy_policy_limits', {}) or {})
        max_chain = max(
            (int(c.get('statement_count_cumulative', 0) or 0) for c in getattr(repo, 'compartments', []) or []),
            default=0,
        )
        return {
            **limits,
            'policy_count': len(getattr(repo, 'policies', []) or []),
            'max_chain_count': max_chain,
            'offline_editable': offline_editable,
        }

    def _supersession_rows(self) -> list[dict[str, Any]]:
        """Build display rows while retaining complete supersession evidence.

        Returns:
            list[dict[str, Any]]: Candidate statements with their complete
            unconditional and conditional coverage evidence.
        """
        repo = self.context.policy_repo
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}
        statements = {
            str(statement.get('internal_id') or ''): statement
            for statement in (getattr(repo, 'regular_statements', []) or [])
        }
        rows: list[dict[str, Any]] = []
        for finding in overlay.get('supersessions', []) or []:
            statement = statements.get(str(finding.get('statement_internal_id') or ''))
            if not statement:
                continue
            evidence = finding.get('evidence', []) or []
            rows.append(
                {
                    'Policy Name': statement.get('policy_name') or '',
                    'Policy Compartment': statement.get('compartment_path') or '',
                    'Effective Path': statement.get('effective_path') or '',
                    'Statement Text': (statement.get('statement_text') or '')[:500],
                    'Classification': finding.get('classification') or '',
                    'Superseded By': ', '.join(
                        f"{item.get('policy_name') or 'Unknown'} ({item.get('relationship') or 'Applicable scope'})"
                        for item in evidence
                    ),
                    'Candidate Permissions': list(finding.get('candidate_permissions') or []),
                    'Notes': finding.get('notes') or '',
                    'Evidence': evidence,
                    'Internal ID': finding.get('statement_internal_id') or '',
                }
            )
        rows.sort(key=lambda row: (str(row['Effective Path']), str(row['Policy Name']), str(row['Statement Text'])))
        return rows

    def _summary_counts(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Return severity/category counts for recommendation summary filters."""

        severity: dict[str, int] = defaultdict(int)
        category: dict[str, int] = defaultdict(int)
        for row in rows:
            severity[str(row.get('Priority') or 'Unspecified')] += 1
            category[str(row.get('Category') or 'Unspecified')] += 1
        return {'severity': dict(severity), 'category': dict(category)}

    def _policy_path(self, policy_ocid: str | None = None, policy_obj: dict[str, Any] | None = None) -> str:
        """Resolve canonical policy path for display.

        Args:
            policy_ocid: Policy OCID lookup key.
            policy_obj: Existing policy object.

        Returns:
            str: Path in ``ROOT/.../PolicyName`` style.
        """
        repo = self.context.policy_repo
        policy = policy_obj
        if policy is None and policy_ocid:
            for item in getattr(repo, 'policies', []) or []:
                if item.get('policy_ocid') == policy_ocid:
                    policy = item
                    break
        if not policy:
            return '[Unknown Policy Path]'
        comp_path = str(policy.get('compartment_path') or '').strip('/')
        name = str(policy.get('policy_name') or '')
        return f'{comp_path}/{name}'.replace('//', '/') if comp_path else name

    def _statement_risk_rows(self) -> list[dict[str, Any]]:
        """Build statement risk rows.

        Returns:
            list[dict[str, Any]]: Statement-level risk rows.
        """
        repo = self.context.policy_repo
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}
        risk_scores = overlay.get('risk_scores', []) or []
        by_id = {entry.get('statement_internal_id'): entry for entry in risk_scores}

        rows: list[dict[str, Any]] = []
        for statement in getattr(repo, 'regular_statements', []) or []:
            if str(statement.get('action') or '').lower() == 'deny':
                continue
            internal_id = statement.get('internal_id')
            risk_entry = by_id.get(internal_id, {})
            rows.append(
                {
                    'Policy Path': self._policy_path(policy_ocid=statement.get('policy_ocid')),
                    'Effective Path': statement.get('effective_path') or '',
                    'Score': int(risk_entry.get('score', 0) or 0),
                    'Risk Notes': risk_entry.get('notes', ''),
                    'Statement Text': (statement.get('statement_text') or '')[:240],
                }
            )

        max_score = max((row['Score'] for row in rows), default=1)
        for row in rows:
            raw = row['Score']
            if raw <= 0 or max_score <= 1:
                row['Relative Risk'] = 1
            else:
                # log-based normalization (parity with TK risk view)
                import math

                row['Relative Risk'] = max(1, int((math.log(raw) / math.log(max_score)) * 100))
        rows.sort(key=lambda r: int(r.get('Relative Risk', 0)), reverse=True)
        return rows

    def _policy_risk_rows(self) -> list[dict[str, Any]]:
        """Build policy-level aggregated risk rows.

        Returns:
            list[dict[str, Any]]: Aggregated risk-by-policy rows.
        """
        repo = self.context.policy_repo
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}
        risk_scores = overlay.get('risk_scores', []) or []
        by_id = {entry.get('statement_internal_id'): entry for entry in risk_scores}
        policy_by_ocid = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for st in getattr(repo, 'regular_statements', []) or []:
            if str(st.get('action') or '').lower() == 'deny':
                continue
            policy_ocid = st.get('policy_ocid')
            if policy_ocid:
                grouped[policy_ocid].append(st)

        global_max = 1
        for statements in grouped.values():
            for st in statements:
                score = int((by_id.get(st.get('internal_id'), {}) or {}).get('score', 0) or 0)
                global_max = max(global_max, score)

        rows: list[dict[str, Any]] = []
        for policy_ocid, statements in grouped.items():
            scores: list[int] = []
            notes: set[str] = set()
            example_statement = ''
            example_score = -1
            for st in statements:
                risk = by_id.get(st.get('internal_id'), {}) or {}
                score = int(risk.get('score', 0) or 0)
                scores.append(score)
                if score > example_score:
                    example_score = score
                    example_statement = str(st.get('statement_text') or '')[:300]
                if risk.get('notes'):
                    notes.add(str(risk['notes']))
            if scores:
                max_score = max(scores)
                avg_score = round(sum(scores) / len(scores), 1)
                total_raw_risk = sum(scores)
                if max_score <= 0 or global_max <= 1:
                    relative = 1
                else:
                    import math

                    relative = max(1, int((math.log(max_score) / math.log(global_max)) * 100))
            else:
                max_score = 0
                avg_score = 0
                total_raw_risk = 0
                relative = 0

            rows.append(
                {
                    'Policy Path': self._policy_path(policy_obj=policy_by_ocid.get(policy_ocid)),
                    'Total Statements': len(statements),
                    'Max Score': max_score,
                    'Avg Score': avg_score,
                    'Max Statement Risk (Global %)': relative,
                    'Total Raw Risk': total_raw_risk,
                    'Risk Summary/Notes': '; '.join(sorted(notes))[:500],
                    'Example Statement': example_statement,
                }
            )
        rows.sort(key=lambda r: int(r.get('Max Statement Risk (Global %)', 0)), reverse=True)
        return rows

    def _cleanup_rows(self) -> list[dict[str, Any]]:
        """Build cleanup issue rows from overlay cleanup buckets.

        Returns:
            list[dict[str, Any]]: Cleanup issue rows for display.
        """
        overlay = getattr(self.context.intelligence, 'overlay', {}) or {}
        cleanup = overlay.get('cleanup_items', {}) or {}
        rows: list[dict[str, Any]] = []

        for item in cleanup.get('invalid_statements', []) or []:
            rows.append(
                {
                    'Type': 'Invalid Statement',
                    'Name': (item.get('statement_text') or '[unknown statement]')[:200],
                    'Reason': '; '.join(item.get('invalid_reasons', []) or []) or 'Failed validation',
                    'Action': 'Fix invalid statement or resolve identity/reference issues.',
                }
            )
        for group in cleanup.get('unused_groups', []) or []:
            rows.append(
                {
                    'Type': 'Group w/ No Users',
                    'Name': f"{group.get('domain_name', 'Default')}/{group.get('group_name', '[unknown]')}",
                    'Reason': 'Group has zero user members.',
                    'Action': 'Remove, repurpose, or assign users.',
                }
            )
        for dg in cleanup.get('unused_dynamic_groups', []) or []:
            rows.append(
                {
                    'Type': 'Unused Dynamic Group',
                    'Name': f"{dg.get('domain_name', 'Default')}/{dg.get('dynamic_group_name', '[unknown]')}",
                    'Reason': 'Not referenced by any policy statement.',
                    'Action': 'Delete dynamic group or document why kept.',
                }
            )
        for st in cleanup.get('statements_too_open', []) or []:
            rows.append(
                {
                    'Type': 'Overly Broad Statement',
                    'Name': (st.get('statement_text') or '[unknown statement]')[:200],
                    **overly_broad_statement_guidance(st),
                }
            )
        for st in cleanup.get('anyuser_no_where', []) or []:
            rows.append(
                {
                    'Type': 'Any-user Without Where',
                    'Name': (st.get('statement_text') or '[unknown statement]')[:200],
                    'Reason': 'Statement grants access to any-user with no where clause.',
                    'Action': 'Limit subject with a concise where clause.',
                }
            )
        return rows

    def _limits_rows(self) -> list[dict[str, Any]]:
        """Build limits rows with status and recommendation.

        Returns:
            list[dict[str, Any]]: Compartment statement limit rows.
        """
        repo = self.context.policy_repo
        rows: list[dict[str, Any]] = []
        limits = getattr(repo, 'tenancy_policy_limits', {}) or {}
        try:
            chain_limit = int(limits.get('policy_statements_per_compartment_chain_count') or 0)
            chain_limit = chain_limit if chain_limit > 0 else None
        except (TypeError, ValueError):
            chain_limit = None
        near_limit = int(chain_limit * self.NEARING_THRESHOLD) if chain_limit else None
        for comp in getattr(repo, 'compartments', []) or []:
            cumulative = int(comp.get('statement_count_cumulative', 0) or 0)
            direct = int(comp.get('statement_count_direct', 0) or 0)
            if not chain_limit:
                status = 'Limit Not Supplied'
                rec = 'Enter policy-statements-per-compartment-chain-count in Policy Browser to assess this hierarchy.'
            elif cumulative > chain_limit:
                status = 'Over Limit'
                rec = 'Reduce or consolidate policy statements in this hierarchy to avoid enforcement errors.'
            elif near_limit is not None and cumulative >= near_limit:
                status = 'Nearing Limit'
                rec = 'Proactively clean up or consolidate policies to stay under the statement limit.'
            else:
                status = 'OK'
                rec = ''
            rows.append(
                {
                    'Compartment Hierarchy Path': comp.get('hierarchy_path') or '',
                    'Direct Statements': direct,
                    'Cumulative Statements': cumulative,
                    'Status': status,
                    'Recommendation': rec,
                }
            )
        rows.sort(key=lambda r: int(r.get('Cumulative Statements', 0)), reverse=True)
        return rows
