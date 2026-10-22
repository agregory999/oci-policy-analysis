"""Bounded, bidirectional reference discovery over an independently loaded catalog."""

import base64
import hashlib
import json
import re
from importlib.metadata import version

from oci_policy_analysis.application.core.models.models_reference_lookup import (
    OperationReferenceMatch,
    OperationReferenceQuery,
    OperationReferenceResult,
    PermissionExpansion,
    PermissionReferenceMatch,
    PermissionReferenceQuery,
    PermissionReferenceResult,
    PermissionResourceMatch,
    ResourceReferenceMatch,
    ResourceReferenceQuery,
    ResourceReferenceResult,
)
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService

_VERBS = ('inspect', 'read', 'use', 'manage')
_DETAIL_LIMIT = 50
_WARNING = (
    'Bundled catalog evidence only; conditions, scope and additional checks still apply. Not an OCI access decision.'
)


def _words(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', str(text)).casefold()).split())


def _rank(query, name, aliases=(), search_terms=(), *, exact=False):
    needle = query.casefold()
    for rank, kind, values in ((0, 'identifier', [name]), (1, 'alias', aliases)):
        for value in values:
            if needle == value.casefold():
                return rank, kind, value
    if exact:
        return None
    normalized = _words(query)
    if not normalized:
        return None
    for value in search_terms:
        if normalized == _words(value):
            return 2, 'search_term', value
    for value in [name, *aliases, *search_terms]:
        words = _words(value)
        if normalized in words or all(part in words.split() for part in normalized.split()):
            return 3, 'text', value
    return None


def _bounded(values):
    values = sorted({value for value in values if not value.startswith('UNKNOWN_')})
    return PermissionExpansion(
        permissions=values[:_DETAIL_LIMIT], total_count=len(values), truncated=len(values) > _DETAIL_LIMIT
    )


class ReferenceLookupService:
    """Discover catalog terminology and reverse mappings without loading a tenancy.

    Args:
        reference_data: Loaded catalog retained for this service's lifetime.

    Attributes:
        catalog_id: Content fingerprint used to bind continuation cursors.
        catalog_version: Installed package version; the fingerprint identifies edits.

    Notes:
        Treat the supplied repository as immutable. Results are detached models.
        Recreate the service after changing catalog data. No OCI calls, settings,
        snapshot loads or cache writes occur here.
    """

    def __init__(self, reference_data: ReferenceDataRepo):
        self.reference = reference_data
        self.facade = ReferenceDataService(reference_data)
        self.catalog_id = hashlib.sha256(json.dumps(reference_data.data, sort_keys=True).encode()).hexdigest()[:20]
        self.catalog_version = version('oci-policy-analysis')
        self.resources = reference_data.data.get('resources', {})
        self.families = reference_data.data.get('families', {})
        self.operations = {
            name: meta for name, meta in reference_data.data.get('operations', {}).items() if ':' in name
        }
        self.membership = {
            resource: sorted(family for family, meta in self.families.items() if resource in meta.get('resources', []))
            for resource in self.resources
        }
        self.expansions = {
            resource: {
                verb: {p for p in reference_data.get_permissions(resource, verb) if not p.startswith('UNKNOWN_')}
                for verb in _VERBS
            }
            for resource, meta in self.resources.items()
            if not meta.get('mapping_status')
        }
        self.permission_resources = {}
        for resource, verbs in self.expansions.items():
            for permission in verbs['manage']:
                self.permission_resources.setdefault(permission, []).append(resource)
        self.permission_operations = {}
        for name, meta in self.operations.items():
            for permission in meta.get('permissions', []):
                if not permission.startswith('UNKNOWN_'):
                    self.permission_operations.setdefault(permission, []).append(name)

    def _sources(self, entity):
        return sorted(set(filter(None, self.reference.get_source(entity).split(', '))))

    def _page(self, query, rows, result_type, warnings):
        signature = hashlib.sha256(
            json.dumps(
                {
                    'catalog': self.catalog_id,
                    'type': result_type.__name__,
                    **query.model_dump(exclude={'cursor', 'limit'}),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]
        offset = 0
        if query.cursor:
            try:
                decoded = json.loads(base64.b64decode(query.cursor.encode(), altchars=b'-_', validate=True))
                offset = decoded['offset']
                if decoded['signature'] != signature or type(offset) is not int or offset < 0 or offset >= len(rows):
                    raise ValueError
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError('Cursor is invalid or belongs to a different query or catalog.') from exc
        selected = rows[offset : offset + query.limit]
        following = offset + len(selected)
        cursor = None
        if following < len(rows):
            cursor = base64.urlsafe_b64encode(
                json.dumps({'offset': following, 'signature': signature}).encode()
            ).decode()
        if not rows:
            warnings.append(
                'No catalog match. This does not establish that OCI has no such resource, operation or permission.'
            )
        return result_type(
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            matches=selected,
            total_matches=len(rows),
            next_cursor=cursor,
            warnings=[_WARNING, *warnings],
        )

    def resource_reference(self, query: ResourceReferenceQuery) -> ResourceReferenceResult:
        """Find resource/family names and cumulative allow-verb permission evidence.

        Args:
            query: Validated search, kind, verb and page controls.

        Returns:
            ResourceReferenceResult: Ranked identities, memberships and bounded expansions.

        Raises:
            ValueError: A continuation cursor does not match this request/catalog.
        """
        matches = []
        aggregates = {
            **self.families,
            'all-resources': {
                'resources': list(self.resources),
                'notes': 'Universal policy resource type. Expansion is limited to known catalog mappings, not all OCI permissions.',
                'search_terms': ['all resources', 'every resource'],
            },
        }
        for kind, entries in (('resource', self.resources), ('family', aggregates)):
            if query.kind not in (kind, 'either'):
                continue
            for name, meta in entries.items():
                ranked = _rank(
                    query.query,
                    name,
                    meta.get('aliases', []),
                    meta.get('search_terms', []),
                    exact=query.match == 'exact',
                )
                if not ranked:
                    continue
                expansion = {
                    verb: _bounded(self.reference.get_permissions(name, verb))
                    for verb in ([query.verb] if query.verb else _VERBS)
                }
                status = meta.get('mapping_status') or (
                    'mapped' if any(v.total_count for v in expansion.values()) else 'unavailable'
                )
                if (
                    status == 'unavailable'
                    and query.verb in meta.get('verbs', {})
                    and meta.get('catalog_status') == 'documented'
                ):
                    status = 'documented_empty'
                members = sorted(meta.get('resources', []))
                unmapped_members = [
                    member
                    for member in members
                    if member not in self.expansions or not self.expansions[member]['manage']
                ]
                if unmapped_members and status == 'mapped':
                    status = 'partial'
                record = ResourceReferenceMatch(
                    canonical_name=name,
                    kind=kind,
                    match_type=ranked[1],
                    matched_text=ranked[2],
                    source_resource_name=meta.get('source_resource_name') or name,
                    aliases=meta.get('aliases', []),
                    search_terms=meta.get('search_terms', []),
                    families=self.membership.get(name, []),
                    member_resources=members[:_DETAIL_LIMIT],
                    member_count=len(members),
                    members_truncated=len(members) > _DETAIL_LIMIT,
                    unmapped_member_resources=unmapped_members[:_DETAIL_LIMIT],
                    unmapped_member_count=len(unmapped_members),
                    supported_verbs=meta.get('supported_verbs', []),
                    permissions_by_verb=expansion,
                    notes=meta.get('notes', ''),
                    source_urls=self._sources(name),
                    catalog_status=meta.get('catalog_status', 'unreviewed'),
                    mapping_status=status,
                )
                matches.append((ranked[0], name, record))
        matches.sort(key=lambda item: (item[0], item[1]))
        return self._page(query, [row[2] for row in matches], ResourceReferenceResult, [])

    def operation_reference(self, query: OperationReferenceQuery) -> OperationReferenceResult:
        """Find qualified operations with fixed, conditional and unmapped requirements.

        Args:
            query: Validated wording or exact name, optional API group and page controls.

        Returns:
            OperationReferenceResult: Qualified names, source notes and bounded requirements.

        Raises:
            ValueError: A continuation cursor does not match this request/catalog.
        """
        matches = []
        for name, meta in self.operations.items():
            group, operation = name.split(':', 1)
            if query.api_group and group.casefold() != query.api_group.casefold():
                continue
            ranked = _rank(query.query, name, [operation], meta.get('search_terms', []), exact=query.match == 'exact')
            if not ranked:
                continue
            permissions = sorted({p for p in meta.get('permissions', []) if not p.startswith('UNKNOWN_')})
            unmapped = [p for p in permissions if p not in self.permission_resources]
            detail = self.facade.get_operation_detail(name)
            matches.append(
                (
                    ranked[0],
                    name,
                    OperationReferenceMatch(
                        canonical_name=name,
                        api_group=group,
                        operation_name=operation,
                        request_operation=detail['request_operation'],
                        match_type=ranked[1],
                        matched_text=ranked[2],
                        permissions=permissions[:_DETAIL_LIMIT],
                        permission_count=len(permissions),
                        permissions_truncated=len(permissions) > _DETAIL_LIMIT,
                        unmapped_permissions=unmapped[:_DETAIL_LIMIT],
                        related_checks=detail['related_checks'],
                        notes=meta.get('notes', ''),
                        catalog_status=meta.get('catalog_status', 'unreviewed'),
                        source_urls=[meta['source_url']] if meta.get('source_url') else [],
                        mapping_status=meta.get('mapping_status')
                        or ('partial' if unmapped else 'mapped' if permissions else 'documented_empty'),
                    ),
                )
            )
        matches.sort(key=lambda item: (item[0], item[1]))
        warnings = (
            ['Operation names can be shared by API groups; use canonical_name for subsequent lookups.']
            if len(matches) > 1
            else []
        )
        return self._page(query, [row[2] for row in matches], OperationReferenceResult, warnings)

    def permission_reference(self, query: PermissionReferenceQuery) -> PermissionReferenceResult:
        """Find named permissions and reverse resource/verb and operation mappings.

        Args:
            query: Validated permission search with an optional exact resource filter.

        Returns:
            PermissionReferenceResult: Lowest granting verbs and retained mapping gaps.

        Raises:
            ValueError: Resource is unknown or a cursor does not match this request/catalog.
        """
        resource = None
        if query.resource:
            resource = self.reference.resource_name_map.get(query.resource.casefold())
            if not resource:
                raise ValueError(
                    'Unknown resource filter; use resource_reference to discover an exact resource identifier.'
                )
        matches = []
        for permission in sorted(self.permission_resources.keys() | self.permission_operations.keys()):
            ranked = _rank(query.query, permission, exact=query.match == 'exact')
            if not ranked:
                continue
            resources = sorted(self.permission_resources.get(permission, []))
            if resource and resource not in resources:
                continue
            if resource:
                resources = [resource]
            mappings = []
            for name in resources[:_DETAIL_LIMIT]:
                verbs = [v for v in _VERBS if permission in self.expansions[name][v]]
                mappings.append(
                    PermissionResourceMatch(
                        resource=name,
                        source_resource_name=self.resources[name].get('source_resource_name') or name,
                        families=self.membership[name],
                        lowest_granting_verb=verbs[0],
                        granting_verbs=verbs,
                        additional_permissions=_bounded(self.expansions[name][verbs[0]] - {permission}),
                        source_urls=self._sources(name),
                    )
                )
            operations = sorted(set(self.permission_operations.get(permission, [])))
            matches.append(
                PermissionReferenceMatch(
                    canonical_name=permission,
                    match_type=ranked[1],
                    matched_text=ranked[2],
                    resource_mappings=mappings,
                    resource_mapping_count=len(resources),
                    resource_mappings_truncated=len(resources) > _DETAIL_LIMIT,
                    operations=operations[:_DETAIL_LIMIT],
                    operation_count=len(operations),
                    operations_truncated=len(operations) > _DETAIL_LIMIT,
                    source_urls=sorted({url for row in mappings for url in row.source_urls}),
                    mapping_status='mapped' if resources else 'operation_only',
                    notes=''
                    if resources
                    else 'Known from operation requirements; no resource/verb mapping is available in this catalog.',
                )
            )
        matches.sort(key=lambda row: (row.match_type != 'identifier', row.canonical_name))
        return self._page(query, matches, PermissionReferenceResult, [])
