##########################################################################
# Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# simulation_engine.py
#
# Core logic for OCI policy simulation: Determines, for any principal and compartment,
# what API operations are permitted, evaluating all applicable policy statements,
# resolving inheritance, and fully supporting conditional ("where") clauses.
#
# This engine folds in all where-clause simulation logic. The repo layer is
# responsible for providing structured policy and resource data; this module handles
# only permission simulation and policy calculation.
#
# @author: Andrew Gregory & Cline
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

from datetime import datetime
from typing import Any

from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.core.parser import (
    PolicyStatementNormalizer,
    evaluate_condition_clause,
    extract_variable_names,
)
from oci_policy_analysis.common.logger import get_logger

logger = get_logger(component='core.engine.policy_simulation_engine')


class PolicySimulationEngine:
    """
    Central simulation service for OCI policies.

    --- Stateless simulation setup APIs (recommended for UI/MCP) ---

    These methods provide the *canonical* way to derive principal keys, resolve all applicable
    policy statements, and compute required where-clause parameter names, regardless of UI vs MCP flow.

    Step 1: Normalize compartment_path and principal_type/principal into principal_key (handles tuple/string, None/'default', etc).
        -> Use normalize_principal_key(principal_type, principal)

    Step 2: Find all statements for a context (compartment_path, principal_type, principal).
        -> Use find_applicable_statements_for_context(compartment_path, principal_type, principal)

    Step 3: Get all required where-clause variable names for a context.
        -> Use get_required_where_fields_for_context(compartment_path, principal_type, principal)

    The MCP version *always* uses all valid applicable statements for a context.


    Responsibilities:
    - Given principal + effective compartment, generate the list of all applicable policy statements (including 'any-user').
    - Build and cache a mapping of compartment -> principal -> [statements] for fast lookup.
    - For a given policy context, extract all required where-clause fields, and evaluate conditional logic against input values.
    - For a set of user choices (principal + compartment + where values), return the effective permission set and permission simulation trace.
    - Fold in/replace all old where simulation logic found elsewhere (single source of truth).
    - DO NOT load or store raw data — consumption only.

    Primary entrypoints:
      - get_applicable_statements(principal, compartment): List[dict]
      - get_required_where_fields(statements): Set[str]
      - simulate_permissions(principal, compartment, where_context: dict): (Set[str], List[dict])
      - simulate_api_operation(principal, compartment, operation, where_context: dict): dict (YES/NO + full trace)
    """

    def _normalize_principal_key(self, principal_type, principal):
        """
        Internal: Canonical normalization for (principal_type, principal) to engine principal_key string.

        Args:
            principal_type (str): One of simulation model values ("user", "group", etc.)
            principal: str, tuple/list, or None. See context spec.

        Returns:
            str: Canonical key (e.g., "user:Default/anita", "any-user:None/any-user")
        """
        if principal_type in ('any-user', 'any-group', 'service'):
            key = f'{principal_type}:None/{principal or principal_type}'
            return key
        if isinstance(principal, list | tuple) and len(principal) == 2:
            domain, name = principal
            if domain is None or (isinstance(domain, str) and domain.lower() == 'default'):
                domain = 'Default'
            return f'{principal_type}:{domain}/{name}'
        elif isinstance(principal, str):
            return f'{principal_type}:Default/{principal}'
        raise ValueError(f'principal_type/principal combination not recognized: {principal_type}, {principal}')

    def get_statements_for_context(self, compartment_path, principal_type, principal=None):
        """
        Canonical: Return (principal_key, [statement dicts]) for a given policy simulation context (UI/MCP).

        Args:
            compartment_path (str): Path like 'ROOT/Finance'
            principal_type (str): "user", "group", etc.
            principal (optional): None, string, or (domain, name)

        Returns:
            (principal_key, statements): Tuple with normalized principal key and list of matching statements.

        See docs/source/simulation_engine_usage_examples.py for usage.
        """
        principal_key = self._normalize_principal_key(principal_type, principal)
        logger.info(f'Getting statements for context: compartment={compartment_path}, principal_key={principal_key}')
        statements = self.get_applicable_statements(principal_key, compartment_path)
        return principal_key, statements

    def get_required_where_fields_for_context(self, compartment_path, principal_type, principal=None):
        """
        Canonical: Given a context, return (principal_key, set of required where input variables).

        Args:
            compartment_path (str): e.g. "ROOT/Finance"
            principal_type (str): "user", "group", etc.
            principal (optional): None, string, or (domain, name)

        Returns:
            (principal_key, required_fields): Tuple with normalized principal key and set of all required where fields.

        See docs/source/simulation_engine_usage_examples.py for usage.
        """
        principal_key = self._normalize_principal_key(principal_type, principal)
        statements = self.get_applicable_statements(principal_key, compartment_path)
        required_fields = self.get_required_where_fields(statements)
        logger.info(
            f'Extracted where fields for context: compartment={compartment_path}, principal_type={principal_type}, principal={principal} -> {required_fields}'
        )
        return principal_key, required_fields

    @staticmethod
    def extract_variable_names(cond_str):
        """
        Extract variable names from a policy condition string using the OCI IAM Policy Condition parser.

        Args:
            cond_str (str): The condition string to analyze.

        Returns:
            set[str]: A set of variable names (as strings) present in the condition clause.
        """
        return extract_variable_names(str(cond_str or ''))

    def __init__(self, policy_repo=None, ref_data_repo=None):
        """
        Initialize a PolicySimulationEngine for OCI policy simulation.

        Args:
            policy_repo (PolicyAnalysisRepository, optional): Repository object containing parsed policy statements
                (should have 'regular_statements' attribute).
            ref_data_repo (ReferenceDataRepo, optional): Reference data repository with permissions/operations information.

        Attributes:
            policy_statements (list[dict]): The list of policy statements to simulate.
            ref_data_repo (ReferenceDataRepo): Reference data object for permissions/operation simulation.
            policy_repo (PolicyAnalysisRepository): Full object so we can perform filter_policy_statements queries.
            internal_state (dict): Diagnostic/debug state.
            simulation_history (list): Simulation log/history, used for GUI trace table, etc.
        """
        logger.info(
            f'PolicySimulationEngine initialized with {len(policy_repo.regular_statements) if policy_repo else 0} policy statements'
        )
        self.policy_repo = policy_repo
        if policy_repo:
            logger.info(
                f"policy_repo type: {type(policy_repo)}; hasattr regular_statements: {hasattr(policy_repo, 'regular_statements')}"
            )
            if hasattr(policy_repo, 'regular_statements'):
                logger.info(
                    f'policy_repo.regular_statements type: {type(policy_repo.regular_statements)} len: {len(policy_repo.regular_statements)}'
                )
        else:
            logger.warning('No policy_repo provided to PolicySimulationEngine.')

        self.policy_statements = policy_repo.regular_statements if policy_repo else []
        logger.info(
            f'self.policy_statements initialized: type={type(self.policy_statements)}, len={len(self.policy_statements)}'
        )
        self.ref_data_repo = ref_data_repo
        # Prospective (what-if) policy statements, managed via UI/settings and treated
        # identically to regular statements during simulation. Stored as a list of
        # normalized statement dicts with at least: internal_id, compartment_path,
        # policy_name/description, statement_text, conditions, is_prospective=True.
        self._prospective_statements: list[dict[str, Any]] = []
        # Create a JSON to hold internal state for debug and tracing
        self.internal_state: dict[str, Any] = {}
        self.internal_state['total_statements'] = len(self.policy_statements)
        # Simulation log/history: list of dicts, one per simulation run
        self.simulation_history: list[dict[str, Any]] = []
        # Normalizer for validating prospective statements (reuses core parser)
        self._statement_normalizer = PolicyStatementNormalizer()

    # ------------------------------------------------------------------
    # Prospective Statement Management
    # ------------------------------------------------------------------

    def get_prospective_statements(self) -> list[dict[str, Any]]:
        """Return a shallow copy of all current prospective statements.

        These statements are *in addition to* the regular policy statements
        loaded from the tenancy/cache and are used for "what-if" simulation
        scenarios. They are not written back to OCI.
        """

        # Shallow copy is enough for UI consumption; engine maintains the
        # authoritative list.
        return list(self._prospective_statements)

    def _ensure_prospective_internal_ids(self) -> None:
        """Ensure each prospective statement has a unique internal_id.

        Uses a distinct id space with the prefix ``prospective-`` to avoid
        colliding with tenancy-loaded statement ids (typically numeric/UUID).
        """

        # Build a set of existing ids from regular statements for safety.
        existing_ids = {str(s.get('internal_id')) for s in self.policy_statements if s.get('internal_id') is not None}
        counter = 1
        for stmt in self._prospective_statements:
            cur = stmt.get('internal_id')
            if cur is None or str(cur) in existing_ids:
                # Assign new id in the prospective-* namespace
                new_id = f'prospective-{counter}'
                while new_id in existing_ids:
                    counter += 1
                    new_id = f'prospective-{counter}'
                stmt['internal_id'] = new_id
                existing_ids.add(new_id)
                counter += 1

    def set_prospective_statements(self, statements: list[dict[str, Any]]) -> None:  # noqa: C901
        """Replace the current set of prospective statements.

        The caller (UI/MCP) provides lightweight dicts with at least
        ``compartment_path``, ``statement_text``, and optional ``description``.
        This method will:

        * mark each as ``is_prospective = True``
        * ensure each has a unique ``internal_id``

        Persistence to disk/settings is orchestrated by the application; the
        engine simply owns the in-memory representation used for simulation.
        """

        norm: list[dict[str, Any]] = []
        # Lazily create a lightweight PolicyIntelligenceEngine for effective_path calculation
        intelligence_engine: PolicyIntelligenceEngine | None = None
        if self.policy_repo is not None:
            try:
                intelligence_engine = PolicyIntelligenceEngine(self.policy_repo)
            except Exception as ex:  # defensive: do not break prospective handling if analytics init fails
                logger.warning(
                    'Unable to initialize PolicyIntelligenceEngine for prospective statements: %s', ex, exc_info=True
                )
                intelligence_engine = None
        for raw in statements or []:
            if not isinstance(raw, dict):  # defensive
                continue
            st = dict(raw)
            st['is_prospective'] = True
            # Normalize keys we rely on downstream
            st.setdefault('compartment_path', raw.get('compartment_path', 'ROOT'))
            st.setdefault('statement_text', raw.get('statement_text', ''))
            # Human-friendly display name; UI can override
            desc = st.get('description') or raw.get('description')
            if not st.get('policy_name'):
                if desc:
                    st['policy_name'] = str(desc)
                else:
                    st['policy_name'] = f"Prospective @{st['compartment_path']}"

            # Run validation so we can track valid/invalid in the prospective set
            try:
                v = self.validate_prospective_statement(st['statement_text']) if st['statement_text'] else None
            except Exception as ex:  # extremely defensive
                logger.warning('Exception while validating prospective statement during set: %s', ex, exc_info=True)
                v = None

            if v is not None:
                st['parsed'] = bool(v.get('parsed'))
                st['valid'] = bool(v.get('valid'))
                st['invalid_reasons'] = v.get('invalid_reasons') or []
                # If the statement parsed and is valid, capture the full normalized
                # RegularPolicyStatement-like payload so downstream simulation and
                # debugging can rely on verb/resource/permission/effective_path.
                normalized = v.get('normalized') or {}
                if st['parsed'] and st['valid'] and isinstance(normalized, dict):
                    st['normalized'] = normalized
                    # For convenience, also project key RegularPolicyStatement
                    # fields to top-level keys if they are present. This keeps
                    # prospective statements structurally similar to regular
                    # tenancy statements consumed by the engine.
                    for key in (
                        'verb',
                        'resource',
                        'permission',
                        'effective_path',
                        'conditions',
                        'action',
                    ):
                        if key in normalized and key not in st:
                            st[key] = normalized.get(key)

                    # Ensure effective_path is calculated for simulation/permissions alignment.
                    # The normalizer may not always populate effective_path, so fall back to
                    # the same calculation used for regular tenancy statements via
                    # PolicyIntelligenceEngine.calculate_effective_compartment_for_statement.
                    if intelligence_engine is not None and not st.get('effective_path'):
                        try:
                            intelligence_engine.calculate_effective_compartment_for_statement(st)
                        except Exception as ex:  # defensive: keep prospective statement but log issue
                            logger.warning(
                                'Failed to calculate effective_path for prospective statement %r: %s',
                                st.get('statement_text'),
                                ex,
                                exc_info=True,
                            )
            else:
                # Unknown state; treat as not parsed/invalid so it is hidden from simulation
                st['parsed'] = False
                st['valid'] = False
                st['invalid_reasons'] = ['Validation error']

            norm.append(st)

        self._prospective_statements = norm
        # Assign safe ids after replacing list
        self._ensure_prospective_internal_ids()
        # Log the fully-parsed/normalized prospective statements for debug
        # visibility. This is intentionally at INFO so the Simulation tab
        # debugger can see the exact verb/resource/permissions/effective_path
        # that will participate in simulation.
        logger.info(
            'set_prospective_statements: loaded %d prospective statements (normalized views below):',
            len(self._prospective_statements),
        )
        for idx, pst in enumerate(self._prospective_statements):
            logger.info(
                '  prospective[%d]: policy_name=%r compartment_path=%r valid=%s parsed=%s verb=%r resource=%r '
                'permissions=%r effective_path=%r conditions=%r internal_id=%r',
                idx,
                pst.get('policy_name'),
                pst.get('compartment_path'),
                pst.get('valid'),
                pst.get('parsed'),
                pst.get('verb'),
                pst.get('resource'),
                pst.get('permission'),
                pst.get('effective_path'),
                pst.get('conditions'),
                pst.get('internal_id'),
            )

    # ------------------------------------------------------------------
    # Prospective validation helper (used by UI Parse button)
    # ------------------------------------------------------------------

    def validate_prospective_statement(self, statement_text: str) -> dict[str, Any]:
        """Validate and normalize a single prospective statement.

        Returns a dict with keys:
          - parsed: bool
          - valid: bool
          - invalid_reasons: list[str]
          - normalized: dict (if valid)
        """

        base_fields: dict[str, Any] = {}
        stmt_type = 'regular'  # prospective statements are standard allow/deny
        logger.info(f'Validating prospective statement: {statement_text!r}')
        norm = self._statement_normalizer.normalize(statement_text, stmt_type, base_fields)
        parsed = bool(norm.get('parsed', False))
        valid = bool(norm.get('valid', parsed))
        reasons = norm.get('invalid_reasons') or []
        logger.debug(f'Prospective normalize result: {norm!r}')
        if parsed and valid:
            logger.info('Prospective statement parsed successfully.')
        elif parsed and not valid:
            logger.warning('Prospective statement parsed but marked invalid: %s', reasons)
        else:
            logger.warning('Prospective statement failed to parse: %s', reasons)
        return {
            'parsed': parsed,
            'valid': valid,
            'invalid_reasons': reasons,
            'normalized': norm if parsed and valid else {},
        }

    def simulate_and_record(  # noqa: C901
        self,
        principal_key: str,
        effective_path: str,
        api_operation: str,
        where_context: dict,
        checked_statement_ids: list[str] | None = None,
        trace_name: str | None = None,
        scenario_internal_id: str | None = None,
        scenario_name: str | None = None,
        simulation_name: str | None = None,
        trace: bool = False,
    ) -> dict[str, Any]:
        """
        Simulates permissions for a principal, compartment, and operation, recording full trace/results.

        Args:
            principal_key (str): The unique principal key (e.g., "group:default/Admins") for the simulation.
            effective_path (str): The effective compartment path for simulation.
            api_operation (str): The API operation to check permission for.
            where_context (dict): Input/context for any evaluated 'where' policy clauses.
            checked_statement_ids (Optional[list[str]]): List of policy statement internal_ids to include in simulation.
                If omitted or None, all applicable statements for the context (principal_key and effective_path) are used.
            trace_name (str, optional): Optional name for this simulation trace/history.
            trace (bool, optional): If True, includes detailed step-by-step trace; else, summary only.

        Returns:
            dict[str, Any]: Full simulation result. The engine *always* computes a full simulation trace
                (permissions, context, per-statement evaluation). The return payload is shaped as follows:

                Top-level keys (always present):
                  - api_call_allowed (bool): Final YES/NO decision for the API operation.
                  - missing_permissions (list[str]): Permissions required by the operation but not granted.
                  - required_permissions_for_api_operation (list[str]): All permissions the operation needs.
                  - failure_reason (str): Empty if allowed, else human-readable explanation.

                Trace block (always present, but caller may choose whether to display it):
                  - simulation_trace (dict):
                        {
                          'final_permission_set': [...],
                          'simulation_context': {...},
                          'permissions_denied': [...],
                          'trace_statements': [...]   # present only when trace=True
                        }

                Notes:
                  * The UI uses the trace flag to control how much of simulation_trace is displayed.
                  * simulation_history always records the *full* simulation_trace (with trace_statements),
                    independent of the trace flag used for the immediate UI response.

        Example:
            result = engine.simulate_and_record('group:default/Admins', 'ROOT', 'oci:ListBuckets', {}, checked_ids, trace=True)
            result = engine.simulate_and_record('group:default/Admins', 'ROOT', 'oci:ListBuckets', {}, trace=True)  # auto selects statements
        """
        # Wrap this entire function with try and catch, print stack trace, then re-raise
        try:
            # If checked_statement_ids not provided, use all statements applicable to this context.
            # We keep the derived list in a local variable for optional debug logging.
            stmts: list[dict[str, Any]] | None = None
            if checked_statement_ids is None:
                stmts = self.get_applicable_statements(principal_key, effective_path)
                checked_statement_ids = [str(s.get('internal_id')) for s in stmts if s.get('internal_id') is not None]

            # NOTE: trace flag is retained for backward compatibility but no
            # longer affects payload shape; the engine always computes and
            # returns full trace details. Callers control how much to display.
            logger.info(
                f'Simulating permissions for principal={principal_key}, compartment={effective_path}, operation={api_operation}. Statements: {len(checked_statement_ids) if checked_statement_ids else 0} selected. Trace flag (ignored in engine)={trace}'
            )
            trace_obj: dict[str, Any] = {}
            perm_set = set()
            statement_trace = []
            permissions_denied = []

            allow_statements = []
            deny_statements = []
            logger.info(
                f'(IN simulate_and_record: pre-mapping) self.policy_statements type: {type(self.policy_statements)} len: {len(self.policy_statements)}'
            )
            for i, s in enumerate(self.policy_statements[:7]):
                logger.info(f"  self.policy_statements[{i}]: internal_id={s.get('internal_id')}")
            # Only print stmts diagnostics if we actually derived them above
            if checked_statement_ids is not None and stmts is not None:
                logger.info(
                    f'(IN simulate_and_record: pre-mapping) stmts (from get_applicable_statements) type: {type(stmts)} len: {len(stmts)}'
                )
                for i, s in enumerate(stmts[:7]):
                    logger.info(
                        f"  stmts[{i}]: internal_id={s.get('internal_id')} statement_text={s.get('statement_text')}"
                    )
            # Build the statement map from the **current** policy repository plus
            # any prospective (what-if) statements, rather than relying solely on
            # the constructor-time snapshot in self.policy_statements. This
            # ensures that the IDs shown in the Simulation tab (which come from
            # get_applicable_statements, i.e. filter_policy_statements +
            # _prospective_statements) can always be resolved here.
            base_statements: list[dict[str, Any]] = []
            if self.policy_repo and hasattr(self.policy_repo, 'regular_statements'):
                try:
                    base_statements = list(self.policy_repo.regular_statements or [])
                except Exception:
                    # Extremely defensive; fall back to whatever snapshot we
                    # had at construction time.
                    logger.warning(
                        'simulate_and_record: unable to read policy_repo.regular_statements; '
                        'falling back to self.policy_statements',
                        exc_info=True,
                    )
                    base_statements = list(self.policy_statements or [])
            else:
                base_statements = list(self.policy_statements or [])

            prospective_statements: list[dict[str, Any]] = list(self._prospective_statements or [])
            src_statements: list[dict[str, Any]] = base_statements + prospective_statements

            all_stmt_map = {str(s.get('internal_id')): s for s in src_statements if s.get('internal_id') is not None}
            logger.info(
                'simulate_and_record: built all_stmt_map with %d total entries '
                '(from %d base + %d prospective statements); sample keys=%s',
                len(all_stmt_map),
                len(base_statements),
                len(prospective_statements),
                list(all_stmt_map.keys())[:10],
            )
            logger.info(f'Checked statement IDs: {checked_statement_ids}')
            for internal_id in checked_statement_ids or []:
                if internal_id not in all_stmt_map:
                    logger.warning(
                        f'Statement ID {internal_id} not found in all_stmt_map keys: {list(all_stmt_map.keys())}'
                    )
                stmt = all_stmt_map.get(str(internal_id))
                if not stmt:
                    logger.warning(f'Statement ID {internal_id} not found in repo. Skipped.')
                    continue
                # Print some details about the statement for debugging
                logger.info(
                    f"Processing statement ID {internal_id}: action={stmt.get('action')}, "
                    f"resource={stmt.get('resource')}, verb={stmt.get('verb')}, "
                    f"statement_text={stmt.get('statement_text')}"
                )
                if stmt.get('action', 'allow').lower() == 'deny':
                    deny_statements.append((internal_id, stmt))
                else:
                    allow_statements.append((internal_id, stmt))

            # Log something
            logger.info(f'Processing {len(allow_statements)} ALLOW statements')
            # First pass: ALLOW statements
            for _internal_id, stmt in allow_statements:
                stmt_entry = {
                    'statement_text': stmt.get('statement_text', ''),
                    'permissions': [],
                    'conditional': bool(stmt.get('conditions')),
                    'passed': True,
                    'fail_reason': '',
                    'action': 'allow',
                }
                # Log the statement evaluation
                logger.info(f"Evaluating ALLOW stmt: {stmt.get('statement_text', '')}")
                passed = True
                fail_reason = ''
                if stmt.get('conditions'):
                    logger.info(f"Evaluating conditions for allow stmt: {stmt.get('statement_text', '')}")
                    passed, fail_reason = self._evaluate_conditions(stmt.get('conditions'), where_context)
                    if not passed:
                        stmt_entry['passed'] = False
                        stmt_entry['fail_reason'] = fail_reason or 'Condition(s) did not pass'
                        statement_trace.append(stmt_entry)
                        continue
                direct_perms = stmt.get('permission', [])
                # Log the permissions we are about to add from this statement before we do it
                logger.info(f'Direct permissions for ALLOW stmt: {direct_perms}')

                resource_perms = (
                    self.ref_data_repo.get_permissions(stmt.get('resource'), stmt.get('verb'), action='allow')
                    if self.ref_data_repo
                    else []
                )
                # Log the permissions we got from the reference data repo for this statement before we add them
                logger.info(f'Resource permissions for ALLOW stmt: {resource_perms}')
                all_perms = list(direct_perms or []) + list(resource_perms or [])
                if all_perms:
                    logger.info(
                        f"Adding permissions from ALLOW: {all_perms} for statement: {stmt.get('statement_text', '')}"
                    )
                for p in all_perms:
                    perm_set.add(p)
                stmt_entry['permissions'] = all_perms
                statement_trace.append(stmt_entry)

            # Log something
            logger.info(f'Processing {len(deny_statements)} DENY statements')

            # DENY statements
            for _internal_id, stmt in deny_statements:
                stmt_entry = {
                    'statement_text': stmt.get('statement_text', ''),
                    'permissions': [],
                    'conditional': bool(stmt.get('conditions')),
                    'passed': True,
                    'fail_reason': '',
                    'action': 'deny',
                }
                passed = True
                fail_reason = ''
                if stmt.get('conditions'):
                    logger.debug(f"Evaluating conditions for DENY stmt: {stmt.get('statement_text', '')}")
                    passed, fail_reason = self._evaluate_conditions(stmt.get('conditions'), where_context)
                    if not passed:
                        stmt_entry['passed'] = False
                        stmt_entry['fail_reason'] = fail_reason or 'Condition(s) did not pass'
                        statement_trace.append(stmt_entry)
                        continue

                direct_perms = stmt.get('permission', [])
                resource_perms = (
                    self.ref_data_repo.get_permissions(stmt.get('resource'), stmt.get('verb'), action='deny')
                    if self.ref_data_repo
                    else []
                )

                # Special-case: a global deny for "inspect all-resources" should
                # revoke *everything* that has been granted so far in this
                # simulation context. This matches the intuitive expectation
                # that such a policy removes all effective permissions,
                # regardless of which verbs were used to grant them.
                if (
                    str(stmt.get('action', '')).lower() == 'deny'
                    and str(stmt.get('resource', '')).lower() == 'all-resources'
                    and str(stmt.get('verb', '')).lower() == 'inspect'
                ):
                    deny_this = set(perm_set)
                    logger.info(
                        'Global deny detected (deny inspect all-resources); revoking all currently granted permissions: %d entries',
                        len(deny_this),
                    )
                else:
                    deny_this = set(direct_perms or []) | set(resource_perms or [])

                logger.info(f'Resource permissions for DENY stmt: {resource_perms}')
                actually_revoked = []
                for p in deny_this:
                    if p in perm_set:
                        perm_set.remove(p)
                        actually_revoked.append(p)
                stmt_entry['permissions'] = list(deny_this)
                stmt_entry['permissions_revoked'] = list(actually_revoked)
                if actually_revoked:
                    stmt_entry['revocation_details'] = [
                        f"Permission '{p}' revoked by deny statement." for p in actually_revoked
                    ]
                else:
                    stmt_entry['revocation_details'] = []
                statement_trace.append(stmt_entry)
                # Track globally for results/summary
                for p in actually_revoked:
                    permissions_denied.append({'permission': p, 'by_statement': stmt.get('statement_text', '')})

            trace_obj['simulation_context'] = {
                'principal_key': principal_key,
                'effective_path': effective_path,
                'where_context': where_context,
                'api_operation': api_operation,
            }
            # Always record the full trace details for history/export, but let the
            # caller control whether detailed per-statement entries are surfaced
            # in the immediate result via the `trace` flag.
            trace_obj['trace_statements'] = list(statement_trace)
            trace_obj['final_permission_set'] = sorted(perm_set)
            trace_obj['permissions_denied'] = permissions_denied

            logger.info(f'Final permissions: {sorted(perm_set)} for {principal_key} in {effective_path}')

            # Operation simulation/check
            has_permission = (
                self.ref_data_repo.has_api_operation_permissions(api_operation, perm_set)
                if self.ref_data_repo
                else False
            )
            # Collect required permissions for API operation (empty if not found)
            required = []
            missing = set()
            if self.ref_data_repo:
                required = self.ref_data_repo.data.get('operations', {}).get(api_operation, {}).get('permissions', [])
                missing = {p.upper() for p in required if p.upper() not in perm_set}

            trace_obj['required_permissions_for_api_operation'] = sorted([p.upper() for p in required])

            # Base result: summary fields always at the top level.
            sim_result: dict[str, Any] = {
                'api_call_allowed': has_permission,
                'missing_permissions': sorted(missing),
                'required_permissions_for_api_operation': trace_obj['required_permissions_for_api_operation'],
                'failure_reason': '' if has_permission else f'Missing required permissions: {sorted(missing)}',
                'scenario_internal_id': scenario_internal_id or '',
                'scenario_name': scenario_name or '',
                'simulation_name': simulation_name or '',
                # New summary counters: how many ALLOW vs DENY statements were
                # actually considered for this simulation (after filtering by
                # principal/path/checked_statement_ids). These are useful for
                # quickly debugging inclusion issues without needing the full
                # trace.
                'allow_statements_considered': len(allow_statements),
                'deny_statements_considered': len(deny_statements),
            }

            # Always expose full simulation_trace (including
            # trace_statements). UI/CLI callers decide what to display.
            sim_result['simulation_trace'] = dict(trace_obj)

            # Record full trace (including statement-level details) to
            # simulation_history so later review and export have the complete
            # picture regardless of the UI mode used at call time.
            history_entry_payload = dict(sim_result)
            history_entry_payload['simulation_trace'] = trace_obj

            entry = {
                'name': trace_name or f"Simulation {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'scenario_internal_id': scenario_internal_id or '',
                'scenario_name': scenario_name or '',
                'simulation_name': simulation_name or '',
                'api_operation': api_operation,
                'api_call_allowed': bool(sim_result.get('api_call_allowed')),
                'trace': history_entry_payload,
            }
            self.simulation_history.append(entry)
            return sim_result
        except Exception as e:
            logger.exception(f'Error during simulate_and_record: {e}')
            raise

    def get_simulation_trace_list(self) -> list[dict[str, str | bool]]:
        """
        Get the list of names and timestamps for all recorded simulation traces.

        Returns:
            list[dict[str, str]]: List of dictionaries with keys 'name' and 'timestamp'
                corresponding to each simulation history entry.

        Example:
            [{'name': 'Simulation 1', 'timestamp': '2026-01-05T14:00:01'}, ...]
        """
        return [
            {
                'name': entry['name'],
                'timestamp': entry['timestamp'],
                'scenario_internal_id': entry.get('scenario_internal_id', ''),
                'scenario_name': entry.get('scenario_name', ''),
                'simulation_name': entry.get('simulation_name', ''),
                'api_operation': entry.get('api_operation', ''),
                'api_call_allowed': bool(entry.get('api_call_allowed')),
            }
            for entry in self.simulation_history
        ]

    def get_simulation_trace_by_index(self, idx: int) -> dict[str, Any] | None:
        """
        Retrieve a previously recorded simulation trace result by history index.

        Args:
            idx (int): Index into simulation history (0 = oldest).

        Returns:
            dict[str, Any] or None: The trace result dict, or None if index is out of range.

        Example:
            >>> engine.get_simulation_trace_by_index(0)
            {'result': 'YES', ...}
        """
        if 0 <= idx < len(self.simulation_history):
            return self.simulation_history[idx]['trace']
        return None

    def get_simulation_trace_by_name(self, name: str) -> dict[str, Any] | None:
        """
        Retrieve a simulation trace result by name label.

        Args:
            name (str): Name of the simulation trace to look up.

        Returns:
            dict[str, Any] or None: The simulation trace result, or None if no match.
        """
        for entry in self.simulation_history:
            if entry['name'] == name:
                return entry['trace']
        return None

    def get_api_operations(self, filter_text: str = '') -> list:
        """
        Get all known API operation names, optionally filtered by substring.

        Args:
            filter_text (str, optional): Substring to filter operation names (case-insensitive). Defaults to '' (all ops).

        Returns:
            list[str]: Sorted list of API operation names.

        Example:
            >>> engine.get_api_operations('bucket')
            ['oci:ListBuckets', 'oci:CreateBucket', ...]
        """
        if not self.ref_data_repo or not hasattr(self.ref_data_repo, 'data'):
            return []
        ops = self.ref_data_repo.data.get('operations', {})
        filtered = [name for name in ops if filter_text.lower() in name.lower()] if filter_text else list(ops.keys())
        return sorted(filtered)

    # build_index removed: filtering is now delegated to the repo.

    def _principal_key_to_policy_search_filter(self, principal_key: str) -> dict:  # noqa: C901
        """
        Convert a principal_key string into a PolicySearch-compatible dict filter.

        The function parses principal_key of the form '{type}:{domain}/{name}' or '{type}:None/{name}' and
        maps it to a PolicySearch filter using the correct exact_* field or subject, per model spec.

        Returns:
            Dict suitable for **POLICY** repository filtering. Does not include effective_path.
        """
        # Examples:
        #   user:Default/anita → {'principal_key': ['user:Default/anita']}
        #   group:Default/Admins → {'principal_key': ['group:Default/Admins']}
        #   dynamic-group:Default/MyDyn → {'principal_key': ['dynamic-group:Default/MyDyn']}
        #   any-user:None/any-user → {'principal_key': ['any-user:None/any-user']}
        #   any-group:None/any-group → {'principal_key': ['any-group:None/any-group']}
        #   service:None/some-service → {'principal_key': ['service:None/some-service']}
        import re

        m = re.match(r'(?P<ptype>[^:]+):(?P<domain>[^/]+)/(?P<name>.*)', principal_key)
        if not m:
            # fallback for odd cases
            return {'principal_key': [principal_key]}

        ptype, domain, name = m['ptype'], m['domain'], m['name']
        logger.info(f'Mapping principal_key to policy search filter: ptype={ptype}, domain={domain}, name={name}')

        # Normalize domain
        if domain.lower() == 'none':
            domain = None
        elif domain.lower() == 'default':
            domain = 'Default'

        # Use principal_key as first-class filter to avoid fuzzy subject collisions
        # (e.g. service "database" should not match group names containing "database").
        return_filter = {'principal_key': [f'{ptype}:{domain if domain is not None else "None"}/{name}']}
        logger.info(f'Generated policy search filter: {return_filter}')
        return return_filter

    def get_applicable_statements(self, principal_key: str, effective_path: str) -> list[dict]:  # noqa: C901
        """
        Get all applicable policy statements for a principal and compartment by building a proper
        PolicySearch filter using the principal_key and effective_path.

        Args:
            principal_key (str): Canonical principal key (e.g., 'user:Default/anita')
            effective_path (str): Compartment path for simulation context (e.g., 'ROOT/Finance')

        Returns:
            List[dict]: List of matching policy statement dicts.

        Notes:
            - Used by all canonical orchestration flows (UI/MCP)
            - See usage examples in docs/source/simulation_engine_usage_examples.py
        """
        logger.info(
            'get_applicable_statements: start for principal_key=%s, effective_path=%s',
            principal_key,
            effective_path,
        )

        def _statement_principal_keys(stmt: dict) -> set[str]:
            """Return any authoritative principal keys stored on a statement.

            Principal keys are treated as authoritative when present. We
            only fall back to legacy subject-based matching when no
            principal keys exist.
            """

            keys: set[str] = set()
            key = stmt.get('principal_key')
            if isinstance(key, str) and key.strip():
                keys.add(key.strip())

            principals = stmt.get('principals')
            if isinstance(principals, list):
                for principal in principals:
                    if not isinstance(principal, dict):
                        continue
                    pkey = principal.get('principal_key')
                    if isinstance(pkey, str) and pkey.strip():
                        keys.add(pkey.strip())

            normalized = stmt.get('normalized')
            if isinstance(normalized, dict):
                nkey = normalized.get('principal_key')
                if isinstance(nkey, str) and nkey.strip():
                    keys.add(nkey.strip())
                nprincipals = normalized.get('principals')
                if isinstance(nprincipals, list):
                    for principal in nprincipals:
                        if not isinstance(principal, dict):
                            continue
                        pkey = principal.get('principal_key')
                        if isinstance(pkey, str) and pkey.strip():
                            keys.add(pkey.strip())

            return keys

        # --- Base tenancy statements via repo filter ---
        if not self.policy_repo or not hasattr(self.policy_repo, 'filter_policy_statements'):
            logger.warning('get_applicable_statements: filter_policy_statements not available in repo.')
            base_stmts: list[dict] = []
        else:
            filters = self._principal_key_to_policy_search_filter(principal_key)
            filters['effective_path'] = [effective_path]
            logger.info(f'get_applicable_statements: Using filters {filters}')
            base_stmts = self.policy_repo.filter_policy_statements(filters)
            logger.info(f'get_applicable_statements: Found {len(base_stmts)} base (tenancy) statements.')

        # --- Prospective (what-if) statements ---
        # Merge in any prospective statements applicable to this context. We
        # enforce **both** effective_path scoping and principal/subject
        # matching so that prospective behavior mirrors tenancy-loaded
        # statements as closely as possible.
        comp_path = (effective_path or '').strip()
        merged: list[dict] = list(base_stmts)
        if comp_path and self._prospective_statements:
            # Reuse the same principal filter semantics used for repo
            # filtering, but apply them in-memory against the normalized
            # prospective statement subjects.
            subj_filter = self._principal_key_to_policy_search_filter(principal_key)
            any_subjects = {str(s).lower() for s in subj_filter.get('subject', []) if s}
            logger.info(
                'get_applicable_statements: evaluating %d prospective statements for principal_key=%s; any_subjects=%s',
                len(self._prospective_statements),
                principal_key,
                sorted(any_subjects),
            )

            def _prospective_matches_principal(pst: dict) -> bool:  # noqa: C901
                stored_keys = _statement_principal_keys(pst)
                if stored_keys:
                    return principal_key in stored_keys

                # Legacy path: fall back to subject_type/subject matching
                ptype = (pst.get('subject_type') or pst.get('normalized', {}).get('subject_type') or '').lower()
                subjects = pst.get('subject')
                if not subjects:
                    subjects = pst.get('normalized', {}).get('subject') or []

                logger.info(
                    '_prospective_matches_principal: legacy check pst internal_id=%r policy_name=%r subject_type=%r subjects=%r against filter=%r (any_subjects=%r) for principal_key=%s',
                    pst.get('internal_id'),
                    pst.get('policy_name'),
                    ptype,
                    subjects,
                    subj_filter,
                    sorted(any_subjects),
                    principal_key,
                )
                # Ensure we keep using the resolved subjects (which may
                # have come from normalized) for all subsequent checks.
                # any-user / any-group / service (string subject match)
                if any_subjects:
                    # subjects may be list[tuple] or list[str]; compare string forms
                    for s in subjects:
                        if isinstance(s, str) and s.strip().lower() in any_subjects:
                            return True

                # Principal-key-first legacy matcher for name-based principals.
                # This is required when subj_filter only carries principal_key and
                # no exact_* fields (common in simulation context lookup).
                try:
                    pk_ptype, pk_tail = principal_key.split(':', 1)
                    pk_domain, pk_name = pk_tail.split('/', 1)
                except ValueError:
                    pk_ptype, pk_domain, pk_name = '', '', ''
                pk_ptype_cf = pk_ptype.strip().casefold()
                pk_domain_cf = (
                    'default' if pk_domain.strip().casefold() in {'', 'none', 'default'} else pk_domain.strip()
                ).casefold()
                pk_name_cf = pk_name.strip().casefold()

                if ptype in {'user', 'group', 'dynamic-group'} and pk_ptype_cf == ptype and pk_name_cf:
                    norm_subj: set[tuple[str, str]] = set()
                    for s in subjects:
                        if isinstance(s, (tuple | list)) and len(s) == 2:
                            domain, name = s
                            name_cf = str(name or '').strip().casefold()
                            if not name_cf:
                                continue
                            dom_raw = str(domain).strip() if domain not in (None, '') else 'default'
                            dom_cf = ('default' if dom_raw.casefold() in {'default', 'none'} else dom_raw).casefold()
                            norm_subj.add((dom_cf, name_cf))
                        elif isinstance(s, str):
                            raw = s.strip()
                            if not raw:
                                continue
                            if '/' in raw:
                                dom_raw, name_raw = raw.split('/', 1)
                                dom_cf = (
                                    'default'
                                    if str(dom_raw).strip().casefold() in {'', 'default', 'none'}
                                    else str(dom_raw).strip()
                                ).casefold()
                                name_cf = str(name_raw or '').strip().casefold()
                                if name_cf:
                                    norm_subj.add((dom_cf, name_cf))
                            else:
                                norm_subj.add(('default', raw.casefold()))

                    if (pk_domain_cf, pk_name_cf) in norm_subj:
                        return True

                # Exact users/groups/dynamic-groups
                if ptype == 'user' and 'exact_users' in subj_filter:
                    targets = subj_filter['exact_users']
                elif ptype == 'group' and 'exact_groups' in subj_filter:
                    targets = subj_filter['exact_groups']
                elif ptype == 'dynamic-group' and 'exact_dynamic_groups' in subj_filter:
                    targets = subj_filter['exact_dynamic_groups']
                else:
                    targets = []

                if targets:
                    # Normalize prospective subjects to (domain, name) tuples
                    norm_subj_targets: set[tuple[str | None, str]] = set()
                    for s in subjects:
                        if isinstance(s, (tuple | list)) and len(s) == 2:
                            domain, name = s
                            dom_norm = str(domain).lower() if domain else 'default'
                            norm_subj_targets.add((dom_norm, str(name).lower()))
                    for t in targets:
                        dom = str(t.get('domain_name') or 'default').lower()
                        name = str(
                            t.get('user_name') or t.get('group_name') or t.get('dynamic_group_name') or ''
                        ).lower()
                        if (dom, name) in norm_subj_targets:
                            return True
                return False

            for pst in self._prospective_statements:
                if pst.get('parsed') is False or pst.get('valid') is False:
                    continue
                # Use the same scope semantic as regular statements: effective_path.
                # Fall back to compartment_path for older prospective payloads.
                pst_comp = str(pst.get('effective_path') or pst.get('compartment_path') or '').strip()
                comp_path_cmp = comp_path.lower()
                pst_comp_cmp = pst_comp.lower()
                # Simple prefix/equals check: ROOT/Finance applies to ROOT/Finance/Payables
                if not pst_comp_cmp or not (
                    comp_path_cmp == pst_comp_cmp or comp_path_cmp.startswith(pst_comp_cmp + '/')
                ):
                    continue
                # Now enforce principal/subject match
                if _prospective_matches_principal(pst):
                    logger.info(
                        'get_applicable_statements: including prospective statement internal_id=%r policy_name=%r for principal_key=%s at path=%s',
                        pst.get('internal_id'),
                        pst.get('policy_name'),
                        principal_key,
                        effective_path,
                    )
                    merged.append(pst)
                else:
                    logger.info(
                        'get_applicable_statements: prospective statement internal_id=%r policy_name=%r did NOT match principal_key=%s (skipped)',
                        pst.get('internal_id'),
                        pst.get('policy_name'),
                        principal_key,
                    )

        logger.info(
            'get_applicable_statements: returning %d statements (%d base, %d prospective)',
            len(merged),
            len(base_stmts),
            max(0, len(merged) - len(base_stmts)),
        )
        return merged

    def get_required_where_fields(self, statements: list[dict]) -> set[str]:
        """
        Extract all unique "where clause" input field names needed by a set of policy statements.

        Args:
            statements (list[dict]): The statements to examine for conditional/where fields.

        Returns:
            set[str]: Set of all unique field names required as variables for condition evaluation.

        Example:
            >>> fields = engine.get_required_where_fields(statements)
            >>> print(fields)  # e.g. {'request.time', 'user.department'}
        """
        fields = set()
        for stmt in statements:
            logger.info(
                f"Processing statement for required fields: {stmt.get('statement_text', '')}. Conditions: {stmt.get('conditions')}"
            )
            cond = stmt.get('conditions') or None
            if cond:
                logger.info(
                    f"Extracting fields from condition dict: {cond}.  Statement: {stmt.get('statement_text', '')}"
                )
                # Placeholder: Here we extract field names used in where clause
                # Use the canonical extraction path for all conditions
                self.extract_variable_names(str(cond))
                fields.update(self.extract_variable_names(str(cond)))
                logger.info(f"Extracted fields from statement: {stmt.get('statement_text', '')} -> {fields}")
        return fields

    def generate_where_clauses_for_statements(self, statements: list[dict]) -> dict:
        """
        Utility: Generate a mapping from statement internal_id to set of where-variable names required
        (for UI preview purposes).

        Args:
            statements (list[dict]): Statements to analyze.

        Returns:
            dict: {internal_id: set(field names)} for statements that have where conditions.
        """
        result = {}
        for stmt in statements:
            cond = stmt.get('conditions')
            if cond:
                fields = self.get_required_where_fields([stmt])
                if fields:
                    result[stmt.get('internal_id')] = fields
        return result

    @staticmethod
    def _normalize_timestring(value: str) -> str:
        """
        Ensures ISO format time strings use uppercase 'T' and 'Z'.
        """
        import re

        iso_dt_pattern = r'^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.\d+)?([Zz]|[+\-]\d{2}:?\d{2})?$'
        if isinstance(value, str):
            m = re.match(iso_dt_pattern, value)
            if m:
                date, time, tz = m.group(1), m.group(2), m.group(3)
                new_v = f'{date}T{time}'
                if tz:
                    new_v += tz.upper() if tz.lower() == 'z' else tz
                return new_v
        return value

    @classmethod
    def _normalize_where_context_times(cls, where_context: dict) -> dict:
        """
        Returns new where_context with all string ISO date fields normalized.
        """
        norm = {}
        for k, v in where_context.items():
            if isinstance(v, str):
                norm[k] = cls._normalize_timestring(v)
            elif isinstance(v, dict):
                norm[k] = cls._normalize_where_context_times(v)
            else:
                norm[k] = v
        return norm

    def _evaluate_conditions(  # noqa: C901
        self,
        cond,
        where_context: dict,
        *,
        return_structured: bool = False,
    ) -> tuple[bool, str] | tuple[bool, dict]:
        """
        Evaluate 'where' clause (condition) string or dict against a context of variables (where_context).
        Uses reusable WhereClauseEvaluator visitor, with extended logging.

        Returns:
            (passed: bool, reason: str)
              - passed: True if conditions grant access, otherwise False.
              - reason: Explanation of result or failure.
        """

        logger.info('Starting _evaluate_conditions.')
        logger.debug(f'Input: cond={cond}, where_context={where_context}')
        return evaluate_condition_clause(cond, where_context, return_structured=return_structured)
