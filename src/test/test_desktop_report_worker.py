"""The Tk report worker returns control without sharing Tk widgets with its thread."""

import threading
from types import SimpleNamespace

from oci_policy_analysis.presentation.desktop import reports_tab


def test_report_generation_runs_off_gui_and_publishes_only_when_complete(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    callbacks = []

    class Widget:
        def __init__(self, *args, **kwargs):
            self.state = {}

        def configure(self, **kwargs):
            self.state.update(kwargs)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    monkeypatch.setattr(reports_tab.tk, 'Toplevel', Widget)
    monkeypatch.setattr(reports_tab.ttk, 'Label', Widget)
    monkeypatch.setattr(reports_tab.ttk, 'Progressbar', Widget)

    def generate(report_id):
        entered.set()
        assert release.wait(3)
        return {'report_id': report_id}

    monkeypatch.setattr(reports_tab, 'ReportsService', lambda context: SimpleNamespace(get_report=generate))
    button, export = Widget(), Widget()
    results = []
    tab = SimpleNamespace(
        app=SimpleNamespace(app_context=object()),
        report_choices={'Inventory': 'policy-inventory'},
        report_var=SimpleNamespace(get=lambda: 'Inventory'),
        status_var=SimpleNamespace(set=results.append),
        run_button=button,
        export_button=export,
        winfo_toplevel=lambda: None,
        after=lambda _delay, callback: callbacks.append(callback),
        _completion_message=lambda: 'Done',
        _refresh_preview=lambda: results.append('preview'),
    )
    try:
        reports_tab.ReportsTab.run_selected_report(tab)
        assert entered.wait(2)
        assert tab._report_worker.is_alive()
        assert export.state['state'] == 'disabled'
        release.set()
        tab._report_worker.join(2)
        callbacks.pop(0)()
        assert tab._report_worker is None
        assert tab._report == {'report_id': 'policy-inventory'}
        assert export.state['state'] == 'normal' and results[-1] == 'preview'
    finally:
        release.set()
