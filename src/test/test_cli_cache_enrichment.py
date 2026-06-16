import sys

from oci_policy_analysis import cli as cli_module


def test_cli_live_load_saves_cache_after_effective_path_enrichment(monkeypatch):
    events: list[str] = []
    saved_effective_paths: list[str | None] = []

    class FakeRepo:
        def __init__(self):
            self.tenancy_name = 'test-tenancy'
            self.tenancy_ocid = 'ocid1.tenancy.oc1..example'
            self.data_as_of = '2026-06-15T00:00:00Z'
            self.identity_domains = []
            self.dynamic_groups = []
            self.users = []
            self.groups = []
            self.compartments = []
            self.cross_tenancy_statements = []
            self.regular_statements = [
                {
                    'statement_text': 'Allow group Admins to read buckets in tenancy',
                    'effective_path': '',
                }
            ]

        def initialize_client(self, **_kwargs):
            events.append('initialize_client')
            return True

        def load_complete_identity_domains(self):
            events.append('load_complete_identity_domains')
            return True

        def load_policies_and_compartments(self):
            events.append('load_policies_and_compartments')
            return True

    class FakeCacheManager:
        def save_combined_cache(self, *, policy_analysis, **_kwargs):
            events.append('save_combined_cache')
            saved_effective_paths.extend(stmt.get('effective_path') for stmt in policy_analysis.regular_statements)
            return 'test-cache'

    class FakePolicyIntelligenceEngine:
        def __init__(self, policy_repo):
            self.policy_repo = policy_repo

        def calculate_all_effective_compartments(self):
            events.append('calculate_all_effective_compartments')
            for stmt in self.policy_repo.regular_statements:
                stmt['effective_path'] = 'root'

        def find_invalid_statements(self):
            events.append('find_invalid_statements')

        def run_dg_in_use_analysis(self):
            events.append('run_dg_in_use_analysis')

    monkeypatch.setattr(sys, 'argv', ['oci-policy-analysis-cli', '--profile', 'DEFAULT'])
    monkeypatch.setattr(cli_module, 'PolicyAnalysisRepository', FakeRepo)
    monkeypatch.setattr(cli_module, 'CacheManager', FakeCacheManager)
    monkeypatch.setattr(cli_module, 'PolicyIntelligenceEngine', FakePolicyIntelligenceEngine)

    cli_module.main()

    assert events.index('calculate_all_effective_compartments') < events.index('save_combined_cache')
    assert saved_effective_paths == ['root']
