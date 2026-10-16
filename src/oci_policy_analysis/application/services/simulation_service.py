"""Service facade for policy simulation workflows."""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.condition_tester_service import (
    ConditionTesterService,
    extract_condition_clause,
)


@dataclass
class SimulationPrepareResult:
    """Prepared principal identity and request fields needed for simulation.

    Attributes:
        principal_key: Resolved canonical identity used by the simulation engine.
        required_where_fields: Sorted condition-variable names to supply in request context.
    """

    principal_key: str
    required_where_fields: list[str]


class SimulationService:
    """Prepare and evaluate requests against the active analysis model.

    Args:
        context: Enriched runtime containing the simulation engine.

    Attributes:
        context: Shared runtime whose current simulation engine is used per call.
        logger: Component logger for preparation and execution diagnostics.

    Notes:
        Preparation and execution may update engine state and record results.
        Supply request-context values for applicable conditions. Results describe
        the tool's model of the snapshot, not decisions by OCI's policy engine.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the simulation service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='application.services.simulation')

    def environment_options(self) -> dict[str, Any]:
        """List known environment choices without preparing or evaluating policies.

        Returns:
            dict[str, Any]: Compartment paths and principal choices grouped by
            type. Each choice includes a display label, engine input and canonical
            key. Inventory and retained source references are combined; their
            presence does not establish evaluation eligibility or complete coverage.

        Notes:
            Reads the current snapshot and prospective records without modifying
            engines, history, source evidence or cache files. Users are offered
            only when user inventory was collected.
        """
        repo = self.context.policy_repo
        choices: dict[str, dict[str, dict]] = {}

        def add(kind, domain, name):
            if not isinstance(name, str) or not name.strip():
                return
            if domain is not None and not isinstance(domain, str):
                return
            key = calculate_principal_key(kind, domain, name)
            named = kind in {'user', 'group', 'dynamic-group'}
            choices.setdefault(kind, {}).setdefault(
                key,
                {
                    'label': f'{domain or "Default"}/{name}' if named else name,
                    'principal': (domain, name) if named else name,
                    'principal_key': key,
                },
            )

        for kind, collection, name_field in (
            ('user', 'users', 'user_name'),
            ('group', 'groups', 'group_name'),
            ('dynamic-group', 'dynamic_groups', 'dynamic_group_name'),
        ):
            for record in getattr(repo, collection, []) or []:
                add(kind, record.get('domain_name'), record.get(name_field))
        for statement in [
            *repo.regular_statements,
            *self.context.simulation.get_prospective_statements(),
        ]:
            kind = statement.get('subject_type')
            if kind not in {'group', 'dynamic-group', 'service', 'group-id', 'dynamic-group-id'}:
                continue
            for subject in statement.get('subject') or []:
                if isinstance(subject, str):
                    add(kind, None, subject)
                elif isinstance(subject, list | tuple) and len(subject) == 2:
                    add(kind, subject[0], subject[1])
        add('any-user', None, 'any-user')
        add('any-group', None, 'any-group')
        return {
            'compartment_paths': sorted(
                {row['hierarchy_path'] for row in repo.compartments if row.get('hierarchy_path')}
            ),
            'principals': {
                kind: sorted(records.values(), key=lambda row: row['label'].casefold())
                for kind, records in sorted(choices.items())
            },
        }

    def statement_candidates(
        self, *, compartment_path: str, principal_type: str, principal: object | None
    ) -> dict[str, Any]:
        """Discover applicable source evidence and corpus-backed selection eligibility.

        Args:
            compartment_path: Effective compartment selected for the request.
            principal_type: Engine-supported principal type.
            principal: Identity string, domain/name pair or wildcard value.

        Returns:
            dict[str, Any]: Canonical principal_key and detached statements with
            source_kind, checkable and selection_reason fields. Invalid prospective
            drafts are retained separately with scope explicitly unverified.

        Raises:
            ValueError: Conflicting records share an ID, making inclusion ambiguous.

        Notes:
            Uses engine matching and corpus admission; does not evaluate conditions
            or record history. Legacy principal lookup enriches detached records.
            Callers must serialize preparation with snapshot and prospective mutation
            so all inputs represent the same snapshot.
            No source records or cache files are rewritten.
        """
        self.logger.info(
            'Statement preparation started: compartment=%s principal_type=%s principal=%s',
            compartment_path,
            principal_type,
            principal,
        )

        def deduplicate(entries, stage):
            unique, seen = [], {}
            duplicates = 0
            for statement, origin in entries:
                key = str(statement.get('internal_id') or '')
                if key and key in seen:
                    previous, previous_origin = seen[key]
                    if previous_origin != origin or previous != statement:
                        fields = sorted(
                            field
                            for field in previous.keys() | statement.keys()
                            if (field in previous) != (field in statement)
                            or previous.get(field) != statement.get(field)
                        )
                        self.logger.info(
                            'Duplicate statement ID conflict: stage=%s id=%s origins=%s/%s differing_fields=%s',
                            stage,
                            key,
                            previous_origin,
                            origin,
                            fields,
                        )
                        raise ValueError(
                            f'Duplicate statement ID: {key} has conflicting records. '
                            'See simulation logs for the source stage and differing fields.'
                        )
                    duplicates += 1
                    self.logger.info(
                        'Collapsed identical duplicate statement: stage=%s id=%s source=%s policy=%s path=%s',
                        stage,
                        key,
                        origin if stage == 'source' else ('Unverified draft' if origin else 'Applicable'),
                        statement.get('policy_name'),
                        statement.get('compartment_path'),
                    )
                    continue
                if key:
                    seen[key] = (statement, origin)
                unique.append((statement, origin))
            self.logger.info(
                'Statement preparation counts: stage=%s records=%d unique=%d duplicates=%d',
                stage,
                len(entries),
                len(unique),
                duplicates,
            )
            return unique

        engine = copy(self.context.simulation)
        engine.policy_repo = copy(self.context.policy_repo)
        engine.policy_repo.regular_statements = deepcopy(self.context.policy_repo.regular_statements)
        prospective = engine.get_prospective_statements()
        sources = deduplicate(
            [
                *((row, 'Collected') for row in engine.policy_repo.regular_statements),
                *((row, 'Prospective') for row in prospective),
            ],
            'source',
        )
        engine.policy_repo.regular_statements = [row for row, kind in sources if kind == 'Collected']
        prospective = [row for row, kind in sources if kind == 'Prospective']
        principal_key, statements = engine.get_statements_for_context(compartment_path, principal_type, principal)
        corpus = engine.get_corpus(include_prospective=True)
        admitted = {fact.provenance.statement_id for fact in corpus.facts} if corpus else set()
        excluded = {item.statement_id: item.reason for item in corpus.exclusions} if corpus else {}
        self.logger.info(
            'Statement preparation corpus: principal_key=%s applicable_rows=%d facts=%d admitted_statement_ids=%d exclusions=%d',
            principal_key,
            len(statements),
            len(corpus.facts) if corpus else 0,
            len(admitted),
            len(excluded),
        )
        drafts = [row for row in prospective if row.get('valid') is False or row.get('parsed') is False]
        prospective_ids = {str(row.get('internal_id')) for row in prospective}
        rows = []
        candidates = deduplicate(
            [*((row, False) for row in statements), *((row, True) for row in drafts)], 'candidates'
        )
        for statement, unverified in candidates:
            row = deepcopy(statement)
            key = str(row.get('internal_id') or '')
            draft = row.get('valid') is False or row.get('parsed') is False
            reason = excluded.get(key, '')
            if draft and not reason:
                reason = 'Invalid or unparsed source statement.'
            if not key:
                reason = 'Missing stable statement ID.'
            if not reason and key not in admitted:
                reason = 'No evaluable permission facts in the loaded corpus.'
            row.update(
                source_kind='Prospective' if key in prospective_ids else 'Collected',
                checkable=not reason,
                selection_reason=(f'Unverified scope · {reason}' if unverified else reason)
                or 'Eligible · Conditions still require request context.',
                scope_status='Unverified draft' if unverified else 'Applicable in model',
            )
            rows.append(row)
        self.logger.info(
            'Statement preparation complete: candidates=%d eligible=%d excluded=%d',
            len(rows),
            sum(row['checkable'] for row in rows),
            sum(not row['checkable'] for row in rows),
        )
        return {'principal_key': principal_key, 'statements': rows}

    def request_context_schema(self, statements: list[dict[str, Any]]) -> dict[str, Any]:
        """Discover condition inputs and diagnostics on prepared statement copies.

        Args:
            statements: Eligible candidate records to inspect without evaluation.

        Returns:
            dict[str, Any]: Sorted variables and per-statement clauses, variables,
            parse status and warnings. Unsupported clauses retain their source
            text and diagnostics instead of silently becoming unconditional grants.

        Notes:
            Reads conditions without changing source records or engine history.
            Consumers may project these schemas onto an explicit checked-ID subset.
        """
        tester = ConditionTesterService()
        conditions = []
        variables = set()
        for statement in statements:
            condition = ''
            for field in ('where_clause', 'conditions_where_clause', 'conditions'):
                value = statement.get(field) or ''
                if isinstance(value, dict):
                    value = value.get('raw_text') or ''
                if str(value).strip():
                    condition = str(value)
                    break
            clause = extract_condition_clause(str(condition), statement.get('statement_text') or '')
            if not clause:
                continue
            parsed = tester.parse_clause(clause)
            variables.update(parsed['variables'])
            conditions.append(
                {
                    'internal_id': str(statement.get('internal_id') or ''),
                    'clause': clause,
                    'variables': parsed['variables'],
                    'parse_status': parsed['structure']['parse_status'],
                    'warnings': parsed['structure']['warnings'],
                }
            )
        self.logger.info(
            'Request context schema prepared: statements=%d conditions=%d variables=%d unsupported=%d',
            len(statements),
            len(conditions),
            len(variables),
            sum(row['parse_status'] != 'parsed' for row in conditions),
        )
        return {'variables': sorted(variables), 'conditions': conditions}

    def prepare(
        self, *, compartment_path: str, principal_type: str, principal: object | None
    ) -> SimulationPrepareResult:
        """Prepare simulation context for a principal/compartment pairing.

        Args:
            compartment_path: Target compartment path.
            principal_type: Principal type value expected by simulation engine.
            principal: Principal object used for context resolution.

        Returns:
            SimulationPrepareResult: Principal key and required where-fields.
        """
        self.logger.info(
            'Preparing simulation context: compartment=%s principal_type=%s',
            compartment_path,
            principal_type,
        )
        engine = self.context.simulation
        principal_key, required_where_fields = engine.get_required_where_fields_for_context(
            compartment_path, principal_type, principal
        )
        return SimulationPrepareResult(
            principal_key=principal_key,
            required_where_fields=sorted(required_where_fields),
        )

    def run(
        self,
        *,
        principal_key: str,
        compartment_path: str,
        api_operation: str,
        where_context: dict[str, Any],
        checked_statement_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a policy simulation and record decision details.

        Args:
            principal_key: Resolved simulation principal key.
            compartment_path: Effective path used for simulation.
            api_operation: API operation being evaluated.
            where_context: Resolved where-clause context values.
            checked_statement_ids: Optional set of specific statement IDs to evaluate.

        Returns:
            dict[str, Any]: Simulation output payload.
        """
        self.logger.info(
            'Running simulation: principal_key=%s compartment=%s api_operation=%s',
            principal_key,
            compartment_path,
            api_operation,
        )
        engine = self.context.simulation
        return engine.simulate_and_record(
            principal_key=principal_key,
            effective_path=compartment_path,
            api_operation=api_operation,
            where_context=where_context,
            checked_statement_ids=checked_statement_ids,
        )
