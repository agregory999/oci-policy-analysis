"""Experimental, snapshot-based symbolic grants and offline batch evaluation.

The JSON model is the durable representation. Runtime indexes and parsed predicate
atoms are private accelerators rebuilt once when a model is opened, never per query.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener
from oci.util import to_dict

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionLexer import (
    OciIamPolicyConditionLexer,
)
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionParser import (
    OciIamPolicyConditionParser,
)
from oci_policy_analysis.application.core.parser.condition_parser.WhereClauseEvaluator import WhereClauseEvaluator
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.core.support.logger import get_logger

LOG_COMPONENT = 'compiled_corpus'
logger = get_logger(LOG_COMPONENT)

SCHEMA_VERSION = 1
SNAPSHOT_FIELDS = (
    'tenancy_ocid',
    'policies',
    'regular_statements',
    'cross_tenancy_statements',
    'defined_aliases',
    'compartments',
    'users',
    'groups',
    'dynamic_groups',
    'identity_domains',
    'defined_tag_namespace_keys',
    'inventory_complete',
    'compliance_capabilities',
    'identity_loaded_from_tenancy',
    'policies_loaded_from_tenancy',
    'snapshot_kind',
    'data_as_of',
    'policy_data_reloaded',
)


def json_text(value: Any) -> str:
    """Encode snapshots consistently, including repository set values."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=_json_default)


def _json_default(value):
    if isinstance(value, set):
        return sorted(value, key=str)
    if isinstance(value, datetime):
        return value.isoformat()
    # Live and cached identity inventories both contain OCI SDK Domain models.
    # Use their declared data schema, never __dict__ or a lossy string fallback.
    if type(value).__module__.startswith('oci.') and isinstance(getattr(value, 'swagger_types', None), dict):
        return to_dict(value)
    raise TypeError(f'Unsupported snapshot value: {type(value).__name__}')


def digest(value: Any) -> str:
    """Return a deterministic identity for JSON-compatible data."""
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def capture_inputs(repo, reference, *, log_capture=False) -> dict:
    """Copy only data, never clients, locks, credentials, or live repositories."""
    started = time.perf_counter()
    inventory = {}
    if log_capture:
        logger.info('Snapshot capture started: %d inventory fields plus reference data', len(SNAPSHOT_FIELDS))
    for field in (*SNAPSHOT_FIELDS, 'reference_data'):
        value = reference.data if field == 'reference_data' else getattr(repo, field, None)
        if log_capture:
            item_types = sorted({type(item).__name__ for item in value}) if isinstance(value, list) else []
            logger.debug(
                'Snapshot field=%s type=%s count=%s item_types=%s',
                field,
                type(value).__name__,
                len(value) if isinstance(value, list | dict | set) else '-',
                item_types,
            )
        try:
            encoded = json.loads(json_text(value))
        except (TypeError, ValueError) as exc:
            raise TypeError(f'Snapshot field {field}: {exc}') from exc
        if field == 'reference_data':
            reference_data = encoded
        else:
            inventory[field] = encoded
    if log_capture:
        logger.info(
            'Snapshot capture completed in %.3fs: statements=%d domains=%d compartments=%d',
            time.perf_counter() - started,
            len(inventory.get('regular_statements') or []),
            len(inventory.get('identity_domains') or []),
            len(inventory.get('compartments') or []),
        )
    return {'inventory': inventory, 'reference_data': reference_data}


class BuildCancelled(Exception):
    """Raised cooperatively without replacing the previous successful build."""


def checkpoint(progress, cancel, done, total, message):
    """Report progress and honor cooperative cancellation."""
    if cancel and cancel.is_set():
        logger.info('Cancellation requested; stopping at a work checkpoint')
        raise BuildCancelled('Cancelled')
    if progress:
        progress(done, total, message)


