"""Read/list PAR compatibility, pagination, and sanitized failures."""

import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from oci_policy_analysis.analytics import loader


class Response:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_json_pagination_deduplication_date_filter_and_escaped_object_keys(monkeypatch):
    calls = []
    first = 'events/2026/10/14/abc123/first.json'
    second = 'events/2026/10/17/abc123/run with spaces.json'

    def request(req, **kwargs):
        assert req.get_method() == 'GET'
        calls.append(req.full_url)
        if parse_qs(urlsplit(req.full_url).query).get('start'):
            return Response({'objects': [{'name': first}, {'name': second}]})
        return Response(
            {
                'objects': [{'name': first}, {'name': 'events/2026/10/17/abc123/not-json.txt'}],
                'nextStartWith': 'next/with spaces',
            }
        )

    monkeypatch.setattr(loader.request, 'urlopen', request)
    refs = loader.list_usage_objects_for_dates(
        'https://example.invalid/read/', date(2026, 10, 17), date(2026, 10, 17), strict=True
    )
    assert refs == [(second, 'abc123')]
    assert parse_qs(urlsplit(calls[1]).query)['start'] == ['next/with spaces']

    def doc(req, **kwargs):
        assert 'run%20with%20spaces.json' in req.full_url
        return Response({'run_id': 'r', 'app_version': '4', 'started_at': '2026-10-17T00:00:00Z'})

    monkeypatch.setattr(loader.request, 'urlopen', doc)
    assert loader._load_single_usage_doc('https://example.invalid/read/', second, 'abc123').run_id == 'r'


@pytest.mark.parametrize(
    'listing',
    [
        [{'name': 'events/2025/01/01/abc123/a.json'}],
        {'items': [{'Name': 'events/2025/01/01/abc123/a.json'}]},
        b'<ListBucketResult xmlns="urn:example"><Contents><Key>events/2025/01/01/abc123/a.json</Key></Contents></ListBucketResult>',
    ],
)
def test_legacy_listing_shapes(listing, monkeypatch):
    monkeypatch.setattr(loader.request, 'urlopen', lambda *args, **kwargs: Response(listing))
    assert loader.list_usage_objects_for_dates('https://example.invalid/', None, None, strict=True) == [
        ('events/2025/01/01/abc123/a.json', 'abc123')
    ]


def test_listing_failure_is_not_reported_as_clean_zero_and_never_exposes_url(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError('https://private.invalid/p/SECRET/')

    monkeypatch.setattr(loader.request, 'urlopen', fail)
    with pytest.raises(ValueError, match='Unable to list') as error:
        loader.load_usage_report(None, None, base_url='https://private.invalid/p/SECRET/')
    assert 'SECRET' not in str(error.value) + caplog.text
    assert loader.list_usage_objects_for_dates('https://example.invalid/', None, None) == []


def test_partial_reads_report_skipped_counts_and_ignore_bad_documents(monkeypatch):
    refs = [('events/2026/10/17/abc123/a.json', 'abc123'), ('events/2026/10/17/abc123/b.json', 'abc123')]
    monkeypatch.setattr(loader, 'list_usage_objects_for_dates', lambda *args, **kwargs: refs)

    def read(base, key, suffix):
        if key.endswith('a.json'):
            return loader.UsageDoc.from_dict(
                {'run_id': 'a', 'app_version': '7', 'started_at': '2026-10-17T00:00:00Z'}, tenancy_suffix=suffix
            )

    monkeypatch.setattr(loader, '_load_single_usage_doc', read)
    result = loader.load_usage_report(None, None, base_url='https://example.invalid/')
    assert len(result.docs) == 1 and result.listed == 2 and result.skipped == 1


def test_repeated_pagination_marker_cannot_loop_forever(monkeypatch):
    monkeypatch.setattr(
        loader.request, 'urlopen', lambda *args, **kwargs: Response({'objects': [], 'nextStartWith': 'same'})
    )
    with pytest.raises(ValueError):
        loader.list_usage_objects_for_dates('https://example.invalid/', None, None, strict=True)


def test_truncated_xml_is_not_silently_presented_as_complete(monkeypatch):
    xml = b'<ListBucketResult><IsTruncated>true</IsTruncated><Contents><Key>events/2025/01/01/abc123/a.json</Key></Contents></ListBucketResult>'
    monkeypatch.setattr(loader.request, 'urlopen', lambda *args, **kwargs: Response(xml))
    with pytest.raises(ValueError, match='Unable to list'):
        loader.list_usage_objects_for_dates('https://example.invalid/', None, None, strict=True)
