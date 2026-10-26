"""Bounded graph projection of direct policy corpus grants."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from time import perf_counter
from typing import Any

from oci_policy_analysis.application.core.common.policy_helpers import principal_display_name
from oci_policy_analysis.application.core.policy_corpus import PolicyCorpus
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.condition_tester_service import extract_condition_clause

logger = get_logger(component='application.services.policy_graph')


class PolicyGraphService:
    """Project direct corpus contributions into source-grant search results.

    Args:
        corpus: Compiled regular policy corpus, or None for an unloaded result.

    Attributes:
        corpus: Snapshot bound to this service instance; construct a new service after reload.

    Notes:
        Groups permissions by source statement/principal/path while retaining source
        evidence and conditions. Does not expand inherited facts or evaluate conditions
        and denies into an authorization decision.
    """

    def __init__(self, corpus: PolicyCorpus | None) -> None:
        self.corpus = corpus

    def get_page(
        self,
        *,
        principal: str = '',
        path: str = '',
        resource: str = '',
        query: str = '',
        effect: str = '',
        page: int = 1,
        page_size: int = 12,
        overview: bool = False,
        all_results: bool = False,
    ) -> dict[str, Any]:
        """Search source grants and return complete facets with selected rows.

        Args:
            principal: Case-insensitive substring of canonical or declared principal keys.
            path: Case-insensitive substring of the original grant path.
            resource: Substring of a resource name or expanded permission name.
            query: Substring of policy name, original statement text, or statement ID.
            effect: Exact effect filter, normally allow or deny; empty selects both.
            page: One-based page number, clamped to at least one.
            page_size: Requested rows per page, clamped to the range 1 through 12.
            overview: Suppress grant rows until an effect or two-character text filter
                is present; counts and facets still describe all matches.
            all_results: Return all matching rows on page one, overriding pagination.

        Returns:
            dict[str, Any]: Load state, match total, page metadata, grants with complete
            permission lists, principal/path facets across all matches, needs_filter,
            and corpus summary counts. An unloaded corpus returns empty rows.
        """
        started = perf_counter()
        corpus = self.corpus
        if corpus is None:
            logger.info('Policy graph search: no corpus loaded; returning no grants.')
            return {
                'loaded': False,
                'total': 0,
                'page': 1,
                'page_size': 12,
                'grants': [],
                'paths': [],
                'principals': [],
                'needs_filter': False,
                'summary': {'direct_facts': 0, 'source_statements': 0, 'exclusions': 0},
            }

        principal = principal.strip().casefold()
        path = path.strip().casefold()
        resource = resource.strip().casefold()
        query = query.strip().casefold()
        effect = effect.strip().casefold()
        page = max(1, page)
        page_size = max(1, min(page_size, 12))
        grouped: dict[tuple[str, ...], dict[str, Any]] = {}
        all_statements: set[str] = set()
        for fact in corpus.facts:
            source = fact.provenance
            all_statements.add(source.statement_id)
            principal_text = f'{fact.principal_key} {principal_display_name(fact.principal_key)}'.casefold()
            # A declared any-user/group key remains searchable after workload
            # specialization. Other multi-subject facts must match their own key.
            if fact.principal_key.startswith(('resource-principal:', 'oke-workload-identity:')):
                principal_text += ' ' + fact.original_principal_key.casefold()
            principal_text += ' ' + principal_text.replace('-', ' ')
            if principal and principal not in principal_text:
                continue
            if path and path not in fact.grant_path.casefold():
                continue
            if effect and effect != fact.effect:
                continue
            if query and query not in f'{source.policy_name} {source.statement_text} {source.statement_id}'.casefold():
                continue
            key = (
                source.policy_ocid,
                source.statement_id,
                fact.principal_key,
                fact.grant_path,
                fact.resource,
                fact.effect,
                fact.condition,
            )
            if key not in grouped:
                grouped[key] = {
                    'id': '|'.join(key),
                    'prospective': fact.prospective,
                    'principal': fact.principal_key,
                    'principal_display': principal_display_name(fact.principal_key),
                    'path': fact.grant_path,
                    'resource': fact.resource,
                    'effect': fact.effect,
                    'condition': fact.condition,
                    'condition_clause': extract_condition_clause(fact.condition, source.statement_text),
                    'policy_name': source.policy_name,
                    'policy_ocid': source.policy_ocid,
                    'statement_id': source.statement_id,
                    'statement_text': source.statement_text,
                    'permissions': set(),
                }
            grouped[key]['permissions'].add(fact.permission)

        grants = sorted(
            (
                row
                for row in grouped.values()
                if not resource
                or resource in row['resource'].casefold()
                or any(resource in permission.casefold() for permission in row['permissions'])
            ),
            key=lambda row: (
                row['principal'].casefold(),
                row['path'].casefold(),
                row['policy_name'].casefold(),
                row['statement_id'],
                row['resource'].casefold(),
            ),
        )
        # Path discovery uses every matching grant, not just the displayed page.
        path_counts: dict[str, dict[str, Any]] = {}
        principal_counts: dict[str, dict[str, Any]] = {}
        for grant in grants:
            token = grant['path'].casefold()
            item = path_counts.setdefault(token, {'path': grant['path'], 'grant_count': 0})
            item['grant_count'] += 1
            principal_item = principal_counts.setdefault(
                grant['principal'].casefold(),
                {'principal': grant['principal'], 'principal_display': grant['principal_display'], 'grant_count': 0},
            )
            principal_item['grant_count'] += 1
        paths = sorted(path_counts.values(), key=lambda item: item['path'].casefold())
        principals = sorted(principal_counts.values(), key=lambda item: item['principal'].casefold())
        if all_results:
            page, page_size = 1, max(1, len(grants))
        needs_filter = overview and not (effect or any(len(value) >= 2 for value in (principal, path, resource, query)))
        offset = (page - 1) * page_size
        selected = (
            [{**row, 'permissions': sorted(row['permissions'])} for row in grants[offset : offset + page_size]]
            if not needs_filter
            else []
        )
        logger.info(
            'Policy graph search: filters=%r effect=%s overview=%s page=%d page_size=%d '
            'facts=%d statements=%d excluded=%d matching_principals=%d '
            'matching_grants=%d matching_paths=%d visible_grants=%d elapsed_ms=%.1f',
            [
                name
                for name, value in (
                    ('principal', principal),
                    ('path', path),
                    ('resource_or_permission', resource),
                    ('policy_or_statement', query),
                )
                if value
            ],
            effect or 'all',
            needs_filter,
            page,
            page_size,
            len(corpus.facts),
            len(all_statements),
            len(corpus.exclusions),
            len(principals),
            len(grants),
            len(paths),
            len(selected),
            (perf_counter() - started) * 1000,
        )
        logger.debug(
            'Policy graph filter values: principal=%r path=%r resource_or_permission=%r query=%r',
            principal,
            path,
            resource,
            query,
        )
        return {
            'loaded': True,
            'total': len(grants),
            'page': page,
            'page_size': page_size,
            'grants': selected,
            'paths': paths,
            'principals': principals,
            'needs_filter': needs_filter,
            'summary': {
                'direct_facts': len(corpus.facts),
                'source_statements': len(all_statements),
                'exclusions': len(corpus.exclusions),
            },
        }

    def get_statement_evidence(self, grants: list[dict], *, source_statements: list[dict]) -> list[dict]:
        """Join selected graph combinations to complete source records and facts.

        Args:
            grants: Selected rows from get_page, including rows beyond a visible
                graph page when the caller requests all_results.
            source_statements: Current collected and optional prospective statement
                views. Source IDs, policy OCIDs and prospective markers identify rows.

        Returns:
            list[dict]: Detached source records with permission_facts containing all
            direct corpus contributions for the selected combinations. Conditions,
            effect, paths and provenance remain attached to each fact. Permission
            contributions do not establish an OCI authorization decision.
        """
        if self.corpus is None:
            return []
        combinations = {(row['principal'], row['path'], row['resource'], row['effect']) for row in grants}
        sources = {
            (str(row.get('internal_id') or ''), str(row.get('policy_ocid') or ''), bool(row.get('is_prospective'))): row
            for row in source_statements
        }
        grouped = {}
        for fact in self.corpus.facts:
            combination = (fact.principal_key, fact.grant_path, fact.resource, fact.effect)
            if combination not in combinations:
                continue
            source = fact.provenance
            identity = (source.statement_id, source.policy_ocid, fact.prospective)
            if identity not in grouped:
                row = {
                    'internal_id': source.statement_id,
                    'policy_name': source.policy_name,
                    'policy_ocid': source.policy_ocid,
                    'statement_text': source.statement_text,
                    'action': fact.effect,
                    'resource': fact.resource,
                    'effective_path': fact.grant_path,
                    'conditions': fact.condition,
                    **deepcopy(sources.get(identity) or {}),
                }
                if fact.prospective and not str(row.get('policy_name') or '').startswith('[Prospective]'):
                    row['policy_name'] = '[Prospective] ' + str(row.get('policy_name') or 'What-if')
                row['conditional'] = bool(
                    extract_condition_clause(row.get('conditions') or '', row.get('statement_text') or '')
                )
                row['is_prospective'] = fact.prospective
                row['permission_facts'] = []
                row['graph_selection'] = []
                grouped[identity] = row
            row = grouped[identity]
            row['permission_facts'].append(asdict(fact))
            selection = dict(zip(('principal', 'effective_path', 'resource', 'action'), combination, strict=True))
            if selection not in row['graph_selection']:
                row['graph_selection'].append(selection)
        return list(grouped.values())
