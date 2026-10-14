"""Immutable, valid-only policy knowledge compiled from a loaded snapshot.

The repository deliberately retains invalid and partially understood source
statements for diagnostics.  ``PolicyCorpus`` is the complementary projection:
it exposes only the valid, evaluable authorization facts while retaining a
record of every excluded source statement.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

from oci_policy_analysis.application.core.common.policy_helpers import (
    calculate_principal_key,
    canonicalize_principal_key,
)
from oci_policy_analysis.application.core.parser.condition_structure import parse_condition_structure
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.core.support.logger import get_logger

LOGGER = get_logger(component='core.policy_corpus')


CorpusEffect = Literal['allow', 'deny']


@dataclass(frozen=True)
class CorpusProvenance:
    """Source evidence attached to an individual permission contribution.

    Attributes:
        policy_name: Display name of the source policy.
        policy_ocid: OCI policy identifier when available.
        statement_id: Snapshot-local identifier of the source statement.
        statement_text: Original policy text, preserving the supplied spelling.
    """

    policy_name: str
    policy_ocid: str
    statement_id: str
    statement_text: str


@dataclass(frozen=True)
class PolicyCorpusFact:
    """One unmerged principal/path/permission contribution in the analysis model.

    Attributes:
        principal_key: Canonical principal identity, normalized on construction.
        effective_path: Path represented by this direct or inherited fact.
        grant_path: Original path at which the source statement contributes access.
        permission: Concrete permission expanded using bundled reference data.
        effect: Allow or deny contribution; not a final authorization outcome.
        condition: Preserved predicate requiring request context if nonempty.
        provenance: Source statement evidence.
        resource: Source resource or resource-family name.
        inherited_from: Ancestor grant path for inherited facts, otherwise empty.
        original_principal_key: Original principal spelling for display.
        prospective: Whether this contribution comes from a hypothetical statement.
    """

    principal_key: str
    effective_path: str
    grant_path: str
    permission: str
    effect: CorpusEffect
    condition: str
    provenance: CorpusProvenance
    resource: str = ''
    inherited_from: str = ''
    original_principal_key: str = ''
    prospective: bool = False

    def __post_init__(self) -> None:
        """Keep fact identities canonical even when constructed from older caches."""
        object.__setattr__(self, 'principal_key', canonicalize_principal_key(self.principal_key))

    @property
    def conditional(self) -> bool:
        """Whether this fact requires an OCI where-clause predicate."""
        return bool(self.condition.strip())

    @property
    def inherited(self) -> bool:
        """Whether this effective fact was derived from an ancestor grant."""
        return bool(self.inherited_from)


@dataclass(frozen=True)
class CorpusExclusion:
    """Source statement omitted from regular permission-fact compilation.

    Attributes:
        statement_id: Snapshot-local identifier of the omitted statement.
        category: Machine-readable exclusion category.
        reason: Explanation of the admission failure or unavailable mapping.
        policy_name: Source policy display name.
        policy_ocid: Source policy OCID when available.
        statement_text: Original source text retained for diagnosis.
        action: Source effect.
        resource: Source resource name.
        verb: Source verb.
        prospective: Whether the source was a hypothetical statement.
    """

    statement_id: str
    category: str
    reason: str
    policy_name: str = ''
    policy_ocid: str = ''
    statement_text: str = ''
    action: str = ''
    resource: str = ''
    verb: str = ''
    prospective: bool = False


@dataclass(frozen=True)
class PolicyCorpus:
    """Immutable regular policy facts and transparent compilation diagnostics.

    Attributes:
        schema_version: Version of the compiled representation.
        built_at: UTC compilation timestamp, not the OCI collection timestamp.
        facts: Direct source contributions without descendant expansion.
        effective_facts: Direct and inherited contributions across known paths.
        exclusions: Source statements omitted from concrete permission facts.

    Notes:
        Conditions and denies remain contributions, not resolved access decisions.
        Coverage depends on the loaded inventory, validation, and permission mappings.
        Rebuild after replacing or changing repository data.
    """

    schema_version: int
    built_at: str
    facts: tuple[PolicyCorpusFact, ...] = field(default_factory=tuple)
    effective_facts: tuple[PolicyCorpusFact, ...] = field(default_factory=tuple)
    exclusions: tuple[CorpusExclusion, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready stable representation for adapters and storage."""
        return asdict(self)

    def summary(self) -> dict[str, int]:
        """Return compact counts for status surfaces and diagnostics."""
        return {
            'direct_fact_count': len(self.facts),
            'effective_fact_count': len(self.effective_facts),
            'exclusion_count': len(self.exclusions),
        }

    def inspect_page(self, section: str, *, page: int = 0, page_size: int = 100, query: str = '') -> dict[str, object]:
        """Convert only the requested debugger page to JSON-ready records."""
        sources = {
            'facts': self.facts,
            'effective_facts': self.effective_facts,
            'exclusions': self.exclusions,
        }
        if section not in sources:
            return {'error': f'Unknown policy corpus section: {section}'}
        records = sources[section]
        page = max(0, page)
        page_size = max(1, min(page_size, 250))
        offset = page * page_size
        needle = query.strip().casefold()
        if not needle:
            selected = records[offset : offset + page_size]
            total: int | None = len(records)
            has_more = offset + len(selected) < total
        else:
            matches = (item for item in records if needle in str(item).casefold())
            for _ in range(offset):
                if next(matches, None) is None:
                    break
            selected = []
            for _ in range(page_size + 1):
                item = next(matches, None)
                if item is None:
                    break
                selected.append(item)
            has_more = len(selected) > page_size
            selected = selected[:page_size]
            total = None
        return {
            'schema_version': self.schema_version,
            'section': section,
            'page': page + 1,
            'page_size': page_size,
            'total': total,
            'has_more': has_more,
            'records': [asdict(item) for item in selected],
        }


