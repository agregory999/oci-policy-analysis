"""Desktop graph orchestration stays aligned with the web projection."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from oci_policy_analysis.application.core.policy_corpus import CorpusProvenance, PolicyCorpus, PolicyCorpusFact
from oci_policy_analysis.presentation.desktop.policy_graph_tab import PolicyGraphTab
from oci_policy_analysis.presentation.web.api import routes_core
from oci_policy_analysis.presentation.web.main import app


class _Variable:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _corpus(principal='group:Default/Ops'):
    source = CorpusProvenance(
        'Graph policy', 'ocid1.policy.test', 'one', 'Allow group Ops to manage objects in tenancy'
    )
    return PolicyCorpus(
        schema_version=1,
        built_at='now',
        facts=tuple(
            PolicyCorpusFact(
                principal, 'ROOT/network', 'ROOT/network', permission, 'allow', '', source, resource='objects'
            )
            for permission in ('OBJECT_CREATE', 'OBJECT_READ')
        ),
    )


def _tab(corpus):
    # Test the actual desktop controller without requiring a windowing server.
    tab = object.__new__(PolicyGraphTab)
    tab.app = SimpleNamespace(app_context=SimpleNamespace(corpus=corpus))
    tab.filters = {name: _Variable() for name in ('principal', 'resource', 'path', 'query', 'effect')}
    tab._pending_search = None
    tab.result = {}
    tab._rows = {}
    tab._close_detail = MagicMock()
    tab._draw_graph = MagicMock()
    for name in ('summary', 'match_count', 'page_label'):
        setattr(tab, name, _Variable())
    for name in (
        'path_entry',
        'principal_entry',
        'path_title',
        'previous_button',
        'next_button',
        'table',
        'canvas',
        'path_canvas',
        'detail_menu',
    ):
        setattr(tab, name, MagicMock())
    return tab


def test_desktop_permission_search_matches_web_and_keeps_complete_details(monkeypatch):
    corpus = _corpus()
    tab = _tab(corpus)
    tab.filters['resource'].set('object_create')
    tab.filters['path'].set('network')
    tab.refresh_view()
    monkeypatch.setattr(routes_core, 'get_context', lambda: tab.app.app_context)
    response = TestClient(app).get(
        '/analysis/policy-graph',
        params={
            'resource': 'object_create',
            'path': 'network',
            'overview': 'true',
            'all_results': 'true',
        },
    )
    assert response.status_code == 200
    assert tab.result == response.json()
    assert tab._rows['0']['permissions'] == ['OBJECT_CREATE', 'OBJECT_READ']


def test_graph_card_focus_preserves_other_filters_and_returns_to_first_page():
    tab = _tab(_corpus())
    tab.filters['path'].set('network')
    tab.filters['query'].set('Graph policy')
    tab._focus_node({'resource': 'objects', 'effect': 'allow'})
    assert tab.filters['path'].get() == 'network'
    assert tab.filters['query'].get() == 'Graph policy'
    assert tab.result['page'] == 1
    assert tab.result['total'] == 1
    assert tab.result['principals'] == [{'principal': 'group:default/ops', 'grant_count': 1}]


def test_refresh_reads_replaced_corpus_and_reset_clears_stale_rows():
    tab = _tab(_corpus())
    tab.filters['principal'].set('ops')
    tab.refresh_view()
    assert tab.result['total'] == 1
    tab.app.app_context.corpus = _corpus('group:Default/Audit')
    tab.refresh_view()
    assert tab.result['total'] == 0
    tab.app.app_context.corpus = None
    tab.reset_for_data_load()
    assert tab.result['loaded'] is False
    assert tab._rows == {}
    assert all(value.get() == '' for value in tab.filters.values())
    tab._close_detail.assert_called_with(restore_focus=False)


def test_initial_and_cleared_graph_has_no_arbitrary_grants():
    tab = _tab(_corpus())
    tab.refresh_view()
    assert tab.result['needs_filter'] is True
    assert tab._rows == {}
    tab._focus_node({'principal': 'group:default/ops'})
    assert tab._rows == {}
    assert tab.filters['principal'].get() == ''
    tab.filters['principal'].set('ops')
    tab.refresh_view()
    assert len(tab._rows) == 1
    tab._clear_filters()
    assert tab.result['needs_filter'] is True
    assert tab._rows == {}


def test_right_click_selects_clicked_row_and_offers_details_without_opening_modal():
    tab = _tab(_corpus())
    tab._open_selected = MagicMock()
    tab.table.identify_row.return_value = 'target'
    tab.table.identify_region.return_value = 'cell'
    assert tab._table_right_click(SimpleNamespace(x=20, y=40, x_root=120, y_root=140)) == 'break'
    tab.table.selection_set.assert_called_once_with('target')
    tab.table.focus.assert_called_once_with('target')
    tab.detail_menu.tk_popup.assert_called_once_with(120, 140)
    tab.detail_menu.grab_release.assert_called_once()
    tab._open_selected.assert_not_called()
    tab.detail_menu.tk_popup.reset_mock()
    tab.table.identify_row.return_value = ''
    tab._table_right_click(SimpleNamespace(x=20, y=400))
    tab._open_selected.assert_not_called()
    tab.detail_menu.tk_popup.assert_not_called()


def test_conditional_grant_menu_sends_original_condition_to_tester():
    tab = _tab(_corpus())
    tab.app.open_condition_tester_with_condition = MagicMock()
    condition = "request.permission = 'OBJECT_CREATE'"
    tab._rows['target'] = {'condition': f'where {condition}'}
    tab.table.identify_row.return_value = 'target'
    tab.table.identify_region.return_value = 'cell'
    tab._table_right_click(SimpleNamespace(x=20, y=40, x_root=120, y_root=140))
    commands = tab.detail_menu.add_command.call_args_list
    assert commands[-1].kwargs['label'] == 'Test Condition in Condition Tester Tab'
    commands[-1].kwargs['command']()
    tab.app.open_condition_tester_with_condition.assert_called_once_with(condition)
    tab.detail_menu.add_command.reset_mock()
    tab._rows['target']['condition'] = ''
    tab._table_right_click(SimpleNamespace(x=20, y=40, x_root=120, y_root=140))
    assert tab.detail_menu.add_command.call_count == 1


def test_desktop_table_includes_all_grants_and_conditional_flag():
    from dataclasses import replace

    base = _corpus().facts[0]
    facts = tuple(
        replace(
            base,
            principal_key=f'group:Default/ops{i:02}',
            condition="request.permission = 'OBJECT_CREATE'" if i == 20 else '',
        )
        for i in range(21)
    )
    tab = _tab(PolicyCorpus(schema_version=1, built_at='now', facts=facts))
    tab.filters['resource'].set('objects')
    tab.refresh_view()
    assert len(tab._rows) == 21
    values = [call.kwargs['values'] for call in tab.table.insert.call_args_list]
    assert sum(row[-2] == 'Yes' for row in values) == 1
    assert sum(row[-2] == 'No' for row in values) == 20


def test_graph_condition_handoff_populates_visible_tester_before_generating_inputs():
    from functools import partial

    from oci_policy_analysis.main import App
    from oci_policy_analysis.presentation.desktop.condition_tester_tab import ConditionTesterTab

    tab = _tab(_corpus())
    condition = "request.permission = 'OBJECT_CREATE'"
    visible_text = _Variable('previous condition')
    text_widget = MagicMock()
    text_widget.delete.side_effect = lambda *_args: visible_text.set('')
    text_widget.insert.side_effect = lambda _position, text: visible_text.set(text)
    text_widget.get.side_effect = lambda *_args: visible_text.get()
    tester = SimpleNamespace(clause_text=text_widget, clause_var=_Variable('previous condition'))
    tester.set_clause_text = partial(ConditionTesterTab.set_clause_text, tester)
    # Input generation consumes the visible Text widget, rather than clause_var.
    generated = []
    tester._generate_inputs = lambda: generated.append(tester.clause_text.get('1.0', 'end').strip())
    tab.app.condition_tester_tab = tester
    tab.app.notebook = MagicMock()
    tab.app.open_condition_tester_with_condition = partial(App.open_condition_tester_with_condition, tab.app)
    tab._rows['target'] = {
        'condition': '',
        'statement_text': f'Allow group Ops to manage objects in tenancy where {condition}',
    }
    tab.table.identify_row.return_value = 'target'
    tab.table.identify_region.return_value = 'cell'
    tab._table_right_click(SimpleNamespace(x=20, y=40, x_root=120, y_root=140))
    tab.detail_menu.add_command.call_args_list[-1].kwargs['command']()
    assert visible_text.get() == condition
    assert tester.clause_var.get() == condition
    assert generated == [condition]
    tab.app.notebook.select.assert_called_once_with(tester)
