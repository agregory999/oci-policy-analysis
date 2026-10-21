"""Attach verified native archives and onefile executables to an existing release."""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def select_release(releases: list[dict], tag: str) -> dict:
    """Prefer a published tag match over duplicate drafts.

    Args:
        releases: GitHub release records, in any order.
        tag: Exact semantic-release tag; unrelated releases are never selected.

    Returns:
        dict: Published match, or the newest matching draft.

    Raises:
        ValueError: No existing release matches the tag.
    """
    matches = [item for item in releases if item.get('tag_name') == tag]
    published = [item for item in matches if not item.get('draft', True)]
    if not matches:
        raise ValueError(f'Semantic-release did not create {tag}')
    return max(published or matches, key=lambda item: item['id'])


class GitHubReleases:
    """Use authenticated GitHub release APIs without creating duplicate records.

    Args:
        repository: Validated GitHub owner/repository identifier.
        token: Explicit workflow token; never written to output or files.
    """

    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
            raise ValueError('Expected a GitHub owner/repository')
        if not token:
            raise ValueError('GH_TOKEN or GITHUB_TOKEN is required')
        self.repository, self.token = repository, token

    def request(self, method: str, path: str, data: bytes | None = None, *, upload: bool = False):
        """Send one release API request with retries for transient failures.

        Args:
            method: HTTP verb.
            path: Repository-relative release endpoint.
            data: Serialized JSON or archive bytes.
            upload: Select GitHub's fixed upload host and binary content type.

        Returns:
            object: Decoded GitHub JSON response.
        """
        host = 'uploads.github.com' if upload else 'api.github.com'
        request = Request(
            f'https://{host}/repos/{self.repository}/{path}',
            data=data,
            method=method,
            headers={
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'Content-Type': 'application/octet-stream' if upload else 'application/json',
            },
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=300) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                time.sleep(2**attempt)

    def list_releases(self) -> list[dict]:
        """Read all release pages so old matching drafts remain discoverable.

        Returns:
            list[dict]: Release metadata including exact tag names and asset IDs.
        """
        releases = []
        page = 1
        while True:
            batch = self.request('GET', f'releases?per_page=100&page={page}')
            releases.extend(batch)
            if len(batch) < 100:
                return releases
            page += 1


def publish(client, *, tag: str, archives: list[Path], prerelease: bool) -> int:
    """Upload by release ID, then finalize that same record idempotently.

    Args:
        client: GitHubReleases-compatible API client.
        tag: Existing semantic-release tag.
        archives: Verified installer/application archives.
        prerelease: Whether the selected release is a prerelease.

    Returns:
        int: Selected GitHub release ID.
    """
    if not archives:
        raise ValueError('No native archives were collected')
    release = select_release(client.list_releases(), tag)
    release_id = release['id']
    existing = {asset['name'] for asset in release.get('assets', [])}
    for path in archives:
        if path.name in existing:
            print(f'Already attached: {path.name}', flush=True)
            continue
        client.request(
            'POST', f'releases/{release_id}/assets?name={quote(path.name, safe="")}', path.read_bytes(), upload=True
        )
        existing.add(path.name)
        print(f'Attached: {path.name}', flush=True)
    client.request('PATCH', f'releases/{release_id}', json.dumps({'draft': False, 'prerelease': prerelease}).encode())
    print(f'Published {tag} using release ID {release_id}', flush=True)
    return release_id


def main(argv: list[str] | None = None) -> int:
    """Publish only native artifacts from a successful workflow run.

    Args:
        argv: Optional command arguments; defaults to process arguments.

    Returns:
        int: Zero after all native archives attach and the release finalizes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    parser.add_argument('--tag', required=True)
    parser.add_argument('--artifacts-dir', type=Path, default=Path('dist'))
    parser.add_argument('--prerelease', choices=('true', 'false'), required=True)
    args = parser.parse_args(argv)
    archives = sorted(
        path
        for path in args.artifacts_dir.rglob('oci-policy-analysis-*')
        if path.is_file()
        and (
            path.name.endswith('.zip')
            or path.name.endswith('.tar.gz')
            or path.name == 'oci-policy-analysis-qt-onefile.exe'
        )
    )
    client = GitHubReleases(args.repository, os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or '')
    publish(client, tag=args.tag, archives=archives, prerelease=args.prerelease == 'true')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
