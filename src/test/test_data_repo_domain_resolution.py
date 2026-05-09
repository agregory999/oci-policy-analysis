from types import SimpleNamespace

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository


def test_get_domain_name_from_ocid_handles_dict_and_object_domains():
    repo = PolicyAnalysisRepository()
    repo.identity_domains = [
        SimpleNamespace(id='ocid1.domain.oc1..object', display_name='Object Domain'),
        {'id': 'ocid1.domain.oc1..dict', 'display_name': 'Dict Domain'},
    ]

    assert repo._get_domain_name_from_ocid('ocid1.domain.oc1..object') == 'Object Domain'
    assert repo._get_domain_name_from_ocid('ocid1.domain.oc1..dict') == 'Dict Domain'
    assert repo._get_domain_name_from_ocid('ocid1.domain.oc1..missing') == 'Default'
    assert repo._get_domain_name_from_ocid('') == 'Default'
