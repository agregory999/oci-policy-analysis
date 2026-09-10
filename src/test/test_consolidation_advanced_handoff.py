"""Consolidation handoff opens advanced tabs only after accepting valid candidates."""

from types import SimpleNamespace

import pytest
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab


@pytest.mark.parametrize(
    'visible,confirmed,accepted,expected',
    [
        (False, True, True, ['enable', 'open']),
        (True, True, True, ['open']),
        (False, False, True, []),
        (False, True, False, []),
    ],
)
def test_handoff_enables_advanced_tabs_only_when_needed(monkeypatch, visible, confirmed, accepted, expected):
    events, prompts = [], []
    app = SimpleNamespace(advanced_tabs_visible=visible)

    def enable():
        events.append('enable')
        app.advanced_tabs_visible = True

    def confirm(title, message):
        prompts.append(message)
        return confirmed

    app.settings_tab = SimpleNamespace(_toggle_advanced_tabs=enable)
    app.consolidation_tab = SimpleNamespace(
        select_candidate_statements=lambda ids, **kwargs: ids if accepted else set()
    )
    app.notebook = SimpleNamespace(select=lambda tab: events.append('open'))
    monkeypatch.setattr('tkinter.messagebox.askyesno', confirm)
    monkeypatch.setattr('tkinter.messagebox.showwarning', lambda *args: None)
    PolicyRecommendationsTab._on_create_consolidation_plan(
        SimpleNamespace(app=app),
        [
            {
                'Handoff Mode': 'supported',
                'Recommended Strategy': 'Pack',
                'Statement Internal IDs': ['s1'],
            }
        ],
    )
    assert events == expected
    assert ('Advanced Tabs will be enabled' in prompts[0]) is (not visible)


def test_create_plan_button_is_available_with_hidden_advanced_tabs():
    states = []
    tab = SimpleNamespace(
        app=SimpleNamespace(advanced_tabs_visible=False, consolidation_tab=object()),
        consolidation_plan_button=SimpleNamespace(configure=lambda **kwargs: states.append(kwargs['state'])),
    )
    PolicyRecommendationsTab.update_consolidation_plan_availability(tab)
    assert states == ['normal']
    tab.app.consolidation_tab = None
    PolicyRecommendationsTab.update_consolidation_plan_availability(tab)
    assert states[-1] == 'disabled'
