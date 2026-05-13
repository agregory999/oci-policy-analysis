from __future__ import annotations

from typing import Any

from oci_policy_analysis.web.api import routes_core


class _Repo:
    def __init__(self) -> None:
        self.regular_statements: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = [
            {'domain_name': 'Default', 'user_name': 'alice'},
            {'domain_name': 'CorpDomainA', 'user_name': 'alice'},
        ]
        self.last_filters: dict[str, Any] | None = None

    def filter_policy_statements(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        self.last_filters = dict(filters)
        return []

    def get_groups_for_user(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        domain = str(user.get('domain_name') or 'Default')
        if domain == 'Default':
            return [{'domain_name': 'Default', 'group_name': 'DBA'}]
        return [{'domain_name': 'CorpDomainA', 'group_name': 'DBA'}]


class _Ctx:
    def __init__(self, repo: _Repo) -> None:
        self.policy_repo = repo


def test_by_subjects_expands_user_principal_keys_to_group_keys(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(repo))

    payload = {
        'principal_keys': ['user:Default/alice'],
        'include_any_subjects': False,
    }
    result = routes_core.filter_policies_by_subjects(payload)

    assert repo.last_filters is not None
    assert repo.last_filters.get('principal_key') == ['group:Default/DBA']
    assert result.get('selected_groups') == [{'Domain': 'Default', 'Group': 'DBA'}]


def test_by_subjects_group_principal_keys_pass_through(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(repo))

    payload = {
        'principal_keys': ['group:CorpDomainA/DBA'],
        'include_any_subjects': False,
    }
    result = routes_core.filter_policies_by_subjects(payload)

    assert repo.last_filters is not None
    assert repo.last_filters.get('principal_key') == ['group:CorpDomainA/DBA']
    assert result.get('selected_groups') == [{'Domain': 'CorpDomainA', 'Group': 'DBA'}]


def test_by_subjects_empty_selector_returns_no_results(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(repo))

    payload = {
        'principal_keys': [],
        'include_any_subjects': False,
    }
    result = routes_core.filter_policies_by_subjects(payload)

    assert repo.last_filters is None
    assert result.get('matched') == 0
    assert result.get('statements') == []
