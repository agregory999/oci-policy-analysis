from types import SimpleNamespace

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.presentation.formatters import for_display_group


def test_legacy_idcs_group_mappings_attach_to_the_target_default_group() -> None:
    repo = PolicyAnalysisRepository()
    repo.tenancy_ocid = 'ocid1.tenancy.oc1..example'
    repo.groups = [
        {
            'domain_name': 'Default',
            'group_name': 'TargetAdmins',
            'group_ocid': 'ocid1.group.oc1..target',
        }
    ]
    repo.identity_client = SimpleNamespace(
        list_identity_providers=lambda *_args, **_kwargs: None,
        list_idp_group_mappings=lambda *_args, **_kwargs: None,
    )
    provider = SimpleNamespace(id='ocid1.identityprovider.oc1..idcs', name='OracleIdentityCloudService')
    mapping = SimpleNamespace(
        id='ocid1.idpgroupmapping.oc1..mapping',
        group_id='ocid1.group.oc1..target',
        idp_group_name='SourceAdmins',
        lifecycle_state='ACTIVE',
        time_created='2026-09-22T00:00:00Z',
    )

    def api_call(label, *_args, **_kwargs):
        return SimpleNamespace(data=[provider] if label.endswith('list_identity_providers') else [mapping])

    repo._api_call_with_logging = api_call  # type: ignore[method-assign]
    repo._load_legacy_idcs_group_mappings()

    assert repo.idp_group_mappings[0]['target_group_name'] == 'TargetAdmins'
    assert repo.groups[0]['mapped_idp_groups'] == ['OracleIdentityCloudService/SourceAdmins']
    assert for_display_group(repo.groups[0])['Mapped IdP Groups'] == 'OracleIdentityCloudService/SourceAdmins'
