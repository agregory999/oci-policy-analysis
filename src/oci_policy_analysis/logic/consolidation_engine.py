##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_engine.py
#
# Middle tier for the Consolidation Workbench:
# - Owns session/plan state (per-tenancy)
# - Generates consolidation plans using pluggable strategies
# - Renders execution + rollback command text for administrators
# - Validates execution progress after reload by inspecting policy tags / policy presence
#
# @author: Andrew Gregory
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy
from oci_policy_analysis.common.models_consolidation import ConsolidationPlan
from oci_policy_analysis.logic.consolidation_helpers import flatten_defined_tags, now_iso, policy_tag_maps
from oci_policy_analysis.logic.consolidation_strategies import Strategy
from oci_policy_analysis.logic.consolidation_strategies.move_closer_to_target import MoveCloserToTargetCompartment
from oci_policy_analysis.logic.consolidation_strategies.move_into_target import MoveIntoTargetCompartment
from oci_policy_analysis.logic.consolidation_strategies.move_to_root import MoveToRootCompartment
from oci_policy_analysis.logic.consolidation_strategies.statement_density import PackPoliciesByStatementDensity
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo

logger = get_logger(component='consolidation_engine')

SourceType = Literal['live', 'cache', 'compliance', 'unknown']

# Aliases for render code (helpers live in consolidation_helpers; engine keeps shell/JSON helpers only).
_policy_tag_maps = policy_tag_maps
_flatten_defined_tags = flatten_defined_tags


def _json_compact(obj: object) -> str:
    """Safe JSON dump for CLI snippets."""
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), default=str)


def _shell_escape_single_quoted(s: str) -> str:
    """
    Escape a string for use inside a single-quoted shell literal.
    In single-quoted bash, the only escape is '' (end quote, escaped single quote, new quote).
    """
    return s.replace("'", "'\"'\"'")


def _shell_escape_double_quoted(s: str) -> str:
    """
    Escape a string for use inside a double-quoted shell argument.
    Escapes backslash, double quote, and single quote so statements like
    allow group 'Federated'/'group' and JSON structure are safe.
    """
    return s.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")


def _statements_cli_value(statements: list) -> str:
    """
    JSON array of statement strings, escaped for embedding in a double-quoted
    shell argument. Caller wraps result in double quotes: --statements \"...\"
    """
    raw = _json_compact(statements if statements is not None else [])
    return _shell_escape_double_quoted(raw)