class PolicyCorpusBuilder:
    """Compile regular statements into the tool's representable permission model.

    Notes:
        Explicitly invalid statements and statements missing required fields/mappings
        are excluded with source evidence. Missing validity flags do not themselves
        exclude statements. Compilation neither validates through OCI nor evaluates
        request conditions. Use normal post-load enrichment before compiling.
    """

    SCHEMA_VERSION = 1

    def build(self, policy_repo: Any, *, additional_statements: list[dict[str, Any]] | None = None) -> PolicyCorpus:
        """Compile a detached regular corpus with an optional prospective overlay.

        Args:
            policy_repo: Loaded repository providing normalized regular statements,
                compartment paths, and optional permission reference data.
            additional_statements: Hypothetical statement dictionaries to compile beside
                the base sources. May include normalized fields under a normalized key.

        Returns:
            PolicyCorpus: Direct facts, descendant-expanded effective facts, exclusions,
            schema version, and compilation time. Does not mutate policies in OCI.
        """
        facts: list[PolicyCorpusFact] = []
        exclusions: list[CorpusExclusion] = []
        reference_data = getattr(policy_repo, 'permission_reference_repo', None)
        if not isinstance(reference_data, ReferenceDataRepo) or not reference_data.data.get('resources'):
            reference_data = ReferenceDataRepo()
            reference_data.load_data()

        source_statements = [(statement, False) for statement in (getattr(policy_repo, 'regular_statements', []) or [])]
        for index, raw_statement in enumerate(additional_statements or []):
            normalized = raw_statement.get('normalized')
            statement = {**(normalized if isinstance(normalized, dict) else {}), **raw_statement}
            statement.setdefault('internal_id', f'prospective:{index}')
            source_statements.append((statement, True))

        for source_index, (statement, is_prospective) in enumerate(source_statements):
            statement_id = str(statement.get('internal_id') or f'regular:{source_index}')
            exclusion_detail = {
                'policy_name': str(statement.get('policy_name') or ''),
                'policy_ocid': str(statement.get('policy_ocid') or ''),
                'statement_text': str(statement.get('statement_text') or ''),
                'action': str(statement.get('action') or ''),
                'resource': str(statement.get('resource') or ''),
                'verb': str(statement.get('verb') or ''),
                'prospective': is_prospective,
            }
            # Some programmatic callers compile a repository before the full
            # validation stage. Missing ``valid`` means no invalidity is known;
            # an explicit false is the only exclusion here.
            if statement.get('valid') is False:
                detail = '; '.join(str(item) for item in (statement.get('invalid_reasons') or []) if str(item))
                exclusions.append(
                    CorpusExclusion(
                        statement_id,
                        'invalid_statement',
                        detail or 'statement is not valid',
                        **exclusion_detail,
                    )
                )
                continue

            effective_path = str(statement.get('effective_path') or '').strip()
            if not effective_path:
                exclusions.append(
                    CorpusExclusion(
                        statement_id, 'missing_effective_path', 'effective path is unavailable', **exclusion_detail
                    )
                )
                continue

            principal_keys = _principal_keys(statement)
            if not principal_keys:
                exclusions.append(
                    CorpusExclusion(
                        statement_id, 'missing_principal_keys', 'principal keys are unavailable', **exclusion_detail
                    )
                )
                continue

            effect = str(statement.get('action') or 'allow').strip().lower()
            permissions = _permissions(statement, reference_data, effect)
            if not permissions:
                mapping_status = reference_data.get_resource_mapping_status(exclusion_detail['resource'])
                category = (
                    'known_no_permissions'
                    if mapping_status == 'known_no_permissions'
                    else 'unmapped_permission_expansion'
                )
                reason = (
                    'reference data marks this resource as having no concrete permissions'
                    if category == 'known_no_permissions'
                    else 'expanded permissions are unavailable for this verb/resource combination'
                )
                exclusions.append(
                    CorpusExclusion(
                        statement_id,
                        category,
                        reason,
                        **exclusion_detail,
                    )
                )
                continue

            if effect not in {'allow', 'deny'}:
                exclusions.append(
                    CorpusExclusion(
                        statement_id, 'missing_effect', 'authorization effect is unavailable', **exclusion_detail
                    )
                )
                continue

            where_clause = (
                statement.get('where_clause')
                or statement.get('conditions_where_clause')
                or statement.get('conditions')
                or ''
            )
            if isinstance(where_clause, dict):
                condition = str(where_clause.get('raw_text') or '')
            else:
                condition = str(where_clause).strip()
            provenance = CorpusProvenance(
                policy_name=str(statement.get('policy_name') or ''),
                policy_ocid=str(statement.get('policy_ocid') or ''),
                statement_id=statement_id,
                statement_text=str(statement.get('statement_text') or ''),
            )
            for principal_key in principal_keys:
                for permission in permissions:
                    facts.append(
                        PolicyCorpusFact(
                            principal_key=principal_key,
                            effective_path=effective_path,
                            grant_path=effective_path,
                            permission=permission,
                            effect=effect,
                            condition=condition,
                            provenance=provenance,
                            resource=str(statement.get('resource') or ''),
                            original_principal_key=_original_principal_key(statement, principal_key),
                            prospective=is_prospective,
                        )
                    )

        effective_facts = self._expand_effective_facts(facts, self._known_paths(policy_repo, facts))
        LOGGER.info(
            'Policy corpus built: direct_facts=%d effective_facts=%d exclusions=%d',
            len(facts),
            len(effective_facts),
            len(exclusions),
        )
        return PolicyCorpus(
            schema_version=self.SCHEMA_VERSION,
            built_at=datetime.now(UTC).isoformat(),
            facts=tuple(facts),
            effective_facts=effective_facts,
            exclusions=tuple(exclusions),
        )

    @staticmethod
    def _known_paths(policy_repo: Any, facts: list[PolicyCorpusFact]) -> set[str]:
        paths = {fact.effective_path for fact in facts if fact.effective_path}
        for compartment in getattr(policy_repo, 'compartments', []) or []:
            if isinstance(compartment, dict):
                path = str(compartment.get('hierarchy_path') or '').strip()
                if path:
                    paths.add(path)
        return paths

    @staticmethod
    def _expand_effective_facts(facts: list[PolicyCorpusFact], known_paths: set[str]) -> tuple[PolicyCorpusFact, ...]:
        effective: list[PolicyCorpusFact] = []
        sorted_paths = sorted(known_paths, key=_path_sort_key)
        expansions: dict[str, tuple[tuple[str, str], ...]] = {}
        for fact in facts:
            grant_path = fact.grant_path
            if grant_path not in expansions:
                descendants = [path for path in sorted_paths if _path_is_self_or_descendant(path, grant_path)]
                expansions[grant_path] = tuple(
                    (path, '' if path.casefold() == grant_path.casefold() else grant_path)
                    for path in (descendants or [grant_path])
                )
            for path, inherited_from in expansions[grant_path]:
                effective.append(replace(fact, effective_path=path, inherited_from=inherited_from))
        return tuple(effective)


