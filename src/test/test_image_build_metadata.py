"""Build identity is immutable image metadata, independent of operator environment."""

import json

from oci_policy_analysis import _version
from oci_policy_analysis.presentation.web.api import routes_core


def test_build_metadata_is_read_from_image_resource(monkeypatch, tmp_path):
    (tmp_path / '_build_info.json').write_text(
        json.dumps(
            {
                'image_tag': '7.0-web-test',
                'built_at': '2026-10-12T20:00:00Z',
                'private_value': 'omit',
            }
        )
    )
    monkeypatch.setattr(_version, 'files', lambda _package: tmp_path)
    metadata = routes_core.app_metadata()
    assert metadata['image_tag'] == '7.0-web-test'
    assert metadata['built_at'] == '2026-10-12T20:00:00Z'
    assert metadata['server_started_at']
    assert 'private_value' not in metadata


def test_local_runs_have_no_fake_image_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(_version, 'files', lambda _package: tmp_path)
    assert _version.get_image_build_metadata() == {}
