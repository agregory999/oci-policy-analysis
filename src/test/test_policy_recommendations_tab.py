"""Focused helper coverage for the desktop policy recommendations tab."""

from types import SimpleNamespace

from oci_policy_analysis.application.core.engine.recommendation_actions import cleanup_detail_sections
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import (
    PolicyRecommendationsTab,
    _compartment_filter_label,
    _normalize_compartment_path,
    _path_is_same_or_descendant,
)


def test_supersession_compartment_filter_label_includes_hierarchy_level() -> None:
    assert _compartment_filter_label('ROOT') == 'ROOT (Level 1)'
    assert _compartment_filter_label('ROOT/cloud-engineering') == 'ROOT/cloud-engineering (Level 2)'
    assert _compartment_filter_label('ROOT/cloud-engineering/andrew') == 'ROOT/cloud-engineering/andrew (Level 3)'


def test_supersession_compartment_filter_normalizes_root_casing() -> None:
    assert _normalize_compartment_path('root/cloud-engineering') == 'ROOT/cloud-engineering'


def test_supersession_compartment_filter_includes_descendants_but_not_siblings() -> None:
    assert _path_is_same_or_descendant('ROOT/cloud-engineering', 'ROOT/cloud-engineering')
    assert _path_is_same_or_descendant('ROOT/cloud-engineering/andrew', 'ROOT/cloud-engineering')
    assert not _path_is_same_or_descendant('ROOT/finance', 'ROOT/cloud-engineering')


def test_show_full_policy_clears_other_filters_and_scopes_to_policy_compartment() -> None:
    class Value:
        def __init__(self) -> None:
            self.value = 'previous filter'

        def set(self, value: str) -> None:
            self.value = value

    class PoliciesTab:
        def __init__(self) -> None:
            self.hierarchy_filter_var = Value()
            self.policy_filter_var = Value()
            self.clear_calls = 0
            self.update_calls = 0

        def clear_policy_filters(self) -> None:
            self.clear_calls += 1

        def update_policy_output(self) -> None:
            self.update_calls += 1

    class Notebook:
        def __init__(self) -> None:
            self.selected = None

        def select(self, *, tab_id: int) -> None:
            self.selected = tab_id

    policies_tab = PoliciesTab()
    notebook = Notebook()
    tab = SimpleNamespace(app=SimpleNamespace(notebook=notebook, policies_tab=policies_tab))

    PolicyRecommendationsTab._show_full_policy_in_main_analysis(
        tab,
        'Shared Policy',
        'ROOT/cloud-engineering',
    )

    assert notebook.selected == 2
    assert policies_tab.clear_calls == 1
    assert policies_tab.hierarchy_filter_var.value == 'ROOT/cloud-engineering'
    assert policies_tab.policy_filter_var.value == 'Shared Policy'
    assert policies_tab.update_calls == 1


def test_cleanup_dynamic_group_detail_sets_real_filters_and_clears_stale_filters(monkeypatch):
    messages = []
    monkeypatch.setattr('tkinter.messagebox.showinfo', lambda *args: messages.append(args))

    class Value:
        def __init__(self, value='old filter'):
            self.value = value

        def set(self, value):
            self.value = value

    selected = []
    refreshed = []
    dg_tab = SimpleNamespace(
        domain_filter_var=Value(),
        dg_name_var=Value(),
        dg_rule_var=Value(),
        dg_ocid_var=Value(),
        chk_show_instance_principals=Value(True),
        chk_show_not_in_use=Value(True),
        _update_dg_output=lambda: refreshed.append(True),
    )
    tab = SimpleNamespace(
        app=SimpleNamespace(
            notebook=SimpleNamespace(select=lambda tab_id: selected.append(tab_id)),
            dynamic_groups_tab=dg_tab,
        )
    )

    PolicyRecommendationsTab._on_focus_cleanup_row(
        tab, {'Type': 'Unused Dynamic Group', 'Name': 'Default/all-exacs-DG'}
    )

    assert selected == [dg_tab]
    assert dg_tab.domain_filter_var.value == 'Default'
    assert dg_tab.dg_name_var.value == 'all-exacs-DG'
    assert dg_tab.dg_rule_var.value == ''
    assert dg_tab.dg_ocid_var.value == ''
    assert dg_tab.chk_show_instance_principals.value is False
    assert dg_tab.chk_show_not_in_use.value is False
    assert refreshed == [True]
    assert messages == []


def test_cleanup_details_preserve_full_statement_and_offer_guidance_for_each_type():
    statement = 'allow any-user to read objects in tenancy // ' + 'explanation ' * 30
    checks = {
        'Invalid Statement': 'identity domain',
        'Group w/ No Users': 'Zero members does not mean zero policy references',
        'Unused Dynamic Group': 'planned use',
        'Overly Broad Statement': 'tighter permissions',
        'Any-user Without Where': "where all {request.principal.type = 'autonomousdatabase'}",
    }
    for cleanup_type, expected_guidance in checks.items():
        sections = dict(
            cleanup_detail_sections(
                {'Type': cleanup_type, 'Name': statement[:200], 'Reason': 'Specific finding'},
                {'statement_text': statement, 'policy_name': 'Example Policy'},
            )
        )
        assert sections['Item'] == ['Policy: Example Policy', statement]
        assert sections['Why this was flagged'] == ['Specific finding']
        assert expected_guidance in '\n'.join(sections['Potential actions'])