def permissions_report_projection(corpus: PolicyCorpus) -> dict[str, object]:
    """Project corpus facts into the legacy Permissions Report payload shape.

    The report stays a convenient UI projection; it no longer owns a separate
    parser/permission-expansion/inheritance implementation.
    """
    report: dict[str, dict[str, dict[str, object]]] = {}
    resource_map: dict[tuple[str, str], str] = {}
    conditionals: dict[tuple[str, str, str], bool] = {}
    statements: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    direct_rows: list[dict[str, object]] = []

    for fact in corpus.facts:
        bucket = report.setdefault(fact.grant_path, {}).setdefault(
            fact.principal_key,
            {'allow': set(), 'deny': set(), 'subject_type': fact.principal_key.split(':', 1)[0]},
        )
        bucket[fact.effect].add(fact.permission)
        key = (fact.grant_path, fact.principal_key, fact.permission)
        conditionals[key] = conditionals.get(key, False) or fact.conditional
        if fact.provenance.statement_text and fact.provenance.statement_text not in statements[key]:
            statements[key].append(fact.provenance.statement_text)
        resource_map[(fact.grant_path, fact.principal_key)] = fact.resource

    for subjects in report.values():
        for subject_data in subjects.values():
            subject_data['allow'] = sorted(subject_data['allow'])
            subject_data['deny'] = sorted(subject_data['deny'])

    for fact in corpus.effective_facts:
        direct_rows.append(
            {
                'effective_path': fact.effective_path,
                'grant_path': fact.grant_path,
                'principal_key': fact.principal_key,
                'original_subject_key': fact.original_principal_key or fact.principal_key,
                'principal_kind': fact.principal_key.split(':', 1)[0],
                'action': fact.effect,
                'resource': fact.resource,
                'permission': fact.permission,
                'conditional': fact.conditional,
                'inherited': fact.inherited,
                'inherited_from': fact.inherited_from,
                'statement_text': fact.provenance.statement_text,
                'policy_name': fact.provenance.policy_name,
                'statement_id': fact.provenance.statement_id,
                'prospective': fact.prospective,
            }
        )

    return {
        'report': report,
        'resource_map': resource_map,
        'perm_conditionals': conditionals,
        'perm_statements': {key: '\n\n'.join(value) for key, value in statements.items()},
        'grant_rows': direct_rows,
        'exclusions': [asdict(item) for item in corpus.exclusions],
        'summary': {
            'statement_count': len({fact.provenance.statement_id for fact in corpus.facts}),
            'path_count': len(report),
            'principal_count': sum(len(subjects) for subjects in report.values()),
            'allow_grant_count': sum(1 for fact in corpus.facts if fact.effect == 'allow'),
            'deny_grant_count': sum(1 for fact in corpus.facts if fact.effect == 'deny'),
            'direct_grant_row_count': len(corpus.facts),
            'effective_grant_row_count': len(corpus.effective_facts),
            'skipped_statement_count': len(corpus.exclusions),
        },
    }


