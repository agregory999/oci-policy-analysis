"""Documentation contracts for the two distinct limited modes."""

from pathlib import Path

DOCS = Path('docs/source')


def test_limited_modes_document_separates_compliance_loading_from_web_user_access() -> None:
    page = (DOCS / 'limited_modes.md').read_text(encoding='utf-8')

    assert '# Limited Modes' in page
    assert '## Limited Compliance Loading' in page
    assert '## Limited Web User' in page
    assert 'Limited Compliance Loading does not grant or restrict a user' in page
    assert 'Limited Web User does not change which CIS artifacts were imported' in page
    assert not (DOCS / 'limited_mode.md').exists()


def test_usage_and_user_guide_link_to_the_relevant_limited_mode_section() -> None:
    usage = (DOCS / 'usage.md').read_text(encoding='utf-8')
    user_guide = (DOCS / 'user_guide.md').read_text(encoding='utf-8')
    index = (DOCS / 'index.rst').read_text(encoding='utf-8')

    assert 'limited_modes.md#limited-compliance-loading' in usage
    assert 'limited_modes.md#limited-compliance-loading' in user_guide
    assert 'limited_modes.md#limited-web-user' in user_guide
    assert '   limited_modes' in index
