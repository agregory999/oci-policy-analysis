"""Focused helper coverage for the desktop policy recommendations tab."""

from types import SimpleNamespace

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