class ConsolidationEngine:
    """
    Middle-tier consolidation engine.

    Instantiated early (UI startup) with cache and reference data. A PolicyAnalysisRepository
    is bound via :meth:`bind_policy_repo` once the App creates it; the repository is populated
    later via tenancy load or cache load.
    """

    def __init__(
        self,
        *,
        cache_mgr: CacheManager,
        reference_data_repo: ReferenceDataRepo,
        policy_repo: PolicyAnalysisRepository | None = None,
        strategies: list[Strategy] | None = None,
    ):
        """Initialize the consolidation engine.

        Args:
            cache_mgr: Cache manager for plan history and protected sets.
            reference_data_repo: Reference data repository (e.g. for strategy lookups).
            policy_repo: Optional policy repository; can be bound later with bind_policy_repo.
            strategies: Optional list of Strategy implementations. If None, uses built-in default(s).
        """
        self.cache_mgr = cache_mgr
        self.reference_data_repo = reference_data_repo
        self.policy_repo = policy_repo

        # Pluggable strategies: use provided list or default built-in(s).
        strategies = (
            strategies
            if strategies is not None
            else [
                PackPoliciesByStatementDensity(),
                MoveToRootCompartment(),
                MoveCloserToTargetCompartment(),
                MoveIntoTargetCompartment(),
            ]
        )
        self._strategies: dict[str, Strategy] = {}
        self._strategies_by_id: dict[str, Strategy] = {}
        for s in strategies:
            self._strategies[s.display_name] = s
            self._strategies_by_id[s.strategy_id] = s
        logger.info(
            'ConsolidationEngine initialized with strategies: %s',
            list(self._strategies.keys()),
        )

    def register_strategy(self, strategy: Strategy) -> None:
        """Register a single consolidation strategy (pluggable).

        Args:
            strategy: Strategy instance implementing the Strategy protocol.
        """
        self._strategies[strategy.display_name] = strategy
        self._strategies_by_id[strategy.strategy_id] = strategy
        logger.debug('Registered consolidation strategy: %s', strategy.display_name)

    def register_strategies(self, strategies: list[Strategy]) -> None:
        """Register multiple consolidation strategies.

        Args:
            strategies: List of Strategy instances.
        """
        for s in strategies:
            self.register_strategy(s)

    def get_strategy_display_names(self) -> list[str]:
        """Return display names of all registered strategies (for UI dropdown, etc.).

        Returns:
            List of display_name strings in registration order (insertion order).
        """
        # Preserve order; dict is insertion-ordered in Python 3.7+
        return list(self._strategies.keys())

    def bind_policy_repo(self, repo: PolicyAnalysisRepository) -> None:
        """Attach the policy repository used for plan generation and rendering.

        Args:
            repo: The policy/compartment repository (e.g. policy_compartment_analysis).
        """
        self.policy_repo = repo

    def detect_source_type(self) -> SourceType:
        """Detect whether repo data is from live tenancy, cache, or compliance output.

        Returns:
            One of "live", "cache", "compliance", or "unknown".
        """
        repo = self.policy_repo
        if not repo:
            return 'unknown'
        if getattr(repo, 'loaded_from_compliance_output', False):
            return 'compliance'
        if getattr(repo, 'policies_loaded_from_tenancy', False) and getattr(
            repo, 'identity_loaded_from_tenancy', False
        ):
            return 'live'
        # cache loads tend to set data_as_of and tenancy_ocid but not the *_loaded_from_tenancy flags
        if getattr(repo, 'data_as_of', None):
            return 'cache'
        return 'unknown'

    def tenancy_ocid(self) -> str | None:
        """Return tenancy OCID from the bound repo.

        Returns:
            Tenancy OCID string if repo is bound and has tenancy_ocid, else None.
        """
        repo = self.policy_repo
        if repo and getattr(repo, 'tenancy_ocid', None):
            return str(repo.tenancy_ocid)
        return None

    def dataset_version(self) -> str | None:
        """Return dataset version or data_as_of from the bound repo.

        Returns:
            Version string (e.g. timestamp) if repo has data_as_of, else None.
        """
        repo = self.policy_repo
        if repo and getattr(repo, 'data_as_of', None):
            return str(repo.data_as_of)
        return None

    # ---- Plan Generation ----

    def generate_plan(
        self,
        *,
        candidate_internal_ids: set[str],
        protected_internal_ids: set[str],
        strategy_display_name: str,
        params: dict[str, object] | None = None,
    ) -> ConsolidationPlan:
        """Build a consolidation plan for the given candidates and strategy.

        Args:
            candidate_internal_ids: Set of statement internal_ids to consolidate.
            protected_internal_ids: Set of statement internal_ids to exclude from consolidation.
            strategy_display_name: Display name of the strategy (e.g. "Statement Density (Pack Policies)").
            params: Optional strategy params (e.g. marker_tag_key).

        Returns:
            A ConsolidationPlan with plan_id, plan_steps, and plan_tags.

        Raises:
            RuntimeError: If policy repo is not bound or tenancy_ocid is missing.
            ValueError: If strategy_display_name does not match any registered strategy.
        """
        if not self.policy_repo:
            raise RuntimeError('Policy repository not bound.')
        tenancy_ocid = self.tenancy_ocid()
        if not tenancy_ocid:
            raise RuntimeError('No tenancy_ocid available.')
        source_type = self.detect_source_type()
        plan_id = self._new_plan_id(tenancy_ocid, candidate_internal_ids, strategy_display_name)

        logger.info(
            'Generating consolidation plan: tenancy_ocid=%s, source_type=%s, strategy=%s, candidates=%d, protected=%d, plan_id=%s',
            tenancy_ocid,
            source_type,
            strategy_display_name,
            len(candidate_internal_ids),
            len(protected_internal_ids),
            plan_id,
        )

        # Resolve strategy name in a robust way:
        strat = self._strategies.get(strategy_display_name)
        if not strat:
            # Match by internal id or prefix (e.g. "Statement Density")
            strat = self._strategies_by_id.get(strategy_display_name)
        if not strat:
            for candidate in self._strategies.values():
                base_label = candidate.display_name.split(' (', 1)[0].strip().lower()
                if strategy_display_name.strip().lower().startswith(base_label):
                    strat = candidate
                    logger.info(
                        "Resolved strategy display name '%s' to '%s' (id=%s)",
                        strategy_display_name,
                        candidate.display_name,
                        candidate.strategy_id,
                    )
                    break
        if not strat:
            logger.warning(
                "Unknown strategy '%s'. Available display names: %s",
                strategy_display_name,
                list(self._strategies.keys()),
            )
            raise ValueError(f'Unknown strategy: {strategy_display_name}')

        plan = strat.build_plan(
            repo=self.policy_repo,
            tenancy_ocid=tenancy_ocid,
            dataset_version=self.dataset_version(),
            candidate_internal_ids=set(candidate_internal_ids),
            protected_internal_ids=set(protected_internal_ids),
            plan_id=plan_id,
            params=params,
        )
        logger.info(
            'generate_plan: strategy returned plan_id=%s, steps=%d, label=%s',
            plan.get('plan_id'),
            len(plan.get('plan_steps', [])),
            plan.get('plan_label', ''),
        )
        return plan

    def _new_plan_id(self, tenancy_ocid: str, candidate_ids: set[str], strategy: str) -> str:
        """Generate a stable-ish plan id from tenancy suffix, timestamp, and strategy hash."""
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        return f'{tenancy_ocid[-6:]}-{ts}-{abs(hash(strategy)) % 10000:04d}'

    # ---- Rendering (execution + rollback) ----

    def render_plan_commands(self, plan: ConsolidationPlan) -> str:
        """Render CLI-oriented execution steps for the plan (no rollback hints).

        Produces shell commands (oci iam policy update/delete) for administrators to run
        manually. Rollback hints for delete steps appear only in the rollback section
        (see render_plan_rollback_commands). The tool does not execute these commands.

        Args:
            plan: The consolidation plan to render.

        Returns:
            Multiline string of commented and executable CLI lines, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        lines: list[str] = []
        lines.append(f"# Consolidation plan: {plan.get('plan_id')} | {plan.get('plan_label')}")
        lines.append(
            f"# Tenancy: {plan.get('tenancy_ocid')} | Dataset: {self.dataset_version() or 'n/a'} | Source: {self.detect_source_type()}"
        )
        version_date = datetime.now(UTC).strftime('%Y-%m-%d')
        lines.append('#')
        for step in plan.get('plan_steps', []):
            action = step.get('action', '')
            pol_ocid = step.get('policy_ocid', '')
            pol = policies_by_ocid.get(pol_ocid, {}) if pol_ocid else {}
            pol_name = pol.get('policy_name', '(unknown)') if pol else (step.get('create_policy_name') or 'new-policy')
            marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
            marker_val = (step.get('plan_tags') or {}).get('marker_tag_value', '')

            lines.append(
                f"## {step.get('step_id')} | {action.upper()} | {pol_name} ({pol_ocid or step.get('compartment_ocid', '')})"
            )
            for loc_note in step.get('location_change_notes') or []:
                lines.append(f'# {loc_note}')
            if action == 'add':
                comp_ocid = step.get('compartment_ocid', '')
                name = step.get('create_policy_name') or 'Consolidated-Root'
                desc = step.get('create_policy_description') or 'Policy created by consolidation (root compartment).'
                ff_add: dict = {str(marker_key): str(marker_val)} if marker_val else {}
                stmt_val = _statements_cli_value(step.get('after_statements', []))
                name_esc = _shell_escape_single_quoted(name)
                desc_esc = _shell_escape_single_quoted(desc)
                lines.append(
                    '# Create new policy in root compartment. You may change --name and --description as desired.'
                )
                lines.append('oci iam policy create \\')
                lines.append(f'  --compartment-id {comp_ocid} \\')
                lines.append(f"  --name '{name_esc}' \\")
                lines.append(f"  --description '{desc_esc}' \\")
                if ff_add:
                    lines.append(f'  --statements "{stmt_val}" \\')
                    lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff_add))}'")
                else:
                    lines.append(f'  --statements "{stmt_val}"')
                # oci iam policy create does not accept --force
            elif action == 'modify':
                ff, dd = _policy_tag_maps(pol)
                ff2 = dict(ff)
                if marker_val:
                    ff2[str(marker_key)] = str(marker_val)
                lines.append('# Update policy statements and mark step via freeform tag.')
                lines.append('# NOTE: OCI CLI updates replace the full statements list; this is intentional.')
                stmt_val = _statements_cli_value(step.get('after_statements', []))
                ff2_val = _shell_escape_single_quoted(_json_compact(ff2))
                lines.append('oci iam policy update \\')
                lines.append(f"  --policy-id {step.get('policy_ocid')} \\")
                lines.append(f'  --statements "{stmt_val}" \\')
                lines.append(f'  --version-date {version_date} \\')
                lines.append(f"  --freeform-tags '{ff2_val}' \\")
                if dd:
                    dd_val = _shell_escape_single_quoted(_json_compact(dd))
                    lines.append(f"  --defined-tags '{dd_val}' \\")
                lines.append('  --force')
            elif action == 'delete':
                lines.append('# Delete policy. Execution proof is policy absence on reload.')
                lines.append(f"oci iam policy delete --policy-id {step.get('policy_ocid')} --force")
                # Rollback (re-create policy) appears only in Rollback / Both section, not in Execution-only output.
            else:
                lines.append('# (unsupported action)')
            lines.append('')
        return '\n'.join(lines).strip()

    def render_plan_ui_instructions(  # noqa: C901
        self, plan: ConsolidationPlan, section: Literal['all', 'execution', 'rollback'] = 'all'
    ) -> str:
        """Render step-by-step UI instructions for the OCI Console.

        Produces human-readable steps for Identity & Security > Identity > Policies,
        including compartment navigation and location-change notes. Rollback block
        is included when section is "all" or "rollback".

        Args:
            plan: The consolidation plan to render.
            section: "execution" (steps only), "rollback" (rollback only), or "all" (both). Default "all".

        Returns:
            Multiline string of instructions, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        def _compartment_nav_path(comp_path: str | None) -> str:
            if not comp_path or not comp_path.strip():
                return ''
            return ' / '.join(comp_path.strip().split('/'))

        lines: list[str] = []
        lines.append(f"Consolidation plan: {plan.get('plan_id')} | {plan.get('plan_label')}")
        lines.append(f"Tenancy: {plan.get('tenancy_ocid')} | Source: {self.detect_source_type()}")
        lines.append('')

        if section in ('all', 'execution'):
            lines.append('--- EXECUTION STEPS (OCI Console) ---')
            for i, step in enumerate(plan.get('plan_steps', []), 1):
                action = step.get('action', '')
                pol_ocid = step.get('policy_ocid', '')
                pol = policies_by_ocid.get(pol_ocid, {}) if pol_ocid else {}
                pol_name = (
                    pol.get('policy_name', '(unknown)') if pol else (step.get('create_policy_name') or 'new-policy')
                )
                comp_path = pol.get('compartment_path') or ''
                if action == 'add':
                    comp_ocid = step.get('compartment_ocid', '')
                    comp_path = next(
                        (
                            c.get('hierarchy_path') or ''
                            for c in (getattr(repo, 'compartments', []) or [])
                            if c.get('id') == comp_ocid
                        ),
                        '',
                    )
                nav_path = _compartment_nav_path(comp_path)
                marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
                marker_val = (step.get('plan_tags') or {}).get('marker_tag_value', '')

                lines.append(f"Step {i} [{step.get('step_id')}] — {action.upper()}: {pol_name}")
                for loc_note in step.get('location_change_notes') or []:
                    lines.append(f'  • {loc_note}')
                if action == 'add':
                    lines.append(
                        '  • NOTE: You may change the Policy Name and Description as desired; a suitable default is provided.'
                    )
                if nav_path:
                    lines.append(f'  • Navigate to compartment: {nav_path}')
                lines.append('  • In OCI Console: Identity & Security > Identity > Policies.')
                if action == 'add':
                    lines.append(
                        f"  • Create a new policy in the root compartment. Name: {step.get('create_policy_name') or 'Consolidated-Root'}"
                    )
                    lines.append(
                        f"  • Description: {step.get('create_policy_description') or 'Policy created by consolidation (root compartment).'}"
                    )
                    lines.append('  • Set Statements to the following list:')
                    for st in step.get('after_statements', [])[:20]:
                        lines.append(f'    - {st}')
                    if len(step.get('after_statements', [])) > 20:
                        lines.append(f"    ... and {len(step.get('after_statements', [])) - 20} more.")
                    if marker_val:
                        lines.append(f'  • Add freeform tag: {marker_key} = {marker_val} (to mark step as executed).')
                    lines.append('  • Save the policy.')
                elif action == 'modify':
                    lines.append(f"  • Locate policy: {pol_name} (OCID: {step.get('policy_ocid')}).")
                    lines.append('  • Edit policy: set Statements to the following list (replace existing):')
                    for st in step.get('after_statements', [])[:20]:
                        lines.append(f'    - {st}')
                    if len(step.get('after_statements', [])) > 20:
                        lines.append(f"    ... and {len(step.get('after_statements', [])) - 20} more.")
                    lines.append(f'  • Add freeform tag: {marker_key} = {marker_val} (to mark step as executed).')
                    lines.append('  • Save the policy.')
                elif action == 'delete':
                    lines.append(f"  • Locate policy: {pol_name} (OCID: {step.get('policy_ocid')}).")
                    lines.append(
                        '  • Delete the policy. Execution is confirmed when the policy no longer appears after reload.'
                    )
                lines.append('')

        if section in ('all', 'rollback'):
            lines.append(
                '--- ROLLBACK (if needed, reverse order) — statements and policy creation below are permanent ---'
            )
            for i, step in enumerate(reversed(plan.get('plan_steps', [])), 1):
                action = step.get('action', '')
                pol_ocid = step.get('policy_ocid', '')
                pol = policies_by_ocid.get(pol_ocid, {}) if pol_ocid else {}
                pol_name = (
                    pol.get('policy_name', '(unknown)') if pol else (step.get('create_policy_name') or 'new-policy')
                )
                pol_comp = pol.get('compartment_ocid', '') if pol else (step.get('compartment_ocid', ''))
                comp_path = pol.get('compartment_path') or ''
                if action == 'add':
                    comp_path = next(
                        (
                            c.get('hierarchy_path') or ''
                            for c in (getattr(repo, 'compartments', []) or [])
                            if c.get('id') == step.get('compartment_ocid')
                        ),
                        '',
                    )
                nav_path = _compartment_nav_path(comp_path)
                r_marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
                lines.append(f'Rollback step {i}: {action.upper()} — {pol_name}')
                if nav_path:
                    lines.append(f'  • Navigate to compartment: {nav_path}')
                if action == 'add':
                    lines.append(
                        f"  • Delete the policy created in this step (root compartment; name: {step.get('create_policy_name') or 'Consolidated-Root'}). "
                        f"Find it by freeform tag {r_marker_key} if needed, then delete the policy."
                    )
                elif action == 'modify':
                    lines.append(
                        f"  • Edit policy {pol_name} (OCID: {step.get('policy_ocid')}) and restore the original statements below; remove freeform tag {r_marker_key}."
                    )
                    lines.append(f"  • Original statements to restore ({len(step.get('before_statements', []))}):")
                    for st in step.get('before_statements', []):
                        lines.append(f'    - {st}')
                elif action == 'delete':
                    lines.append(
                        f"  • Re-create policy in compartment {pol_comp or '(unknown)'} (path: {nav_path or 'n/a'}) with name: {pol_name}"
                    )
                    lines.append(f"  • Statements to set ({len(step.get('before_statements', []))}):")
                    for st in step.get('before_statements', []):
                        lines.append(f'    - {st}')
                    if pol.get('description'):
                        lines.append(f"  • Description: {pol.get('description')}")
                lines.append('')
        return '\n'.join(lines).strip()

    def render_plan_rollback_commands(self, plan: ConsolidationPlan) -> str:  # noqa: C901
        """Render CLI rollback commands for the plan (reverse order; re-create for deletes).

        Produces oci iam policy update/create commands to undo the plan. Shown in the
        Proposed Script area when the user selects "Rollback" or "Both". Execution-only
        view does not include these.

        Args:
            plan: The consolidation plan to render rollback for.

        Returns:
            Multiline string of commented and executable CLI lines, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        lines: list[str] = []
        version_date = datetime.now(UTC).strftime('%Y-%m-%d')
        lines.append(f"# Rollback commands for plan: {plan.get('plan_id')}")
        lines.append('# WARNING: Only safe if no newer plan has executed.')
        lines.append('')
        # Reverse order is typically safer
        for step in reversed(plan.get('plan_steps', [])):
            action = step.get('action', '')
            pol_ocid = step.get('policy_ocid', '')
            pol = policies_by_ocid.get(pol_ocid, {}) if pol_ocid else {}
            pol_name = pol.get('policy_name', '(unknown)') if pol else (step.get('create_policy_name') or 'new-policy')
            pol_comp = pol.get('compartment_ocid', '') if pol else (step.get('compartment_ocid', ''))

            lines.append(f"## ROLLBACK {step.get('step_id')} | {action.upper()} | {pol_name} ({pol_ocid or pol_comp})")
            if action == 'add':
                comp_ocid = step.get('compartment_ocid', '')
                marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
                marker_val = (step.get('plan_tags') or {}).get('marker_tag_value', '')
                lines.append('# Rollback add: delete the policy created in this step (root compartment).')
                lines.append('# List policies in compartment and find the one with the plan marker tag, then delete:')
                lines.append(f'# oci iam policy list --compartment-id {comp_ocid} --all')
                lines.append('# Then: oci iam policy delete --policy-id <policy-id-from-list> --force')
                if marker_val:
                    lines.append(f'# Look for freeform tag: {marker_key} = {marker_val}')
                lines.append('')
            elif action == 'modify':
                ff, dd = _policy_tag_maps(pol)
                stmt_val = _statements_cli_value(step.get('before_statements', []))
                lines.append('oci iam policy update \\')
                lines.append(f"  --policy-id {step.get('policy_ocid')} \\")
                lines.append(f'  --statements "{stmt_val}" \\')
                lines.append(f'  --version-date {version_date} \\')
                if ff:
                    lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff))}' \\")
                if dd:
                    lines.append(f"  --defined-tags '{_shell_escape_single_quoted(_json_compact(dd))}' \\")
                lines.append('  --force')
            elif action == 'delete':
                # rollback is recreate; use step-stored compartment/name/description when policy is gone
                pol_comp = pol_comp or step.get('compartment_ocid', '')
                pol_name = pol_name or step.get('create_policy_name', '')
                desc_for_create = step.get('create_policy_description') or (pol.get('description') if pol else '') or ''
                if pol_comp and pol_name:
                    ff, dd = _policy_tag_maps(pol) if pol else ({}, {})
                    stmt_val = _statements_cli_value(step.get('before_statements', []))
                    name_esc = _shell_escape_single_quoted(pol_name)
                    desc_esc = _shell_escape_single_quoted(desc_for_create)
                    lines.append('oci iam policy create \\')
                    lines.append(f'  --compartment-id {pol_comp} \\')
                    lines.append(f"  --name '{name_esc}' \\")
                    lines.append(f"  --description '{desc_esc}' \\")
                    if ff and dd:
                        lines.append(f'  --statements "{stmt_val}" \\')
                        lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff))}' \\")
                        lines.append(f"  --defined-tags '{_shell_escape_single_quoted(_json_compact(dd))}'")
                    elif ff:
                        lines.append(f'  --statements "{stmt_val}" \\')
                        lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff))}'")
                    elif dd:
                        lines.append(f'  --statements "{stmt_val}" \\')
                        lines.append(f"  --defined-tags '{_shell_escape_single_quoted(_json_compact(dd))}'")
                    else:
                        lines.append(f'  --statements "{stmt_val}"')
                    # oci iam policy create does not accept --force
                else:
                    lines.append(
                        '# Cannot rollback delete: missing compartment/name (plan may have been created '
                        'before step metadata was stored; re-run proposal to get rollback).'
                    )
            lines.append('')
        return '\n'.join(lines).strip()

    # ---- Execution Check (after reload) ----

    def check_plan_progress(self, plan: ConsolidationPlan) -> dict[str, dict[str, object]]:  # noqa: C901
        """Inspect current repo state to estimate execution progress per step.

        Uses policy presence (for delete steps) and marker tag presence (for modify steps)
        to determine which steps have been applied. Call after reloading policy data.

        Args:
            plan: The consolidation plan to check.

        Returns:
            Dict mapping step_id to a dict with keys such as executed (bool), notes (str),
            policy_ocid, action, checked_at.

        Raises:
            RuntimeError: If policy repository is not bound.
        """
        if not self.policy_repo:
            raise RuntimeError('Policy repository not bound.')

        repo = self.policy_repo
        current_policy_ocids = {
            p.get('policy_ocid') for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        results: dict[str, dict[str, object]] = {}
        for step in plan.get('plan_steps', []):
            step_id = step.get('step_id', '')
            pol_ocid = step.get('policy_ocid', '')
            action = step.get('action', '')
            plan_tags = step.get('plan_tags') or {}
            marker_key = str(plan_tags.get('marker_tag_key') or 'opa_consolidation')
            marker_val = str(plan_tags.get('marker_tag_value') or '')

            executed = False
            notes = ''
            if action == 'delete':
                executed = pol_ocid not in current_policy_ocids
                notes = 'policy missing' if executed else 'policy still present'
            elif action == 'modify':
                pol = policies_by_ocid.get(pol_ocid, {})
                ff, _dd = _policy_tag_maps(pol)
                if marker_val and ff.get(marker_key) == marker_val:
                    executed = True
                    notes = f'marker tag present ({marker_key}={marker_val})'
                else:
                    notes = f'marker tag missing or mismatch ({marker_key})'
            elif action == 'add':
                comp_ocid = step.get('compartment_ocid', '')
                if comp_ocid and marker_val:
                    for p in getattr(repo, 'policies', []) or []:
                        if (
                            p.get('compartment_ocid') == comp_ocid
                            and (p.get('freeform_tags') or {}).get(marker_key) == marker_val
                        ):
                            executed = True
                            notes = f'policy created with marker tag ({marker_key}={marker_val})'
                            break
                    if not executed:
                        notes = f'no policy in compartment with marker {marker_key}={marker_val}'
                else:
                    notes = 'add step missing compartment_ocid or marker'
            else:
                notes = 'unsupported action'

            results[step_id] = {
                'policy_ocid': pol_ocid,
                'action': action,
                'executed': executed,
                'notes': notes,
                'checked_at': now_iso(),
            }
        return results

    def get_plan_tag_conflicts(
        self,
        plan: ConsolidationPlan,
        policies_by_ocid: dict[str, BasePolicy] | None = None,
    ) -> list[dict[str, str]]:
        """
        Check if any policy in this plan has an opa_consolidation (marker) tag from a different plan.

        When multiple plans exist, a policy may already be tagged by another plan. If so, this plan
        is considered invalid/conflicted for execution until the situation is resolved. Works with
        any data source (live, cache, compliance); for static sources the result reflects the
        snapshot.

        Args:
            plan: The consolidation plan to check.
            policies_by_ocid: Optional map policy_ocid -> policy; if None, built from bound repo.

        Returns:
            List of dicts with keys policy_ocid, current_tag_value, conflicting_plan_id.
            Empty if no conflicts.
        """
        repo = self.policy_repo
        if not repo:
            return []
        if policies_by_ocid is None:
            policies_by_ocid = {
                p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
            }
        plan_id = (plan.get('plan_id') or '').strip()
        plan_tags = plan.get('plan_tags') or {}
        marker_key = str(plan_tags.get('marker_tag_key') or 'opa_consolidation')
        conflicts: list[dict[str, str]] = []
        for step in plan.get('plan_steps', []):
            pol_ocid = (step.get('policy_ocid') or '').strip()
            if not pol_ocid:
                continue
            step_plan_tags = step.get('plan_tags') or {}
            step_marker_key = str(step_plan_tags.get('marker_tag_key') or marker_key)
            pol = policies_by_ocid.get(pol_ocid, {})
            ff, _ = _policy_tag_maps(pol)
            current_val = (ff.get(step_marker_key) or '').strip()
            if not current_val:
                continue
            # Value is "plan_id:target" or "plan_id:s02"; prefix is the plan that set it
            prefix = current_val.split(':')[0].strip() if ':' in current_val else current_val
            if prefix and prefix != plan_id:
                conflicts.append(
                    {
                        'policy_ocid': pol_ocid,
                        'current_tag_value': current_val,
                        'conflicting_plan_id': prefix,
                    }
                )
        return conflicts
