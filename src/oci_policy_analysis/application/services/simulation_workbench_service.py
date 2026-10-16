"""Explain simulation runs and prepare reviewable what-if policy candidates."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from oci_policy_analysis.application.core.common.policy_helpers import canonicalize_principal_key
from oci_policy_analysis.application.core.parser import evaluate_condition_clause
from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService
from oci_policy_analysis.application.services.prospective_builder_service import ProspectiveBuilderService
from oci_policy_analysis.application.services.simulation_service import SimulationService


class SimulationWorkbenchService:
    """Build snapshot-bound explanations, related requests and grant candidates.

    Args:
        context: Loaded AppContext, serialized by the caller during execution.

    Notes:
        Execution records engine history. Other methods are read-only. Candidates
        are validated local drafts, not OCI changes or guarantees of access.
        Reverse mappings use bundled reference data; corpus facts supply retained
        provenance, not an authoritative decision or a complete OCI permission map.
    """

    def __init__(self, context):
        """Retain the current runtime without loading data or writing storage."""
        self.context = context
        self.simulation = SimulationService(context)

    def _snapshot_id(self):
        engine = self.context.simulation
        if not hasattr(engine, '_workbench_snapshot_id'):
            engine._workbench_snapshot_id = str(uuid4())
        return engine._workbench_snapshot_id

    def execute(self, request: dict) -> dict:
        """Validate explicit inclusion, execute and retain the original run inputs.

        Args:
            request: Environment, qualified operation, explicit checked IDs and
                condition values from the request screen. An empty ID list stays empty.

        Returns:
            dict: Immutable-by-convention request/result evidence with permission
            rows, condition comparisons, findings and related scenario choices.

        Raises:
            ValueError: Unknown operation, stale environment or ineligible IDs.
        """
        request = deepcopy(request)
        prepared = self.simulation.statement_candidates(
            compartment_path=request['compartment_path'],
            principal_type=request['principal_type'],
            principal=request['principal'],
        )
        if prepared['principal_key'] != request['principal_key']:
            raise ValueError('Principal identity changed; prepare the request again.')
        ids = request.get('checked_statement_ids')
        if not isinstance(ids, list):
            raise ValueError('Execution requires an explicit checked statement list, including [] for none.')
        ids = list(dict.fromkeys(str(key) for key in ids))
        request['checked_statement_ids'] = ids
        eligible = {str(row['internal_id']) for row in prepared['statements'] if row['checkable']}
        if set(ids) - eligible:
            raise ValueError('Some included statements are no longer eligible; prepare statements again.')
        operation = self.context.reference_data.resolve_operation(request['api_operation'])
        metadata = self.context.reference_data.data['operations'].get(operation)
        if not metadata:
            raise ValueError('Choose a known API operation from the reference catalog.')
        request['api_operation'] = operation
        request['where_context'] = dict(request.get('where_context') or {})
        request['where_context']['request.operation'] = metadata.get('request_operation') or metadata.get(
            'operation_name', operation
        )
        selected = [row for row in prepared['statements'] if str(row.get('internal_id')) in ids]
        schema = self.simulation.request_context_schema(selected)
        result = self.simulation.run(
            principal_key=request['principal_key'],
            compartment_path=request['compartment_path'],
            api_operation=operation,
            where_context=request['where_context'],
            checked_statement_ids=ids,
        )
        trace = result['simulation_trace']
        denied = {
            permission
            for row in trace['trace_statements']
            if row['action'] == 'deny' and row['passed']
            for permission in row['permissions']
        }
        missing = set(result['missing_permissions'])
        permissions = [
            {
                'permission': permission,
                'status': 'Denied by statement'
                if permission in denied
                else 'Missing grant'
                if permission in missing
                else 'Granted',
            }
            for permission in result['required_permissions_for_api_operation']
        ]
        comparisons = []
        for row in selected:
            if row.get('conditions'):
                _passed, evaluated = evaluate_condition_clause(
                    row['conditions'], request['where_context'], return_structured=True
                )
                comparisons.extend(
                    {**item, 'internal_id': row['internal_id'], 'statement_text': row['statement_text']}
                    for item in evaluated['Log']
                )
        findings = []
        if not ids:
            findings.append('No statements were included. Check Statements before adding a grant.')
        if denied & missing:
            findings.append(
                'A matching deny covers missing permissions. An additional allow cannot override that deny.'
            )
        failed = [row for row in trace['trace_statements'] if not row['passed']]
        if failed:
            findings.append(
                f'{len(failed)} statement conditions did not pass. Review the supplied values and condition comparisons before broadening access.'
            )
        unsupplied = sorted(set(schema['variables']) - request['where_context'].keys())
        if unsupplied:
            findings.append('Values not supplied (absence may be intentional): ' + ', '.join(unsupplied))
        unsupported = [row for row in schema['conditions'] if row['parse_status'] != 'parsed']
        if unsupported:
            findings.append('Some conditions are unsupported. The model outcome has incomplete condition coverage.')
        excluded = sum(not row['checkable'] for row in prepared['statements'])
        if excluded:
            findings.append(
                f'{excluded} candidate records were ineligible. Review their exclusion reasons in Statements.'
            )
        if not result['required_permissions_for_api_operation']:
            findings.append(
                'No primary permission mapping is listed for this operation. An empty mapping does not establish OCI access.'
            )
        if missing and not denied & missing:
            findings.append(
                'No included, passing grant supplies all required permissions. Review scope and unchecked statements, then consider a local what-if policy.'
            )
        report = {
            'request': request,
            'result': deepcopy(result),
            'permissions': permissions,
            'findings': findings,
            'comparisons': comparisons,
            'condition_schema': schema,
            'selected_statements': deepcopy(selected),
            'timestamp': datetime.now(UTC).isoformat(timespec='seconds'),
            'snapshot': {
                'runtime_id': self._snapshot_id(),
                'tenancy_ocid': self.context.policy_repo.tenancy_ocid,
                'data_as_of': getattr(self.context.policy_repo, 'data_as_of', None),
            },
            'related_scenarios': self.related_scenarios(operation),
        }
        # The engine append and enrichment are serialized by the owning worker.
        self.context.simulation.simulation_history[-1]['workbench_report'] = deepcopy(report)
        return report

    def history(self) -> list[dict]:
        """Return detached history for the current snapshot, including legacy runs.

        Returns:
            list[dict]: Original engine runs with optional workbench_report evidence.
            Snapshot replacement creates a fresh engine and history; no cache is written.
        """
        return deepcopy(self.context.simulation.simulation_history)

    def related_scenarios(self, operation: str) -> list[dict]:
        """Resolve advisory dependencies into valid catalog operation choices.

        Args:
            operation: Qualified or unambiguous reference operation name.

        Returns:
            list[dict]: Canonical operation labels, applicability and dependency
            permissions. The caller must select a target path and reload statements.
            Unknown/ambiguous operation names are not presented as executable choices.
        """
        reference = self.context.reference_data_service
        detail = reference.get_operation_detail(operation)
        catalog = reference.list_operations_with_permissions()
        rows, seen = [], set()
        for check in detail['related_checks']:
            choices = []
            explicit = str(check.get('operation') or '')
            if explicit:
                qualified = explicit if ':' in explicit else operation.split(':', 1)[0] + ':' + explicit
                choices = [row for row in catalog if row['label'] == qualified]
            if not choices and check.get('permissions'):
                needed = set(check['permissions'])
                choices = sorted(
                    [row for row in catalog if needed <= set(row['permissions']) and row['label'] != operation],
                    key=lambda row: (len(set(row['permissions']) - needed), row['label']),
                )[:5]
            for row in choices:
                if row['label'] in seen:
                    continue
                seen.add(row['label'])
                rows.append(
                    {
                        'api_operation': row['label'],
                        'resource': check['resource'],
                        'permissions': check['permissions'],
                        'operation_permissions': row['permissions'],
                        'applies_when': check.get('applies_when', ''),
                        'reason': check.get('reason')
                        or check.get('failure_hint')
                        or 'Review this dependency in the related resource compartment.',
                    }
                )
        return rows

    def suggestion_metadata(self) -> dict:
        """Return supported grant principals and paths for explicit user choices.

        Returns:
            dict: Shared builder choices filtered to OCI grant principal types.
            User simulations require choosing a grant-bearing group or other principal.
        """
        builder = ProspectiveBuilderService(
            self.context.policy_repo, self.context.reference_data, self.context.simulation
        )
        metadata = builder.get_builder_metadata()
        metadata['principals'] = [
            key
            for key in metadata['principals']
            if metadata['principal_details'][key]['type']
            in {'group', 'dynamic-group', 'group-id', 'dynamic-group-id', 'service', 'any-user', 'any-group'}
        ]
        return metadata

    def policy_candidates(
        self,
        report: dict,
        *,
        principal_key: str,
        granularity: str,
        effective_path: str,
        policy_path: str = 'ROOT',
        where_clause: str = '',
    ) -> dict:
        """Reverse missing permissions into validated, explicitly scoped policy drafts.

        Args:
            report: Prior run evidence; only its missing primary permissions are used.
            principal_key: Explicit grant principal from suggestion_metadata.
            granularity: permission, resource, or family. Resource/family drafts may
                grant additional catalog permissions, which are listed separately.
            effective_path: User-selected target path, including descendant inheritance.
            policy_path: Ancestor compartment where the hypothetical policy is stored.
            where_clause: Optional custom condition expression, without where keyword.

        Returns:
            dict: Validated candidates, unmapped permissions, corpus evidence and
            limitations. Multiple statements may be needed; each candidate carries
            its covered and additional permissions and source mapping.

        Raises:
            ValueError: Unsupported principal, scope, condition or granularity.

        Notes:
            Uses greedy catalog coverage, not a proof of globally minimal policy.
            No generated policy is saved or applied. Matching denies still win.
        """
        metadata = self.suggestion_metadata()
        if report.get('snapshot', {}).get('runtime_id') != self._snapshot_id():
            raise ValueError('This result belongs to a previous snapshot. Rerun before generating policy candidates.')
        if principal_key not in metadata['principals']:
            raise ValueError('Choose a supported grant principal. OCI policies do not grant directly to a user.')
        known = {path.casefold() for path in metadata['locations']}
        if effective_path.casefold() not in known or policy_path.casefold() not in known:
            raise ValueError('Choose known policy and target compartments.')
        if not (
            effective_path.casefold() == policy_path.casefold()
            or effective_path.casefold().startswith(policy_path.casefold() + '/')
        ):
            raise ValueError('The policy compartment must be an ancestor of the effective compartment.')
        if granularity not in {'permission', 'resource', 'family'}:
            raise ValueError('Choose permission, resource or family granularity.')
        if where_clause:
            parsed = ConditionTesterService().parse_clause(where_clause)
            if parsed['structure']['parse_status'] != 'parsed':
                raise ValueError('The requested restriction cannot be parsed; review the where clause.')
            where_clause = parsed['clause']
        if metadata['principal_details'][principal_key]['type'] in {'any-user', 'any-group'} and not where_clause:
            raise ValueError('Supply an explicit restriction for a wildcard principal, or choose a named principal.')
        missing = set(report['result']['missing_permissions'])
        reference = self.context.reference_data
        options = []
        if granularity == 'permission' and missing:
            options = [('explicit permissions', '', set(missing))]
        else:
            entities = reference.data['resources'] if granularity == 'resource' else reference.data['families']
            for entity in sorted(entities):
                if entity == 'all-resources' or reference.get_resource_mapping_status(entity):
                    continue
                for verb in ('inspect', 'read', 'use', 'manage'):
                    permissions = set(reference.get_permissions(entity, verb))
                    if permissions & missing:
                        options.append((entity, verb, permissions))
        builder = ProspectiveBuilderService(self.context.policy_repo, reference, self.context.simulation)
        remaining, candidates = set(missing), []
        while remaining:
            matching = [item for item in options if item[2] & remaining]
            if not matching:
                break
            entity, verb, permissions = min(
                matching,
                key=lambda item: (len(item[2] - missing), -len(item[2] & remaining), len(item[2]), item[0], item[1]),
            )
            preview = builder.build_preview(
                {
                    'principal_key': principal_key,
                    'include_default': True,
                    'verb': verb or 'inspect',
                    'resource': entity,
                    'location': policy_path,
                    'effective_path': effective_path,
                    'where_mode': 'Other Where Clause' if where_clause else 'No Where Clause',
                    'other_where_text': where_clause,
                }
            )
            text = preview.statement_text
            if granularity == 'permission':
                text = (
                    f'Allow {preview.subject_phrase} to {{{", ".join(sorted(permissions))}}}{preview.location_clause}'
                )
                if where_clause:
                    text += ' where ' + where_clause
            validation = self.context.simulation.validate_prospective_statement(text)
            if not validation.get('parsed') or not validation.get('valid'):
                # Never offer an unresolved or syntactically invalid generated grant.
                options.remove((entity, verb, permissions))
                continue
            covered = permissions & missing
            candidates.append(
                {
                    'statement_text': text,
                    'compartment_path': policy_path,
                    'effective_path': effective_path,
                    'covered_permissions': sorted(covered),
                    'additional_permissions': sorted(permissions - missing),
                    'mapping': f'{entity} / {verb}' if verb else entity,
                    'description': 'Simulation what-if: ' + ', '.join(sorted(covered)),
                    'validation': 'Parsed and valid in the loaded reference model',
                }
            )
            remaining -= covered
        corpus = self.context.simulation.get_corpus(include_prospective=True)
        evidence, seen = [], set()
        for fact in corpus.facts if corpus else []:
            if fact.permission not in missing:
                continue
            key = (fact.provenance.statement_id, fact.permission, fact.effect, fact.principal_key)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    'permission': fact.permission,
                    'effect': fact.effect,
                    'principal_key': fact.principal_key,
                    'effective_path': fact.effective_path,
                    'conditions': fact.condition,
                    'policy_name': fact.provenance.policy_name,
                    'internal_id': fact.provenance.statement_id,
                    'statement_text': fact.provenance.statement_text,
                    'same_principal': fact.principal_key == canonicalize_principal_key(principal_key),
                }
            )
        return {
            'candidates': candidates,
            'unmapped_permissions': sorted(remaining),
            'evidence': evidence,
            'limitations': 'Catalog candidates are not guaranteed fixes. Verify principal membership, conditions, denies, target scope and snapshot coverage. Scope includes descendants. Resource/family options can add permissions beyond the failed operation; review each additional permission. Corpus examples may belong to other principals or paths.',
        }