def _path_is_self_or_descendant(path: str, ancestor: str) -> bool:
    normalized_path = str(path or '').strip('/').casefold()
    normalized_ancestor = str(ancestor or '').strip('/').casefold()
    return normalized_path == normalized_ancestor or normalized_path.startswith(normalized_ancestor + '/')


def _path_sort_key(path: str) -> tuple[int, str]:
    return (len(str(path).split('/')), str(path).casefold())


def _principal_keys(statement: dict[str, Any]) -> tuple[str, ...]:
    """Return canonical principals, including condition-derived workload identities."""
    subject_type = str(statement.get('subject_type') or '').strip().casefold()
    if subject_type in {'any-user', 'any-group'}:
        values = _condition_values(statement)
        principal_type = values.get('request.principal.type', '')
        if principal_type:
            if principal_type.casefold() == 'workload':
                cluster = values.get('request.principal.cluster_id', 'unknown')
                namespace = values.get('request.principal.namespace', 'unknown')
                account = values.get('request.principal.service_account', 'unknown')
                return (f'oke-workload-identity:{cluster}/{namespace}/{account}',)
            compartment = values.get('request.principal.compartment.id', 'unknown')
            return (f'resource-principal:{principal_type}/{compartment}',)

    explicit = tuple(
        canonicalize_principal_key(value) for value in (statement.get('principal_keys') or []) if str(value).strip()
    )
    if explicit:
        return tuple(dict.fromkeys(explicit))

    subjects = statement.get('subject') or []
    if isinstance(subjects, str):
        subjects = [subjects]
    keys: list[str] = []
    for subject in subjects:
        if isinstance(subject, tuple | list) and len(subject) >= 2:
            domain, name = subject[0], subject[1]
        else:
            domain, name = None, subject
        name_text = str(name or '').strip()
        if name_text:
            keys.append(calculate_principal_key(subject_type, domain, name_text))
    return tuple(dict.fromkeys(key for key in keys if key))


