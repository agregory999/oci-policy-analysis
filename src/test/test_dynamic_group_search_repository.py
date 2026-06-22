from types import SimpleNamespace

from oci_policy_analysis.application.core.models.models_iam import DynamicGroupSearch
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository


def _domain(name='Default'):
    return SimpleNamespace(id=f'ocid1.domain.{name.lower()}', display_name=name)


def _dynamic_group_summary(idx: int):
    return SimpleNamespace(id=f'dg-{idx}', display_name=f'DG {idx}')


def _dynamic_group_detail(idx: int):
    return SimpleNamespace(
        id=f'dg-{idx}',
        display_name=f'DG {idx}',
        description=f'Dynamic group {idx}',
        matching_rule=f"instance.compartment.id = 'ocid1.compartment.{idx}'",
        ocid=f'ocid1.dynamicgroup.{idx}',
        meta=SimpleNamespace(created='2026-01-01T00:00:00Z'),
        idcs_created_by=SimpleNamespace(ocid='ocid1.user.creator', display='creator@example.com'),
    )


class _FakeIdentityDomainClient:
    def __init__(self):
        self.list_calls = []

    def list_dynamic_resource_groups(self, **kwargs):
        self.list_calls.append(kwargs)
        start_index = kwargs['start_index']
        if start_index == 1:
            resources = [_dynamic_group_summary(idx) for idx in range(1, 1001)]
        elif start_index == 1001:
            resources = [_dynamic_group_summary(1001)]
        else:
            resources = []
        return SimpleNamespace(data=SimpleNamespace(resources=resources, total_results=1001))

    def get_dynamic_resource_group(self, dynamic_resource_group_id, **_kwargs):
        idx = int(dynamic_resource_group_id.split('-')[-1])
        return SimpleNamespace(data=_dynamic_group_detail(idx))


def test_fetch_dynamic_groups_for_domain_paginates_all_pages(monkeypatch):
    monkeypatch.setattr(
        'oci_policy_analysis.application.core.repo.policy_analysis_repository.THREADS',
        1,
    )
    repo = PolicyAnalysisRepository()
    client = _FakeIdentityDomainClient()

    dynamic_groups = repo._fetch_dynamic_groups_for_domain(_domain(), client)

    assert len(dynamic_groups) == 1001
    assert dynamic_groups[0]['dynamic_group_name'] == 'DG 1'
    assert dynamic_groups[-1]['dynamic_group_name'] == 'DG 1001'
    assert [call['start_index'] for call in client.list_calls] == [1, 1001]
    assert len(repo.dynamic_groups) == 1001


def test_filter_dynamic_groups_supports_in_use_true_and_false():
    repo = PolicyAnalysisRepository()
    repo.dynamic_groups = [
        {'domain_name': 'Default', 'dynamic_group_name': 'Used', 'in_use': True},
        {'domain_name': 'Default', 'dynamic_group_name': 'Unused', 'in_use': False},
    ]

    used = repo.filter_dynamic_groups(DynamicGroupSearch(in_use=True))
    unused = repo.filter_dynamic_groups(DynamicGroupSearch(in_use=False))

    assert [dg['dynamic_group_name'] for dg in used] == ['Used']
    assert [dg['dynamic_group_name'] for dg in unused] == ['Unused']


def test_filter_dynamic_groups_treats_in_use_none_as_unfiltered():
    repo = PolicyAnalysisRepository()
    repo.dynamic_groups = [
        {'domain_name': 'Default', 'dynamic_group_name': 'Used', 'in_use': True},
        {'domain_name': 'Default', 'dynamic_group_name': 'Unused', 'in_use': False},
    ]

    results = repo.filter_dynamic_groups(DynamicGroupSearch(in_use=None))

    assert [dg['dynamic_group_name'] for dg in results] == ['Used', 'Unused']
