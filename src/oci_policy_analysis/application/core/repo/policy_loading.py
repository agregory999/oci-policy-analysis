"""Live policy discovery strategies and their shared detail/parsing pipeline."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from oci import pagination
from oci.exceptions import ServiceError
from oci.resource_search.models import StructuredSearchDetails

from oci_policy_analysis.application.core.models.models import BasePolicy, BasePolicyStatement
from oci_policy_analysis.application.core.support.logger import get_logger

if TYPE_CHECKING:
    from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository

logger = get_logger(component='core.repo.policy_loading')
POLICY_LOAD_METHODS = ('resource_search', 'compartment')


def validate_policy_load_method(value: str) -> str:
    """Validate a policy discovery method without silently changing load scope.

    Args:
        value: ``resource_search`` or ``compartment``.

    Returns:
        str: The validated method.

    Raises:
        ValueError: If the method is unsupported.
    """
    if value not in POLICY_LOAD_METHODS:
        raise ValueError(f'Unknown policy load method: {value!r}')
    return value


class LivePolicyLoader:
    """Discover policy IDs, fetch full details, then normalize on the calling thread.

    Args:
        repo: Initialized repository with its current compartment and IAM inventory.

    Attributes:
        repo: Repository receiving source policies and parsed statement evidence.

    Notes:
        API calls use the repository's in-memory diagnostics wrapper. Discovery
        and detail fetches paginate/use bounded workers; parser mutations remain
        serial. Individual API failures retain partial evidence and collection
        errors. Total discovery/detail failure raises instead of accepting an
        apparently empty snapshot. No cache files are written by this loader.
    """

    def __init__(self, repo: PolicyAnalysisRepository) -> None:
        self.repo = repo
        self._workers = repo.identity_api_workers

    def load(self, method: str) -> None:
        """Populate repository policy evidence using one explicit discovery method.

        Args:
            method: Validated discovery method; no automatic fallback is performed.

        Raises:
            ValueError: If the discovery method is unsupported.
            RuntimeError: If all compartment listings or all policy detail calls fail.
            Exception: For a failed tenancy-wide Resource Search request.
        """
        validate_policy_load_method(method)
        policy_ids = self._search_ids() if method == 'resource_search' else self._compartment_ids()
        policy_ids = sorted(set(policy_ids))
        logger.info('Discovered %d policies using %s (recursive=%s)', len(policy_ids), method, self.repo.recursive)
        loaded = 0
        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            for policy in executor.map(self._get_policy, policy_ids):
                if policy is not None:
                    self._parse_policy(policy)
                    loaded += 1
        if policy_ids and not loaded:
            raise RuntimeError('No discovered policies could be fetched. See API Calls for collection errors.')

    def _search_ids(self) -> list[str]:
        query = 'query policy resources'
        if not self.repo.recursive:
            query += f" where compartmentId = '{self.repo.tenancy_ocid}'"
        response = self.repo._api_call_with_logging(
            'ResourceSearchClient.search_resources',
            pagination.list_call_get_all_results,
            self.repo.resource_search_client.search_resources,
            search_details=StructuredSearchDetails(type='Structured', query=query),
            limit=1000,
        )
        return [item.identifier for item in response.data if item.identifier]

    def _compartment_ids(self) -> list[str]:
        compartments = [self.repo.tenancy_ocid]
        if self.repo.recursive:
            compartments.extend(comp['id'] for comp in self.repo.compartments if comp.get('id'))
        compartments = sorted(set(compartments))
        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            results = list(executor.map(self._list_compartment, compartments))
        if all(result is None for result in results):
            raise RuntimeError('Policies could not be listed in any selected compartment. See API Calls.')
        return [policy_id for result in results if result is not None for policy_id in result]

    def _list_compartment(self, compartment_id: str) -> list[str] | None:
        try:
            response = self.repo._api_call_with_logging(
                'IdentityClient.list_policies',
                pagination.list_call_get_all_results,
                self.repo.identity_client.list_policies,
                compartment_id=compartment_id,
                lifecycle_state='ACTIVE',
                limit=1000,
            )
            return [policy.id for policy in response.data if policy.id]
        except Exception as exc:
            if not isinstance(exc, ServiceError):
                logger.warning('Could not list policies in compartment %s: %s', compartment_id, exc)
            return None

    def _get_policy(self, policy_id: str):
        try:
            response = self.repo._api_call_with_logging(
                'IdentityClient.get_policy', self.repo.identity_client.get_policy, policy_id=policy_id
            )
            return response.data
        except Exception as exc:
            if not isinstance(exc, ServiceError):
                logger.warning('Could not fetch policy %s: %s', policy_id, exc)
            return None

    def _parse_policy(self, policy) -> None:
        freeform_tags = dict(policy.freeform_tags or {})
        defined_tags = dict(policy.defined_tags or {})
        tags = dict(freeform_tags)
        for namespace, values in defined_tags.items():
            if isinstance(values, dict):
                tags.update({f'{namespace}:{key}': value for key, value in values.items()})
            else:
                tags[str(namespace)] = str(values)
        # Always use the fetched policy compartment, including policies moved
        # since a Resource Search index entry was last updated.
        path = self.repo.get_compartment_path_for_ocid(policy.compartment_id)
        policy_obj = BasePolicy(
            policy_ocid=policy.id,
            policy_name=policy.name,
            description=policy.description or '',
            compartment_ocid=policy.compartment_id,
            compartment_path=path,
            creation_time=policy.time_created,
            tags=tags or None,
            freeform_tags=freeform_tags or None,
            defined_tags=defined_tags or None,
        )
        self.repo.policies.append(policy_obj)
        for text in policy.statements or []:
            statement = BasePolicyStatement(
                policy_name=policy.name,
                policy_ocid=policy.id,
                compartment_ocid=policy.compartment_id,
                compartment_path=path,
                statement_text=text,
                creation_time=str(policy.time_created),
                internal_id=hashlib.md5((text + policy.id).encode()).hexdigest(),
                parsed=False,
            )
            lower = text.strip().lower()
            if lower.startswith('define'):
                self.repo._parse_define_statement(policy_obj, statement)
            elif lower.startswith(('admit', 'deny admit')):
                self.repo._parse_admit_statement(policy_obj, statement)
            elif lower.startswith(('endorse', 'deny endorse')):
                self.repo._parse_endorse_statement(policy_obj, statement)
            else:
                self.repo._parse_statement(policy_obj, statement)
