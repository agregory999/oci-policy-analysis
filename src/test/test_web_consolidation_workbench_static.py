"""Static contract coverage for the web consolidation workbench."""

from pathlib import Path


def test_web_workbench_renders_skipped_statements_for_new_and_saved_plans() -> None:
    page_html = Path('src/oci_policy_analysis/presentation/web/static/consolidation-workbench.html').read_text(
        encoding='utf-8'
    )

    assert 'skippedStatementsTable' in page_html
    assert 'function renderSkippedStatements(items)' in page_html
    assert 'renderSkippedStatements((d.plan||{}).skipped_statements||[])' in page_html
    assert 'renderSkippedStatements((run.plan||{}).skipped_statements||[])' in page_html


def test_web_proposal_drawer_displays_compartment_path_not_ocid() -> None:
    page_html = Path('src/oci_policy_analysis/presentation/web/static/consolidation-workbench.html').read_text(
        encoding='utf-8'
    )

    assert "`Compartment Path: ${row.policy_compartment || row['Policy Compartment'] || '-'}`" in page_html
    assert '`Compartment OCID:' not in page_html
