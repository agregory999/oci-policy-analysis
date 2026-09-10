"""Service facade for consolidation workbench workflows.

This module centralizes consolidation workbench orchestration so web and Tkinter
consumers can gradually converge on shared service logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.common.consolidation_helpers import resolve_policy_compartment_path
from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine
from oci_policy_analysis.application.core.models.models_consolidation import (
    ConsolidationPlan,
    ProtectedStatementReference,
    ProtectedStatementSet,
)
from oci_policy_analysis.application.core.support.logger import get_logger

LOCKED_POLICY_NAME = 'Tenant Admin Policy'


class ConsolidationWorkbenchService:
    """Provide consolidation workbench operations independent from UI frameworks.

    Args:
        context: Shared application context containing repositories, cache, and engines.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the consolidation workbench service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.repo = context.policy_repo
        self.cache = context.cache
        self.logger = get_logger(component='application.services.consolidation_workbench')
        self.engine = ConsolidationEngine(
            cache_mgr=context.cache,
            reference_data_repo=context.reference_data,
            policy_repo=context.policy_repo,
        )
        self.logger.debug(
            'Initialized ConsolidationWorkbenchService for tenancy=%s', getattr(self.repo, 'tenancy_ocid', None)
        )

    def _reload_live_policy_data_if_allowed(self) -> dict[str, Any]:
        """Reload only policy/compartment data when source is a live tenancy.

        Returns:
            dict[str, Any]: Reload result metadata with status and message.
                status is one of: success, failure, noop.
        """
        if not (
            getattr(self.repo, 'policies_loaded_from_tenancy', False)
            and not getattr(self.repo, 'loaded_from_compliance_output', False)
        ):
            return {
                'reload_status': 'noop',
                'message': 'Reload skipped: dataset was not loaded live from tenancy.',
            }

        if not hasattr(self.repo, 'reload_compartment_policy_data'):
            return {
                'reload_status': 'failure',
                'message': 'Reload failed: repository does not support policy-only reload.',
            }

        try:
            reload_ok = bool(self.repo.reload_compartment_policy_data())
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error('Live policy reload failed before progress check: %s', exc, exc_info=True)
            return {
                'reload_status': 'failure',
                'message': f'Reload failed: {exc}',
            }

        if not reload_ok:
            return {
                'reload_status': 'failure',
                'message': 'Reload failed: policy/compartment refresh did not complete successfully.',
            }

        return {
            'reload_status': 'success',
            'message': 'Reload succeeded: live tenancy policy data refreshed.',
        }

    def get_status(self) -> dict[str, Any]:
        """Return consolidation status and capability flags for the current dataset.

        Returns:
            dict[str, Any]: Status payload with tenancy info, source flags, and strategies.
        """
        status = {
            'tenancy_ocid': getattr(self.repo, 'tenancy_ocid', None),
            'loaded_from_compliance_output': bool(getattr(self.repo, 'loaded_from_compliance_output', False)),
            'policies_loaded_from_tenancy': bool(getattr(self.repo, 'policies_loaded_from_tenancy', False)),
            'can_check_progress': bool(
                getattr(self.repo, 'policies_loaded_from_tenancy', False)
                and not getattr(self.repo, 'loaded_from_compliance_output', False)
            ),
            'strategy_names': self.engine.get_strategy_display_names(),
        }
        self.logger.info(
            'Consolidation status requested: tenancy=%s can_check_progress=%s strategies=%s',
            status.get('tenancy_ocid'),
            status.get('can_check_progress'),
            len(status.get('strategy_names') or []),
        )
        return status

    def get_protection_rows(self) -> list[dict[str, Any]]:
        """Build protection browser rows from regular statements.

        Returns:
            list[dict[str, Any]]: Protection row payloads for table rendering.
        """
        rows: list[dict[str, Any]] = []
        for st in getattr(self.repo, 'regular_statements', []) or []:
            rows.append(
                {
                    'policy_name': st.get('policy_name', ''),
                    'policy_ocid': st.get('policy_ocid', ''),
                    'compartment_ocid': st.get('compartment_ocid', ''),
                    'compartment_path': st.get('compartment_path', ''),
                    'statement_text': st.get('statement_text', ''),
                    'location': st.get('location', ''),
                    'effective_path': st.get('effective_path', ''),
                    'statement_effective_path': st.get('effective_path', ''),
                    'principal': st.get('subject_type', ''),
                    'internal_id': st.get('internal_id', ''),
                }
            )
        return rows

    def get_protected_set(self) -> dict[str, Any]:
        """Load the protected statement set for the active tenancy.

        Returns:
            dict[str, Any]: Protected set payload, or empty dict when tenancy is unavailable.
        """
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            self.logger.info('get_protected_set called without an active tenancy')
            return {}
        return self.cache.get_protected_set(tenancy_ocid)

    def set_protected_set(self, internal_ids: list[str]) -> dict[str, Any]:
        """Persist protected statement IDs as a canonical protected set.

        Args:
            internal_ids: Selected statement internal IDs to mark as protected.

        Returns:
            dict[str, Any]: Persisted protected-set payload.

        Raises:
            ValueError: If no tenancy is currently loaded.
        """
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            self.logger.warning('set_protected_set called without an active tenancy')
            raise ValueError('No tenancy is currently loaded.')
        selected = set(internal_ids)
        refs: list[ProtectedStatementReference] = []
        for row in self.get_protection_rows():
            iid = row.get('internal_id', '')
            if iid and iid in selected:
                refs.append(
                    {
                        'internal_id': iid,
                        'policy_ocid': row.get('policy_ocid', ''),
                        'policy_name': row.get('policy_name', ''),
                        'statement_text': row.get('statement_text', ''),
                    }
                )
        payload: ProtectedStatementSet = {'tenancy_ocid': tenancy_ocid, 'protected': refs}
        self.cache.set_protected_set(tenancy_ocid, cast(dict[str, Any], payload))
        self.logger.info('Persisted protected set: tenancy=%s protected_count=%s', tenancy_ocid, len(refs))
        return cast(dict[str, Any], payload)

    def get_candidate_rows(self, search: str = '') -> dict[str, Any]:
        """Return candidate rows and exclusion counts.

        Args:
            search: Optional free-text filter against policy name and statement text.

        Returns:
            dict[str, Any]: Candidate rows and counts for protected/invalid/system exclusions.
        """
        protected = {
            ref.get('internal_id')
            for ref in (self.get_protected_set().get('protected') or [])
            if isinstance(ref, dict) and ref.get('internal_id')
        }
        invalid = {
            st.get('internal_id')
            for st in getattr(self.repo, 'regular_statements', []) or []
            if st.get('internal_id') and st.get('invalid_reasons')
        }
        system = {
            st.get('internal_id')
            for st in getattr(self.repo, 'regular_statements', []) or []
            if st.get('internal_id') and (st.get('policy_name') or '').strip() == LOCKED_POLICY_NAME
        }
        needle = (search or '').strip().lower()
        rows: list[dict[str, Any]] = []
        for st in getattr(self.repo, 'regular_statements', []) or []:
            iid = st.get('internal_id', '')
            if not iid or iid in protected or iid in invalid or iid in system:
                continue
            p = (st.get('policy_name') or '').lower()
            t = (st.get('statement_text') or '').lower()
            if needle and needle not in p and needle not in t:
                continue
            rows.append(
                {
                    'policy_name': st.get('policy_name', ''),
                    'statement_text': st.get('statement_text', ''),
                    'statement_compartment_path': st.get('compartment_path', ''),
                    'statement_location': st.get('location', ''),
                    'statement_effective_path': st.get('effective_path', ''),
                    'principal': st.get('subject_type', ''),
                    'resource': st.get('resource', ''),
                    'internal_id': iid,
                }
            )
        return {
            'rows': rows,
            'counts': {'protected': len(protected), 'invalid': len(invalid), 'system': len(system)},
        }

    def create_proposal(self, candidate_internal_ids: list[str], strategy_display_name: str) -> dict[str, Any]:
        """Generate and persist a consolidation proposal.

        Args:
            candidate_internal_ids: Candidate statement internal IDs selected for consolidation.
            strategy_display_name: Strategy display name selected by the user.

        Returns:
            dict[str, Any]: Generated plan and UI-oriented proposal rows.
        """
        self.logger.info(
            'Generating consolidation proposal: candidates=%s strategy=%s',
            len(candidate_internal_ids),
            strategy_display_name,
        )
        protected_ids = {
            str(ref.get('internal_id'))
            for ref in (self.get_protected_set().get('protected') or [])
            if isinstance(ref, dict) and ref.get('internal_id')
        }
        plan = self.engine.generate_plan(
            candidate_internal_ids=set(candidate_internal_ids),
            protected_internal_ids=set(protected_ids),
            strategy_display_name=strategy_display_name,
            params={'marker_tag_key': 'opa_consolidation'},
        )
        rows = self.get_proposal_rows(plan=cast(ConsolidationPlan, plan), progress=None)
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if tenancy_ocid:
            now = datetime.now(UTC).isoformat()
            self.cache.add_run_record(
                tenancy_ocid,
                {
                    'consolidation_effort_id': plan.get('plan_id', '<unknown>'),
                    'created_at': now,
                    'status': 'in_progress',
                    'candidate_statements': list(candidate_internal_ids),
                    'strategy': plan.get('plan_tags', {}).get('strategy_id', ''),
                    'step_status': {'proposal': {'status': 'completed', 'generated_at': now}},
                    'results': rows,
                    'plan': plan,
                },
            )
        else:
            self.logger.warning('Proposal generated without tenancy_ocid; run history was not persisted')
        self.logger.info(
            'Generated consolidation proposal: plan_id=%s step_count=%s',
            plan.get('plan_id', '<unknown>'),
            len(plan.get('plan_steps', []) or []),
        )
        return {'plan': plan, 'rows': rows}

    def get_history(self) -> list[dict[str, Any]]:
        """Return run history rows with validity metadata.

        Returns:
            list[dict[str, Any]]: Sorted history rows with execution and conflict summary.
        """
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            return []
        history = self.cache.get_history(tenancy_ocid)
        out: list[dict[str, Any]] = []
        for run in sorted(history, key=lambda r: r.get('created_at', ''), reverse=True):
            plan = run.get('plan') or {}
            progress = (run.get('step_status') or {}).get('progress') or {}
            steps = plan.get('plan_steps') or []
            executed = sum(1 for p in progress.values() if p.get('executed')) if isinstance(progress, dict) else 0
            conflicts = self.get_conflict_analysis(cast(ConsolidationPlan, plan), run.get('status', 'in_progress'))
            validity = (
                f'Conflicted ({conflicts["conflict_count"]})'
                if conflicts['status'] == 'Conflicted'
                else conflicts['status']
            )
            out.append(
                {
                    'effort_id': run.get('consolidation_effort_id', ''),
                    'created_at': run.get('created_at', ''),
                    'strategy': run.get('strategy', ''),
                    'status': run.get('status', 'in_progress'),
                    'steps': len(steps),
                    'executed_steps': executed,
                    'validity': validity,
                }
            )
        return out

    def get_history_run(self, effort_id: str) -> dict[str, Any] | None:
        """Return a specific run record by effort ID.

        Args:
            effort_id: Consolidation effort identifier.

        Returns:
            dict[str, Any] | None: Run record when found, otherwise None.
        """
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            return None
        history = self.cache.get_history(tenancy_ocid)
        return next((r for r in history if r.get('consolidation_effort_id') == effort_id), None)

    def get_history_run_detail(self, effort_id: str) -> dict[str, Any] | None:
        """Return one run with explicit conflict-analysis metadata."""
        run = self.get_history_run(effort_id)
        if not run:
            return None
        plan = cast(ConsolidationPlan, run.get('plan') or {})
        progress = (run.get('step_status') or {}).get('progress') or {}
        return {
            'run': run,
            'proposal_rows': self.get_proposal_rows(plan, progress, run.get('results') or []),
            'conflict_analysis': self.get_conflict_analysis(plan, run.get('status', 'in_progress')),
        }

    def get_conflict_analysis(self, plan: ConsolidationPlan | None, status: str = 'in_progress') -> dict[str, Any]:
        """Return the canonical conflict status for a plan without UI-specific handling."""
        if not plan or not plan.get('plan_steps'):
            return {
                'rule': 'A plan is conflicted when a policy marker belongs to another plan.',
                'status': '—',
                'conflicts': [],
                'conflict_count': 0,
            }
        conflicts = [] if status == 'completed' else self.engine.get_plan_tag_conflicts(plan)
        return {
            'rule': 'A plan is conflicted when one or more policies in this plan currently have an opa_consolidation marker tag value that points to a different plan_id.',
            'status': '—' if status == 'completed' else ('Conflicted' if conflicts else 'OK'),
            'conflicts': conflicts,
            'conflict_count': len(conflicts),
        }

    def delete_history_run(self, effort_id: str) -> bool:
        """Delete one history run for the active tenancy."""
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            return False
        return bool(self.cache.remove_run_record(tenancy_ocid, effort_id))

    def save_plan_notes(self, effort_id: str, notes: str) -> bool:
        """Save plan notes for a run record.

        Args:
            effort_id: Consolidation effort identifier.
            notes: Notes text to persist into the plan object.

        Returns:
            bool: True when update succeeded; otherwise False.
        """
        run = self.get_history_run(effort_id)
        if not run:
            return False
        plan = run.get('plan') or {}
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            return False
        updated_plan = {**plan, 'notes': notes}
        return bool(self.cache.update_run_record(tenancy_ocid, effort_id, {'plan': updated_plan}))

    def render_script(self, effort_id: str, fmt: str, section: str) -> str:
        """Render execution/rollback script text for a run.

        Args:
            effort_id: Consolidation effort identifier.
            fmt: Output format (`cli` or `ui`).
            section: Requested section (`execution`, `rollback`, or `both`).

        Returns:
            str: Rendered script text.
        """
        run = self.get_history_run(effort_id)
        if not run or not run.get('plan'):
            return '(no plan selected)'
        return self.render_plan(cast(ConsolidationPlan, run['plan']), fmt=fmt, section=section, effort_id=effort_id)

    def render_plan(self, plan: ConsolidationPlan, fmt: str, section: str, effort_id: str = '') -> str:
        """Render a plan for either client, including a summary when it is persisted."""
        summary = self._render_plan_summary_block(plan, effort_id) if effort_id else ''
        if fmt == 'ui':
            sec = 'execution' if section == 'execution' else ('rollback' if section == 'rollback' else 'all')
            body = self.engine.render_plan_ui_instructions(plan, section=sec)
            return f'{summary}\n\n{body}'.strip()
        cmd_txt = self.engine.render_plan_commands(plan)
        rollback_txt = self.engine.render_plan_rollback_commands(plan)
        if section == 'execution':
            return f'{summary}\n\n{cmd_txt}'.strip()
        if section == 'rollback':
            return f'{summary}\n\n{rollback_txt}'.strip()
        return f'{summary}\n\n{cmd_txt}\n\n{rollback_txt}'.strip()

    def evaluate_progress(self, plan: ConsolidationPlan) -> dict[str, Any]:
        """Evaluate a plan against the currently loaded repository state."""
        return self.engine.check_plan_progress(plan)

    def check_progress(self, effort_id: str) -> dict[str, Any]:
        """Check plan progress using current repository state and marker tags.

        Args:
            effort_id: Consolidation effort identifier.

        Returns:
            dict[str, Any]: Progress map and execution counts.

        Raises:
            ValueError: If plan is missing or dataset source is not live tenancy.
        """
        run = self.get_history_run(effort_id)
        if not run or not run.get('plan'):
            self.logger.warning('check_progress requested for unknown plan: effort_id=%s', effort_id)
            raise ValueError('Plan not found.')
        reload_result = self._reload_live_policy_data_if_allowed()
        reload_status = str(reload_result.get('reload_status') or 'noop')
        reload_message = str(reload_result.get('message') or '')

        if reload_status == 'failure':
            self.logger.warning('check_progress reload failed for effort_id=%s: %s', effort_id, reload_message)
            raise ValueError(reload_message or 'Policy data reload failed before progress check.')

        if reload_status == 'noop':
            plan_steps = (run.get('plan') or {}).get('plan_steps') or []
            total = len(plan_steps)
            stored_progress = ((run.get('step_status') or {}).get('progress') or {}) if isinstance(run, dict) else {}
            executed = (
                sum(1 for p in stored_progress.values() if isinstance(p, dict) and p.get('executed'))
                if isinstance(stored_progress, dict)
                else 0
            )
            self.logger.info('check_progress no-op for non-live dataset: effort_id=%s', effort_id)
            return {
                'progress': stored_progress if isinstance(stored_progress, dict) else {},
                'executed': executed,
                'total': total,
                'reload_status': 'noop',
                'message': reload_message
                or 'No-op: progress check requires live tenancy load; showing last known persisted progress.',
                'completed': bool(total > 0 and executed >= total),
            }

        progress = self.evaluate_progress(cast(ConsolidationPlan, run['plan']))
        total = len(progress)
        executed = sum(1 for p in progress.values() if p.get('executed'))
        self.save_progress(effort_id, progress)
        self.logger.info(
            'Checked consolidation progress: effort_id=%s executed=%s total=%s', effort_id, executed, total
        )
        return {
            'progress': progress,
            'executed': executed,
            'total': total,
            'reload_status': 'success',
            'message': reload_message or 'Reload and progress check completed successfully.',
            'completed': bool(total > 0 and executed >= total),
        }

    def save_progress(self, effort_id: str, progress: dict[str, Any]) -> dict[str, Any]:
        """Persist plan progress and return refreshed proposal rows.

        This is used when a presentation layer has already performed a live
        reload and only needs the common persistence/rendering behavior.
        """
        run = self.get_history_run(effort_id)
        if not run or not run.get('plan'):
            raise ValueError('Plan not found.')
        plan = cast(ConsolidationPlan, run['plan'])
        total = len(plan.get('plan_steps') or [])
        executed = sum(1 for item in progress.values() if isinstance(item, dict) and item.get('executed'))
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        rows = self.get_proposal_rows(plan=plan, progress=progress)
        if tenancy_ocid:
            updates: dict[str, Any] = {
                'step_status': {**(run.get('step_status') or {}), 'progress': progress},
                'results': rows,
            }
            if total > 0 and executed >= total:
                updates['status'] = 'completed'
                updates['completed_at'] = datetime.now(UTC).isoformat()
            self.cache.update_run_record(tenancy_ocid, effort_id, updates)
        return {'rows': rows, 'executed': executed, 'total': total, 'completed': bool(total and executed >= total)}

    def _render_plan_summary_block(self, plan: ConsolidationPlan, effort_id: str) -> str:
        """Build a compact summary block for script/instructions output."""
        steps = plan.get('plan_steps') or []
        rows = self.get_proposal_rows(plan=plan, progress=None)
        lines = [
            '# Consolidation Plan Summary',
            f'# Effort ID: {effort_id}',
            f'# Plan ID: {plan.get("plan_id", effort_id)}',
            f'# Strategy: {(plan.get("plan_tags") or {}).get("strategy_id", "")}',
            f'# Steps: {len(steps)}',
            '#',
            '# Step Outline:',
        ]
        for r in rows:
            lines.append(
                f'#   {r.get("index", "?")}. {r.get("action", "")} | {r.get("policy_name", "")} | {r.get("details", "")}'
            )
        return '\n'.join(lines)

    def reset_for_tenancy(self) -> dict[str, Any]:
        """Reset consolidation state (protection + history) for active tenancy.

        Returns:
            dict[str, Any]: Summary including cleared history count.

        Raises:
            ValueError: If no tenancy is currently loaded.
        """
        tenancy_ocid = str(getattr(self.repo, 'tenancy_ocid', '') or '')
        if not tenancy_ocid:
            self.logger.warning('reset_for_tenancy called without an active tenancy')
            raise ValueError('No tenancy is currently loaded.')
        previous = self.cache.get_or_create_consolidation_state(tenancy_ocid)
        history_count = len(previous.get('history', []) if isinstance(previous, dict) else [])
        self.cache.save_consolidation_state(tenancy_ocid, {'protected_set': {}, 'history': []})
        self.logger.info(
            'Reset consolidation state for tenancy=%s cleared_history_records=%s', tenancy_ocid, history_count
        )
        return {'tenancy_ocid': tenancy_ocid, 'cleared_history_records': history_count}

    def _proposal_compartment_display(self, value: str) -> str:
        """Resolve compartment IDs for display, preserving paths and unknown IDs."""
        if not value:
            return ''
        path = resolve_policy_compartment_path(
            cast(Any, {'compartment_ocid': value}), getattr(self.repo, 'compartments', []) or []
        )
        if path:
            return path
        if value == getattr(self.repo, 'tenancy_ocid', None):
            return 'ROOT'
        return value

    def get_proposal_rows(
        self,
        plan: ConsolidationPlan | None,
        progress: dict[str, Any] | None = None,
        results_fallback: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build UI-oriented proposal rows from plan steps.

        Args:
            plan: Consolidation plan payload.
            progress: Optional progress map keyed by step ID.

        Returns:
            list[dict[str, Any]]: Proposal rows for workbench display.
        """
        # Private helper: convert plan model to flattened row payloads used by table UI.
        if not plan or not plan.get('plan_steps'):
            rows: list[dict[str, Any]] = []
            for index, row in enumerate(results_fallback or [], 1):
                normalized = {
                    **row,
                    'index': row.get('index', row.get('#', index)),
                    'action': row.get('action', row.get('Action', '')),
                    'policy_compartment': self._proposal_compartment_display(
                        row.get('policy_compartment')
                        or row.get('Policy Compartment')
                        or row.get('compartment_ocid', '')
                    ),
                    'policy_name': row.get('policy_name', row.get('Policy Name', '')),
                    'details': row.get('details', row.get('Details', '')),
                    'status': row.get('status', row.get('Status', '—')),
                }
                normalized.update(
                    {
                        '#': normalized['index'],
                        'Action': normalized['action'],
                        'Policy Compartment': normalized['policy_compartment'],
                        'Policy Name': normalized['policy_name'],
                        'Details': normalized['details'],
                        'Status': normalized['status'],
                    }
                )
                rows.append(normalized)
            return rows
        policies_by_ocid = {
            p.get('policy_ocid'): p for p in (getattr(self.repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        rows: list[dict[str, Any]] = []
        for i, step in enumerate(plan.get('plan_steps', []), 1):
            action_key = step.get('action', '')
            pol = policies_by_ocid.get(step.get('policy_ocid', ''), {}) or {}
            if action_key == 'add':
                pol_name = (step.get('create_policy_name') or 'Consolidated-Root') + ' (suggested)'
                policy_compartment = self._proposal_compartment_display(step.get('compartment_ocid', '')) or 'ROOT'
                details = f'New Policy with {len(step.get("after_statements", []))} statements'
            else:
                pol_name = pol.get('policy_name') or step.get('create_policy_name') or '(unknown policy)'
                policy_compartment = self._proposal_compartment_display(
                    pol.get('compartment_path') or pol.get('compartment_ocid') or step.get('compartment_ocid', '')
                )
                if action_key == 'modify':
                    details = f'Statements: {len(step.get("before_statements", []))} -> {len(step.get("after_statements", []))}'
                elif action_key == 'delete':
                    details = (
                        f'Delete policy (rollback recreates with {len(step.get("before_statements", []))} statements)'
                    )
                else:
                    details = ''
            status = 'Pending'
            if isinstance(progress, dict):
                info = progress.get(step.get('step_id'), {})
                status = 'Executed' if info.get('executed') else 'Pending'
            action_display = (action_key or '').upper()
            # Canonical proposal-row schema (snake_case) used by service/web/Tk.
            # Keep legacy display keys for backward compatibility with historical runs.
            rows.append(
                {
                    'index': i,
                    'action_key': action_key,
                    'action': action_display,
                    'policy_compartment': policy_compartment,
                    'policy_name': pol_name,
                    'details': details,
                    'status': status,
                    'step_id': step.get('step_id', ''),
                    'policy_ocid': step.get('policy_ocid', ''),
                    'before_statements': step.get('before_statements', []) or [],
                    'after_statements': step.get('after_statements', []) or [],
                    'compartment_ocid': step.get('compartment_ocid', ''),
                    # Back-compat aliases (legacy UI/web/Tk history payloads)
                    '#': i,
                    'Action': action_display,
                    'Policy Compartment': policy_compartment,
                    'Policy Name': pol_name,
                    'Details': details,
                    'Status': status,
                }
            )
        return rows