class _Errors(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        raise ValueError(f'Condition at {line}:{column}: {msg}')


def _parse(text):
    lexer = OciIamPolicyConditionLexer(InputStream(text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_Errors())
    parser = OciIamPolicyConditionParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_Errors())
    return parser.condition_clause().condition_expression()


def compile_predicate(text: str) -> dict:
    """Keep full Boolean structure and lossless atomic expressions."""
    if not text:
        return {'kind': 'true'}

    def visit(ctx):
        atom = ctx.single_condition()
        if atom:
            variable = atom.variable_name().getText()
            if atom.BANG() is not None:
                expression = f'!{variable}'
            else:
                operator = (atom.NOT_IN() or atom.OPERATOR()).getText().lower()
                value = (
                    atom.literal_list().getText()
                    if atom.literal_list()
                    else ' AND '.join(value.getText() for value in atom.condition_value())
                )
                expression = f'{variable} {operator} {value}'
            return {
                'kind': 'atom',
                'variable': atom.variable_name().getText(),
                'expression': expression,
                'presence': atom.BANG() is not None,
            }
        return {
            'kind': ctx.all_or_any().getText().lower(),
            'children': sorted((visit(c) for c in ctx.condition_list().condition_expression()), key=json_text),
        }

    return visit(_parse(text))


def predicate_variables(node):
    """Collect required input variables from a compiled predicate tree."""
    if node['kind'] == 'atom':
        return {node['variable']}
    return set().union(*(predicate_variables(c) for c in node.get('children', [])))


def _principals(repo, statement):
    keys = repo._statement_principal_keys(statement)
    if keys:
        return sorted(keys)
    kind = statement.get('subject_type', '')
    subjects = statement.get('subject') or []
    if isinstance(subjects, str):
        subjects = [subjects]
    for subject in subjects:
        domain, name = subject if isinstance(subject, list | tuple) and len(subject) == 2 else (None, subject)
        if not isinstance(name, str):
            continue
        if kind.endswith('-id') or name.startswith('ocid1.'):
            keys.add(f'{kind if kind.endswith("-id") else kind + "-id"}:{name}')
        else:
            keys.add(calculate_principal_key(kind, domain, name))
    return sorted(keys)


def missing_permission_mappings(corpus: dict) -> list[dict]:
    """Group unknown expansions, including diagnostics from older corpus exports."""
    grouped = {}
    for diagnostic in corpus.get('diagnostics', []):
        if (
            diagnostic.get('code') != 'unknown_permission_expansion'
            and diagnostic.get('message') != 'Resource/verb permission expansion is unknown.'
        ):
            continue
        source_id = diagnostic['source_id']
        provenance = corpus.get('sources', {}).get(source_id, {})
        source = provenance.get('source', {})
        resource = str(diagnostic.get('resource') or source.get('resource') or '(unknown)').strip().lower()
        verb = str(diagnostic.get('verb') or source.get('verb') or '(unknown)').strip().lower()
        effect = str(diagnostic.get('effect') or source.get('action') or 'allow').strip().lower()
        key = (resource, verb, effect)
        row = grouped.setdefault(
            key,
            {
                'resource': resource,
                'verb': verb,
                'effect': effect,
                'source_ids': set(),
                'statement_ids': set(),
                'policy_names': set(),
            },
        )
        row['source_ids'].add(source_id)
        statement_id = diagnostic.get('statement_id') or provenance.get('statement_id')
        policy_name = diagnostic.get('policy_name') or provenance.get('policy_name')
        if statement_id:
            row['statement_ids'].add(str(statement_id))
        if policy_name:
            row['policy_names'].add(str(policy_name))
    return [
        {
            **row,
            'statement_count': len(row['source_ids']),
            'source_ids': sorted(row['source_ids']),
            'statement_ids': sorted(row['statement_ids']),
            'policy_names': sorted(row['policy_names']),
        }
        for _, row in sorted(grouped.items())
    ]


def build_corpus(inputs: dict, progress=None, cancel=None) -> dict:  # noqa: C901
    """Compile every loaded input or retain it as an explicit residual source."""
    inventory = inputs['inventory']
    started = time.perf_counter()
    reference = ReferenceDataRepo()
    reference.data = inputs['reference_data']
    reference.rebuild_name_maps()
    repo = PolicyAnalysisRepository.__new__(PolicyAnalysisRepository)
    all_statements = [
        (kind, st)
        for kind in ('regular_statements', 'cross_tenancy_statements', 'defined_aliases')
        for st in inventory.get(kind) or []
    ]
    sources, predicates, grants, diagnostics = {}, {}, {}, []
    variables = defaultdict(set)
    total = len(all_statements)
    logger.info('Compilation started: %d statements; resolving principals, scopes, permissions and predicates', total)
    for position, (kind, st) in enumerate(all_statements):
        checkpoint(progress, cancel, position, total, f'Compiling statement {position + 1} of {total}')
        source_id = f'source-{position:06d}-{digest(st)[:12]}'
        sources[source_id] = {
            'statement_id': st.get('internal_id') or st.get('id') or '',
            'policy_name': st.get('policy_name', ''),
            'position': position,
            'content_hash': digest(st),
            'source': st,
            'status': 'compiled',
        }
        diagnostic_code = 'unresolved_statement'
        try:
            logger.debug(
                'Compiling source=%s statement_id=%s kind=%s', source_id, sources[source_id]['statement_id'], kind
            )
            if kind != 'regular_statements':
                raise ValueError('Cross-tenancy/alias input retained; external authorization is not modeled.')
            # Check reference coverage before condition/principal validation so
            # the library checklist is not hidden by an unrelated statement error.
            effect = str(st.get('action') or 'allow').lower()
            expanded = []
            if st.get('resource') and effect in ('allow', 'deny'):
                expanded = reference.get_permissions(st['resource'], st.get('verb'), effect)
                if not expanded:
                    diagnostic_code = 'unknown_permission_expansion'
                    raise ValueError(
                        f'Resource/verb permission expansion is unknown: resource={st["resource"]!r}, '
                        f'verb={st.get("verb")!r}, effect={effect!r}.'
                    )
            if st.get('valid') is False or st.get('invalid_reasons'):
                raise ValueError('Statement has validation errors.')
            effect = str(st.get('action') or 'allow').lower()
            if effect not in ('allow', 'deny'):
                raise ValueError(f'Unsupported effect: {effect}')
            scope = str(st.get('effective_path') or '').strip('/').lower()
            if not scope or scope == 'unknown':
                raise ValueError('Target compartment scope is unresolved.')
            principals = _principals(repo, st)
            if not principals:
                raise ValueError('Principal selector is unresolved.')
            condition = st.get('conditions') or ''
            if isinstance(condition, dict):
                if not isinstance(condition.get('where_clause'), str):
                    raise ValueError('Condition object has no supported where_clause text.')
                condition = condition['where_clause']
            predicate = compile_predicate(condition)
            predicate_id = digest(predicate)[:24]
            perms = st.get('permission') or []
            if isinstance(perms, str):
                perms = [perms]
            if st.get('resource'):
                perms = list(perms) + expanded
            if not perms:
                raise ValueError('No resolved permissions.')
            predicates[predicate_id] = predicate
            for variable in predicate_variables(predicate):
                variables[variable].add(source_id)
            for principal in principals:
                for permission in sorted({str(p).upper() for p in perms}):
                    key = (principal, scope, permission, effect, predicate_id)
                    grant_id = digest(key)[:24]
                    grant = grants.setdefault(
                        grant_id,
                        {
                            'id': grant_id,
                            'principal': principal,
                            'scope': scope,
                            'scope_kind': 'subtree',
                            'permission': permission,
                            'effect': effect,
                            'predicate_id': predicate_id,
                            'source_ids': [],
                        },
                    )
                    grant['source_ids'].append(source_id)
            logger.debug(
                'Compiled source=%s effect=%s principals=%d permissions=%d predicate=%s variables=%s',
                source_id,
                effect,
                len(principals),
                len(set(perms)),
                predicate_id,
                sorted(predicate_variables(predicate)),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            sources[source_id]['status'] = 'unresolved'
            diagnostics.append(
                {
                    'source_id': source_id,
                    'message': str(exc),
                    'code': diagnostic_code,
                    'resource': st.get('resource') or '',
                    'verb': st.get('verb') or '',
                    'effect': str(st.get('action') or 'allow').lower(),
                    'statement_id': sources[source_id]['statement_id'],
                    'policy_name': sources[source_id]['policy_name'],
                }
            )
            logger.info('Unresolved source=%s statement_id=%s: %s', source_id, sources[source_id]['statement_id'], exc)
        if (position + 1) % 100 == 0 or position + 1 == total:
            logger.info(
                'Compilation progress: %d/%d statements; %d grants; %d unresolved',
                position + 1,
                total,
                len(grants),
                len(diagnostics),
            )
    checkpoint(progress, cancel, total, total, 'Building indexes and context catalog')
    grant_list = sorted(
        grants.values(), key=lambda g: (g['principal'], g['scope'], g['permission'], g['effect'], g['id'])
    )
    compiled = sum(s['status'] == 'compiled' for s in sources.values())
    mapping_gaps = missing_permission_mappings({'sources': sources, 'diagnostics': diagnostics})
    logger.info(
        'Missing permission mappings: %d resource/verb/effect combinations affecting %d statements',
        len(mapping_gaps),
        sum(row['statement_count'] for row in mapping_gaps),
    )
    logger.info(
        'Compilation completed in %.3fs: compiled=%d unresolved=%d grants=%d predicates=%d context_variables=%d',
        time.perf_counter() - started,
        compiled,
        total - compiled,
        len(grant_list),
        len(predicates),
        len(variables),
    )
    return {
        'schema_version': SCHEMA_VERSION,
        'compiler_version': 'experimental-1',
        'snapshot_id': digest(inputs),
        'built_at': datetime.now(UTC).isoformat(),
        'build_duration_seconds': round(time.perf_counter() - started, 3),
        'reference_hash': digest(inputs['reference_data']),
        'inputs': inputs,
        'summary': {
            'statements': total,
            'compiled_statements': compiled,
            'unresolved_statements': total - compiled,
            'grants': len(grant_list),
            'predicates': len(predicates),
            'context_variables': len(variables),
            'duplicate_grants': sum(len(g['source_ids']) - 1 for g in grant_list),
            'missing_permission_mappings': len(mapping_gaps),
        },
        'grants': grant_list,
        'predicates': predicates,
        'sources': sources,
        'diagnostics': diagnostics,
        'missing_permission_mappings': mapping_gaps,
        'context_catalog': [
            {
                'variable': v,
                'source_ids': sorted(ids),
                'binding': 'derived per permission'
                if v == 'request.permission'
                else 'derived from operation'
                if v == 'request.operation'
                else 'manual',
            }
            for v, ids in sorted(variables.items())
        ],
        'limitations': [
            'Experimental local permission model; not an OCI authorization guarantee.',
            'Cross-tenancy inputs and unsupported conditions remain unresolved.',
            'Dynamic-group membership is selected manually; resource inventory is not evaluated.',
            'Deny enablement and administrator exemption require explicit scenario assumptions.',
            'Related-resource API checks remain advisory.',
        ],
    }


class CorpusRuntime:
    """Indexes a compiled model once and evaluates isolated request contexts."""

    def __init__(self, corpus):
        logger.info(
            'Runtime indexing started: grants=%d predicates=%d',
            len(corpus.get('grants', [])),
            len(corpus.get('predicates', {})),
        )
        if corpus.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Unsupported corpus schema version.')
        self.corpus = corpus
        self.by_permission = defaultdict(list)
        for grant in corpus['grants']:
            self.by_permission[grant['permission']].append(grant)
        self.atoms = {}
        for predicate in corpus['predicates'].values():
            self._prepare(predicate)
        self.repo = PolicyAnalysisRepository.__new__(PolicyAnalysisRepository)
        for field in ('users', 'groups', 'dynamic_groups'):
            setattr(self.repo, field, corpus['inputs']['inventory'].get(field) or [])
        self.reference = ReferenceDataRepo()
        self.reference.data = corpus['inputs']['reference_data']
        self.operations = self.reference.data.get('operations', {})
        logger.info(
            'Runtime indexing completed: permissions=%d condition_atoms=%d operations=%d',
            len(self.by_permission),
            len(self.atoms),
            len(self.operations),
        )

    def _prepare(self, node):
        if node['kind'] == 'atom':
            expression = node['expression']
            if expression not in self.atoms:
                self.atoms[expression] = _parse(expression).single_condition()
        for child in node.get('children', []):
            self._prepare(child)

    def _predicate(self, node, context):
        kind = node['kind']
        if kind == 'true':
            return True
        if kind == 'atom':
            if node['variable'] not in context:
                return None
            try:
                return bool(WhereClauseEvaluator(context).visitSingle_condition(self.atoms[node['expression']]))
            except (ValueError, TypeError, AttributeError):
                return None
        results = [self._predicate(c, context) for c in node['children']]
        if kind == 'all':
            return False if False in results else None if None in results else True
        return True if True in results else None if None in results else False

    def _matches(self, grant, principal, scope, keys):
        if scope != grant['scope'] and not scope.startswith(grant['scope'] + '/'):
            return False
        selector = grant['principal'].casefold()
        if selector in keys:
            return True
        if selector == 'any-user:none/any-user':
            return True
        if selector == 'any-group:none/any-group':
            return principal.startswith(('group:', 'group-id:', 'dynamic-group:', 'dynamic-group-id:')) or any(
                k.startswith(('group:', 'group-id:')) for k in keys
            )
        return False

    def candidates(self, scenario):
        principal = scenario.get('principal_key', '').strip()
        scope = scenario.get('compartment_path', '').strip('/').lower()
        if not principal or not scope:
            raise ValueError('Each scenario needs a principal and target compartment path.')
        keys = {k.casefold() for k in self.repo._equivalent_principal_keys_for_key(principal)}
        required = self.operations.get(self.reference.resolve_operation(scenario.get('api_operation')), {}).get(
            'permissions', []
        )
        return [
            g
            for permission in required
            for g in self.by_permission[str(permission).upper()]
            if self._matches(g, principal, scope, keys)
        ]

    def required_context(self, scenario):
        return sorted(
            set().union(
                *(predicate_variables(self.corpus['predicates'][g['predicate_id']]) for g in self.candidates(scenario))
            )
            - {'request.permission', 'request.operation'}
        )

    def evaluate(self, scenario, shared=None, excluded=frozenset()):  # noqa: C901
        if not isinstance(scenario, dict) or not isinstance(scenario.get('context', {}), dict):
            raise ValueError('Each scenario and its context must be JSON objects.')
        context = {**(shared or {}), **scenario.get('context', {})}
        context.pop('request.permission', None)
        operation = self.reference.resolve_operation(scenario.get('api_operation', ''))
        info = self.operations.get(operation) or {}
        required = sorted({str(p).upper() for p in info.get('permissions', [])})
        context['request.operation'] = info.get('operation_name', operation.removeprefix('oci:'))
        candidates = self.candidates(scenario)
        active, unknown, permission_results = set(), set(), {}
        predicate_cache = {}
        for permission in required:
            allows, denies = [], []
            for grant in candidates:
                if grant['permission'] != permission:
                    continue
                sources = set(grant['source_ids']) - excluded
                if not sources:
                    continue
                key = (grant['predicate_id'], permission)
                if key not in predicate_cache:
                    predicate_cache[key] = self._predicate(
                        self.corpus['predicates'][grant['predicate_id']], {**context, 'request.permission': permission}
                    )
                matched = predicate_cache[key]
                if grant['effect'] == 'deny' and matched is not False:
                    # Explicit assumptions prevent silently claiming generic deny semantics are complete.
                    if context.get('corpus.deny_enabled') == 'false' or context.get('corpus.deny_exempt') == 'true':
                        matched = False
                    elif context.get('corpus.deny_enabled') != 'true' or context.get('corpus.deny_exempt') != 'false':
                        matched = None
                if matched is True:
                    active.update(sources)
                elif matched is None:
                    unknown.update(sources)
                (allows if grant['effect'] == 'allow' else denies).append(matched)
            permission_results[permission] = (
                'denied'
                if True in denies
                else 'indeterminate'
                if None in denies
                else 'allowed'
                if True in allows
                else 'indeterminate'
                if None in allows
                else 'denied'
            )
        warnings = []
        if not required:
            warnings.append('Operation has no known permission mapping.')
        if self.corpus['diagnostics']:
            warnings.append('Unresolved corpus inputs may affect this result.')
        inventory = self.corpus['inputs']['inventory']
        if inventory.get('inventory_complete') is not True:
            warnings.append('Inventory completeness is unverified.')
        if scenario['principal_key'].startswith(('user:', 'user-id:')) and not inventory.get(
            'identity_loaded_from_tenancy'
        ):
            warnings.append('User membership completeness is unverified.')
        modeled = (
            'indeterminate'
            if not required
            else 'denied'
            if 'denied' in permission_results.values()
            else 'indeterminate'
            if 'indeterminate' in permission_results.values()
            else 'allowed'
        )
        result = 'indeterminate' if warnings else modeled
        return {
            'name': scenario.get('name') or operation,
            'result': result,
            'modeled_result': modeled,
            'expected': scenario.get('expected', ''),
            'expectation_met': result == scenario['expected'] if scenario.get('expected') else None,
            'permissions': permission_results,
            'active_sources': sorted(active),
            'unknown_sources': sorted(unknown),
            'candidate_sources': sorted({s for g in candidates for s in g['source_ids']} - excluded),
            'resolved_context': context,
            'missing_context': sorted(set(self.required_context(scenario)) - set(context)),
            'context_bindings': {'request.permission': 'Bound separately to each permission in the permissions map.'},
            'warnings': warnings,
            'related_checks': info.get('related_checks', []),
        }

    def run_suite(self, suite, contribution=False, progress=None, cancel=None):
        scenarios = suite.get('scenarios', [])
        if not isinstance(scenarios, list) or not scenarios:
            raise ValueError('Add at least one scenario.')
        shared = suite.get('shared_context', {})
        if not isinstance(shared, dict):
            raise ValueError('Shared context must be an object.')
        started = time.perf_counter()
        logger.info(
            'Evaluation started: scenarios=%d contribution_analysis=%s shared_fields=%d',
            len(scenarios),
            contribution,
            len(shared),
        )
        results = []
        stats = {
            sid: {'exercised': 0, 'unknown': 0, 'permission_changes': 0, 'decision_changes': 0, 'witnesses': []}
            for sid in self.corpus['sources']
        }
        for index, scenario in enumerate(scenarios):
            checkpoint(progress, cancel, index, len(scenarios), f'Evaluating {index + 1} of {len(scenarios)}')
            baseline = self.evaluate(scenario, shared)
            logger.debug(
                'Scenario %d: result=%s candidates=%d active=%d unknown=%d missing_fields=%s',
                index + 1,
                baseline['result'],
                len(baseline['candidate_sources']),
                len(baseline['active_sources']),
                len(baseline['unknown_sources']),
                baseline['missing_context'],
            )
            for sid in baseline['active_sources']:
                stats[sid]['exercised'] += 1
            for sid in baseline['unknown_sources']:
                stats[sid]['unknown'] += 1
            if contribution:
                for sid in baseline['candidate_sources']:
                    checkpoint(None, cancel, 0, 0, '')
                    changed = self.evaluate(scenario, shared, {sid})
                    permission_change = baseline['permissions'] != changed['permissions']
                    decision_change = baseline['result'] != changed['result']
                    stats[sid]['permission_changes'] += int(permission_change)
                    stats[sid]['decision_changes'] += int(decision_change)
                    if permission_change or decision_change:
                        logger.debug(
                            'Contribution scenario=%d source=%s permission_change=%s decision_change=%s',
                            index + 1,
                            sid,
                            permission_change,
                            decision_change,
                        )
                        stats[sid]['witnesses'].append(
                            {
                                'scenario': index,
                                'without_source': changed['result'],
                                'permissions': changed['permissions'],
                            }
                        )
            results.append(baseline)
            if (index + 1) % 100 == 0 or index + 1 == len(scenarios):
                logger.info('Evaluation progress: %d/%d scenarios', index + 1, len(scenarios))
        checkpoint(progress, cancel, len(scenarios), len(scenarios), 'Evaluation complete')
        logger.info(
            'Evaluation completed in %.3fs: allowed=%d denied=%d indeterminate=%d',
            time.perf_counter() - started,
            sum(r['result'] == 'allowed' for r in results),
            sum(r['result'] == 'denied' for r in results),
            sum(r['result'] == 'indeterminate' for r in results),
        )
        return {
            'schema_version': 1,
            'snapshot_id': self.corpus['snapshot_id'],
            'suite': suite,
            'contribution_analysis': contribution,
            'results': results,
            'statement_contribution': stats,
            'note': 'No effect in this suite is not proof of redundancy. Individual removals are not a bulk removal plan.',
        }
