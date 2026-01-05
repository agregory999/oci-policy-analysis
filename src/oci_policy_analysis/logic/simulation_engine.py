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

from antlr4 import CommonTokenStream, InputStream

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionLexer import OciIamPolicyConditionLexer
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionParser import OciIamPolicyConditionParser
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionVisitor import OciIamPolicyConditionVisitor
from oci_policy_analysis.logic.parsers.condition_parser.WhereClauseEvaluator import evaluate_where_clause

logger = get_logger(component='policy_simulation_engine')


class PolicySimulationEngine:
    """
    Central simulation service for OCI policies.

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

    @staticmethod
    def extract_variable_names(cond_str):
        """
        Extract variable names from a policy condition string using the OCI IAM Policy Condition parser.

        Args:
            cond_str (str): The condition string to analyze.

        Returns:
            set[str]: A set of variable names (as strings) present in the condition clause.
        """
        input_stream = InputStream(cond_str + '\n')
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = OciIamPolicyConditionParser(stream)
        tree = parser.condition_clause()

        class VarCollector(OciIamPolicyConditionVisitor):
            def __init__(self):
                self.vars = set()

            def visitVariable_name(self, ctx):
                self.vars.add(ctx.getText())

            def visitTerminal(self, node):
                if hasattr(node, 'symbol') and hasattr(node.symbol, 'type'):
                    if node.symbol.type == OciIamPolicyConditionLexer.IDENTIFIER and '.' in node.getText():
                        self.vars.add(node.getText())
                        logger.debug(f'Extracted variable: {node.getText()}')
                return None

        collector = VarCollector()
        collector.visit(tree)
        return collector.vars

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
            compartment_principal_index (dict): Mapping from compartment path to principal key to statements.
            any_user_statements (dict): Mapping from compartment path to 'any-user' statements.
            internal_state (dict): Diagnostic/debug state.
            simulation_history (list): Simulation log/history, used for GUI trace table, etc.
        """
        logger.info(
            f'PolicySimulationEngine initialized with {len(policy_repo.regular_statements) if policy_repo else 0} policy statements'
        )
        self.policy_statements = policy_repo.regular_statements if policy_repo else []
        self.ref_data_repo = ref_data_repo
        # Structure: {effective_path: {principal_key: [statement, ...], ...}, ...}
        self.compartment_principal_index: dict[str, dict[str, list[dict]]] = {}
        # Separate index for 'any-user' statements per compartment
        self.any_user_statements: dict[str, list[dict]] = {}
        # Create a JSON to hold internal state for debug and tracing
        self.internal_state: dict[str, Any] = {}
        self.internal_state['total_statements'] = len(self.policy_statements)
        # Simulation log/history: list of dicts, one per simulation run
        self.simulation_history: list[dict[str, Any]] = []

    def simulate_and_record(  # noqa: C901
        self,
        principal_key: str,
        effective_path: str,
        api_operation: str,
        where_context: dict,
        checked_statement_ids: list[str],
        trace_name: str | None = None,
        trace: bool = False,
    ) -> dict[str, Any]:
        """
        Simulates permissions for a principal, compartment, and operation, recording full trace/results.

        Args:
            principal_key (str): The unique principal key (e.g., "group:default/Admins") for the simulation.
            effective_path (str): The effective compartment path for simulation.
            api_operation (str): The API operation to check permission for.
            where_context (dict): Input/context for any evaluated 'where' policy clauses.
            checked_statement_ids (list[str]): List of policy statement internal_ids to include in simulation.
            trace_name (str, optional): Optional name for this simulation trace/history.
            trace (bool, optional): If True, includes detailed step-by-step trace; else, summary only.

        Returns:
            dict[str, Any]: Full simulation result with yes/no, permissions, missing/revoked, per-statement decision trace,
                and trace object suitable for history review.

        Example:
            result = engine.simulate_and_record('group:default/Admins', 'ROOT', 'oci:ListBuckets', {}, checked_ids, trace=True)
        """
        logger.info(
            f"Simulating permissions for principal={principal_key}, compartment={effective_path}, operation={api_operation}. Statements: {len(checked_statement_ids)} selected. Trace={'ON' if trace else 'OFF'}"
        )
        trace_obj = {}
        perm_set = set()
        statement_trace = []
        permissions_denied = []

        allow_statements = []
        deny_statements = []
        all_stmt_map = {s.get('internal_id'): s for s in self.policy_statements}
        for internal_id in checked_statement_ids:
            stmt = all_stmt_map.get(internal_id)
            if not stmt:
                logger.warning(f'Statement ID {internal_id} not found in repo. Skipped.')
                continue
            if stmt.get('action', 'allow').lower() == 'deny':
                deny_statements.append((internal_id, stmt))
            else:
                allow_statements.append((internal_id, stmt))

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
            passed = True
            fail_reason = ''
            if stmt.get('conditions'):
                logger.debug(f"Evaluating conditions for allow stmt: {stmt.get('statement_text', '')}")
                passed, fail_reason = self._evaluate_conditions(stmt.get('conditions'), where_context)
                if not passed:
                    stmt_entry['passed'] = False
                    stmt_entry['fail_reason'] = fail_reason or 'Condition(s) did not pass'
                    statement_trace.append(stmt_entry)
                    continue
            direct_perms = stmt.get('permission', [])
            resource_perms = (
                self.ref_data_repo.get_permissions(stmt.get('resource'), stmt.get('verb'), action='allow')
                if self.ref_data_repo
                else []
            )
            all_perms = list(direct_perms or []) + list(resource_perms or [])
            if all_perms:
                logger.debug(
                    f"Adding permissions from ALLOW: {all_perms} for statement: {stmt.get('statement_text', '')}"
                )
            for p in all_perms:
                perm_set.add(p)
            stmt_entry['permissions'] = all_perms
            statement_trace.append(stmt_entry)

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
            deny_this = set(direct_perms or []) | set(resource_perms or [])
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
        if trace:
            trace_obj['trace_statements'] = statement_trace
        else:
            # Omit per-statement trace in summary mode; just include statement count or basic ref
            trace_obj['trace_statements'] = []

        trace_obj['final_permission_set'] = sorted(perm_set)
        trace_obj['permissions_denied'] = permissions_denied

        logger.debug(f'Final permissions: {sorted(perm_set)} for {principal_key} in {effective_path}')

        # Operation simulation/check
        has_permission = (
            self.ref_data_repo.has_api_operation_permissions(api_operation, perm_set) if self.ref_data_repo else False
        )
        # Collect required permissions for API operation (empty if not found)
        required = []
        missing = set()
        if self.ref_data_repo:
            required = self.ref_data_repo.data.get('operations', {}).get(api_operation, {}).get('permissions', [])
            missing = {p.upper() for p in required if p.upper() not in perm_set}

        trace_obj['required_permissions_for_api_operation'] = sorted([p.upper() for p in required])

        sim_result = {
            'result': 'YES' if has_permission else 'NO',
            'api_call_allowed': has_permission,
            'final_permission_set': sorted(perm_set),
            'required_permissions_for_api_operation': sorted([p.upper() for p in required]),
            'missing_permissions': sorted(missing),
            'failure_reason': '' if has_permission else f'Missing required permissions: {sorted(missing)}',
            # The detail returned depends on trace: basic=trace_statements is [], trace=full per-statement trace
            'trace_statements': statement_trace if trace else [],
            'trace': trace_obj,  # always include for legacy UI code
        }
        # Record to history with name and timestamp
        entry = {
            'name': trace_name or f"Simulation {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'trace': sim_result,
        }
        self.simulation_history.append(entry)
        return sim_result

    def get_simulation_trace_list(self) -> list[dict[str, str]]:
        """
        Get the list of names and timestamps for all recorded simulation traces.

        Returns:
            list[dict[str, str]]: List of dictionaries with keys 'name' and 'timestamp'
                corresponding to each simulation history entry.

        Example:
            [{'name': 'Simulation 1', 'timestamp': '2026-01-05T14:00:01'}, ...]
        """
        return [{'name': entry['name'], 'timestamp': entry['timestamp']} for entry in self.simulation_history]

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

    def build_index(self):
        """
        Build internal indexes for fast policy simulation lookup.

        Creates mappings:
          - compartment_principal_index: compartment path -> principal_key -> [statements]
          - any_user_statements: compartment path -> statements with subject_type 'any-user'

        Returns:
            None

        Example:
            engine.build_index()
        """
        count = 0
        any_user_count = 0
        for stmt in self.policy_statements:
            path = stmt.get('effective_path', 'UNKNOWN')
            subject_type = stmt.get('subject_type', '')
            subjects = stmt.get('subject', [])
            if not isinstance(subjects, list):
                subjects = [subjects]
            for subject_domain, subject_name in subjects:
                principal_key = f'{subject_type}:{subject_domain}/{subject_name}'
                if subject_type.lower() == 'any-user':
                    self.any_user_statements.setdefault(path, []).append(stmt)
                    any_user_count += 1
                else:
                    if path not in self.compartment_principal_index:
                        self.compartment_principal_index[path] = {}
                    if principal_key not in self.compartment_principal_index[path]:
                        self.compartment_principal_index[path][principal_key] = []
                    self.compartment_principal_index[path][principal_key].append(stmt)
                    count += 1
        logger.info(
            f'PolicySimulationEngine index built: {count} principal-path combos, {any_user_count} any-user entries'
        )

    def get_applicable_statements(self, principal_key: str, effective_path: str) -> list[dict]:
        """
        Get all applicable policy statements for a principal in a compartment.

        Args:
            principal_key (str): The principal key (e.g., "group:default/Admins").
            effective_path (str): The compartment (path) in which to evaluate applicability.

        Returns:
            list[dict]: List of matching policy statements for principal + compartment combination,
                including any statements for 'any-user'.

        Example:
            statements = engine.get_applicable_statements('group:default/Admins', 'ROOT')
        """
        applicable = []
        # All statements for explicit principal
        principal_map = self.compartment_principal_index.get(effective_path, {})
        applicable += principal_map.get(principal_key, [])
        # All any-user statements for this path
        applicable += self.any_user_statements.get(effective_path, [])
        return applicable

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
            cond = stmt.get('conditions')
            if cond and isinstance(cond, dict):
                # Placeholder: Here we extract field names used in where clause
                # TODO: Integrate/port logic to parse/extract fields as per existing where handler
                fields.update(self._extract_fields_from_conditions(cond))
                logger.info(f"Extracted fields from statement: {stmt.get('statement_text', '')} -> {fields}")
        return fields

    def _extract_fields_from_conditions(self, cond: dict) -> set[str]:
        """
        Parse a condition dict and return all input field names needed.
        Placeholder for actual where clause field extraction logic.
        """
        # TODO: Implement or port actual logic from condition parser/helpers.
        return set()  # Placeholder

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

    def _evaluate_conditions(self, cond, where_context: dict) -> tuple[bool, str]:  # noqa: C901
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
        # Defensive: Normalize ISO times for all where_context entries before evaluating
        where_context = self._normalize_where_context_times(where_context)
        # Normalize/extract the clause string
        if isinstance(cond, dict):
            # Try to find a clause string field
            condition_str = None
            for k in ('where_clause', 'condition_string', 'clause', 'string'):
                if k in cond:
                    condition_str = cond[k]
                    break
            # Fallback: first string value, else to str(cond)
            if not condition_str:
                for v in cond.values():
                    if isinstance(v, str):
                        condition_str = v
                        break
            if not condition_str:
                condition_str = str(cond)
        elif isinstance(cond, str):
            condition_str = cond
        else:
            condition_str = str(cond)

        logger.info(f'Parsed condition string for evaluation: {condition_str}')
        try:
            result_bool, log = evaluate_where_clause(condition_str, where_context)
            logger.info(f'Where clause evaluated to: {result_bool}')
        except Exception as ex:
            logger.error(f'Exception during where clause evaluation: {ex}')
            result_bool, log = (
                False,
                [
                    {
                        'type': 'Exception',
                        'result': False,
                        'variable': '?',
                        'operator': '?',
                        'sim_value': '?',
                        'expected': '?',
                        'info': str(ex),
                    }
                ],
            )

        # Compose reason string from log or result
        reason_lines = []
        if log:
            if isinstance(log, str):
                reason_lines.append(log)
            elif isinstance(log, list):
                # Try to extract interesting info from structured log objects
                for entry in log:
                    if isinstance(entry, dict):
                        msg = entry.get('info') or entry.get('result') or str(entry)
                        reason_lines.append(str(msg))
                    else:
                        reason_lines.append(str(entry))
        reason = '; '.join([line for line in reason_lines if line])
        # Include status
        if result_bool is True:
            status = 'GRANTED'
        else:
            status = 'DENIED'
        if not reason:
            reason = f'Policy Result: {status}'
        else:
            reason = f'Policy Result: {status}. Details: {reason}'
        logger.info(f'Returning evaluation result: {status} with reason: {reason}')
        return result_bool, reason