def _original_principal_key(statement: dict[str, Any], fallback: str) -> str:
    """Return the declared subject key before a condition-derived specialization."""
    subject_type = str(statement.get('subject_type') or '').strip().casefold()
    subjects = statement.get('subject') or []
    if isinstance(subjects, str):
        subjects = [subjects]
    if subjects:
        first = subjects[0]
        if isinstance(first, tuple | list) and len(first) >= 2:
            return calculate_principal_key(subject_type, first[0], str(first[1]))
        return calculate_principal_key(subject_type, None, str(first))
    return fallback


def _permissions(statement: dict[str, Any], reference_data: ReferenceDataRepo, effect: str) -> tuple[str, ...]:
    """Return concrete permissions; never invent a permission for unknown catalog entries."""
    declared = statement.get('permission') or []
    if isinstance(declared, str):
        declared = [declared]
    permissions = tuple(str(value).strip().upper() for value in declared if str(value).strip())
    if permissions:
        return permissions
    resource = str(statement.get('resource') or '').strip()
    verb = str(statement.get('verb') or '').strip()
    if not resource or not verb:
        return ()
    return tuple(reference_data.get_permissions(resource, verb, action=effect))


def _condition_values(statement: dict[str, Any]) -> dict[str, str]:
    """Extract condition-atom values needed to identify derived principals."""
    structure = statement.get('where_clause_structure') or statement.get('where_clause')
    if not isinstance(structure, dict):
        structure = parse_condition_structure(str(statement.get('conditions') or statement.get('condition') or ''))
    values: dict[str, str] = {}
    for atom in structure.get('atoms', []) if isinstance(structure, dict) else []:
        if not isinstance(atom, dict):
            continue
        left = str(atom.get('normalized_left') or atom.get('left') or '').casefold()
        right = str(atom.get('right') or '').strip().strip('\'"')
        if left and right and left not in values:
            values[left] = right
    return values
