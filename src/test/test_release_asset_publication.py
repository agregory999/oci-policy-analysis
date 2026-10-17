"""Prevent duplicate drafts from redirecting native release uploads."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'release_publisher', Path(__file__).parents[2] / 'run-build/publish_release.py'
)
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


class FakeReleases:
    def __init__(self):
        self.releases = [
            {'id': 10, 'tag_name': 'v7.0.0-dev.3', 'draft': True, 'assets': [{'name': 'installer.zip'}]},
            {'id': 11, 'tag_name': 'v7.0.0-dev.3', 'draft': False, 'assets': []},
            {'id': 12, 'tag_name': 'v7.0.0-dev.4', 'draft': True, 'assets': []},
        ]
        self.calls = []

    def list_releases(self):
        return self.releases

    def request(self, method, path, data, **kwargs):
        self.calls.append((method, path, data, kwargs))
        if method == 'POST':
            self.releases[1]['assets'].append({'name': 'installer.zip'})
        return {}


def test_existing_published_release_wins_over_duplicate_draft_and_reruns_are_safe(tmp_path):
    archive = tmp_path / 'installer.zip'
    archive.write_bytes(b'verified frozen executable')
    client = FakeReleases()
    assert PUBLISHER.publish(client, tag='v7.0.0-dev.3', archives=[archive], prerelease=True) == 11
    assert [call[1] for call in client.calls] == ['releases/11/assets?name=installer.zip', 'releases/11']
    assert json.loads(client.calls[-1][2]) == {'draft': False, 'prerelease': True}
    assert client.calls[0][3]['upload'] is True
    PUBLISHER.publish(client, tag='v7.0.0-dev.3', archives=[archive], prerelease=True)
    assert len([call for call in client.calls if call[0] == 'POST']) == 1
    assert all('releases/10' not in call[1] for call in client.calls)


def test_newest_matching_draft_is_used_when_tag_is_not_yet_published():
    releases = [
        {'id': 1, 'tag_name': 'v1', 'draft': True},
        {'id': 2, 'tag_name': 'v1', 'draft': True},
        {'id': 3, 'tag_name': 'v2', 'draft': False},
    ]
    assert PUBLISHER.select_release(releases, 'v1')['id'] == 2
    with pytest.raises(ValueError, match='did not create'):
        PUBLISHER.select_release(releases, 'v3')


def test_empty_native_artifact_set_is_not_published():
    client = FakeReleases()
    with pytest.raises(ValueError, match='No native archives'):
        PUBLISHER.publish(client, tag='v7.0.0-dev.3', archives=[], prerelease=True)
    assert client.calls == []
