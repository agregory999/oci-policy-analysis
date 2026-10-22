"""Generate explicit OCI Audit CLI searches without connecting to OCI."""

import json
import re
import shlex
from datetime import UTC, datetime, timedelta


class AuditCommandService:
    """Build compartment-scoped commands split into contiguous fourteen-day windows.

    Commands are suggestions for an operator to run. Snapshot differences alone
    do not establish who made a change or whether an Audit event is available.
    """

    DOCUMENTATION = 'https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/audit/event/list.html'
    NOTE = (
        'Commands only; nothing is executed. Audit is regional and compartment-scoped, not recursive. '
        'Select the compartment where the event occurred and the appropriate region (often the home region for IAM). '
        'Read access to audit-events is required. Commands return one page per time window by default. '
        'The optional resource OCID filter is applied locally after events are fetched, not by the Audit service; '
        'narrow the time range and compartment first. Fetching all pages can be slow. '
        'A resource filter may omit events with different or missing resource IDs; clear it to broaden the search. '
        'Snapshot differences are not confirmed OCI changes. '
        'Identity-domain activity may require the IAM domain audit report.'
    )

    @staticmethod
    def defaults(change: dict, metadata: dict | None = None) -> dict:
        """Suggest editable search inputs from original change evidence.

        Args:
            change: Historical item containing old_value and new_value.
            metadata: Comparison metadata, independent of the active tenancy.

        Returns:
            dict: Compartment/resource IDs and UTC bounds. Missing dates fall
            back to the last fourteen days; no active profile is inferred.
        """
        metadata = metadata or {}
        audit = metadata.get('audit_context') or {}
        records = [change.get('new_value') or {}, change.get('old_value') or {}]
        resource = next(
            (
                str(row[key])
                for row in records
                for key in ('policy_ocid', 'group_ocid', 'dynamic_group_ocid', 'user_ocid', 'id', 'ocid')
                if row.get(key) and str(row[key]).startswith('ocid1.')
            ),
            '',
        )
        compartment = next(
            (
                str(row[key])
                for row in records
                for key in ('compartment_ocid', 'compartment_id', 'parent_id')
                if row.get(key)
            ),
            str(audit.get('compartment_id') or ''),
        )
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        try:
            start, end = (AuditCommandService._time(audit.get(key) or '') for key in ('start_time', 'end_time'))
            if start > end:
                start, end = end, start
            if start == end:
                raise ValueError('Identical capture times')
        except (ValueError, TypeError):
            start, end = now - timedelta(days=14), now
        return {
            'compartment_id': compartment,
            'resource_id': resource,
            'start_time': start.isoformat(),
            'end_time': end.isoformat(),
            'region': '',
            'profile': '',
            'shell': 'posix',
        }

    @staticmethod
    def _time(value):
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('Use an ISO timestamp with timezone, for example 2026-10-01T00:00:00Z.') from exc
        if result.tzinfo is None:
            raise ValueError('Date/time values must include a timezone (Z or an offset).')
        return result.astimezone(UTC)

    @classmethod
    def generate(cls, inputs: dict) -> dict:
        """Validate inputs and return quoted CLI commands; perform no I/O.

        Args:
            inputs: compartment_id, optional resource_id/region/profile,
                start_time/end_time with timezone, posix or powershell shell,
                and optional fetch_all to retrieve every result page.

        Returns:
            dict: Commands, normalized minute boundaries, warning and reference.

        Raises:
            ValueError: Invalid IDs, times, shell or an excessive date range.
        """
        compartment = str(inputs.get('compartment_id') or '').strip()
        resource = str(inputs.get('resource_id') or '').strip()
        for name, value in [('Compartment', compartment), ('Resource', resource)]:
            if (name == 'Compartment' or value) and not re.fullmatch(r'ocid1\.[A-Za-z0-9._-]+', value):
                raise ValueError(f'{name} must be an OCID; choose a real compartment/resource from OCI.')
        shell = inputs.get('shell', 'posix')
        if shell not in {'posix', 'powershell'}:
            raise ValueError('Choose POSIX shell or PowerShell.')
        start, end = (cls._time(inputs.get(key) or '') for key in ('start_time', 'end_time'))
        if end <= start or end - start > timedelta(days=366):
            raise ValueError('Choose an increasing date range of at most 366 days.')
        start = start.replace(second=0, microsecond=0)
        if end.second or end.microsecond:
            end = end.replace(second=0, microsecond=0) + timedelta(minutes=1)
        quote = shlex.quote if shell == 'posix' else lambda value: "'" + value.replace("'", "''") + "'"
        fetch_all_value = inputs.get('fetch_all', False)
        if fetch_all_value in (True, 1, 'true', 'on', '1'):
            fetch_all = True
        elif fetch_all_value in (False, 0, None, '', 'false', 'off', '0'):
            fetch_all = False
        else:
            raise ValueError('Choose whether to fetch every Audit result page.')
        commands, windows = [], []
        while start < end:
            stop = min(start + timedelta(days=14), end)
            first, last = (value.strftime('%Y-%m-%dT%H:%M:00Z') for value in (start, stop))
            args = [
                'oci',
                'audit',
                'event',
                'list',
                '--compartment-id',
                compartment,
                '--start-time',
                first,
                '--end-time',
                last,
            ]
            if fetch_all:
                args.append('--all')
            for flag, field in [('--region', 'region'), ('--profile', 'profile')]:
                value = str(inputs.get(field) or '').strip()
                if any(ord(char) < 32 for char in value):
                    raise ValueError('Profile and region cannot contain control characters.')
                if value:
                    args.extend([flag, value])
            rows = f'data[?data."resource-id" == `{json.dumps(resource)}`]' if resource else 'data[]'
            projection = (
                '{time:"event-time",eventType:"event-type",operation:data."event-name",'
                'resourceName:data."resource-name",resourceId:data."resource-id",'
                'principal:data.identity."principal-name",caller:data.identity."caller-name",'
                'ipAddress:data.identity."ip-address",action:data.request.action,path:data.request.path,'
                'status:data.response.status,message:data.response.message,'
                'previous:data."state-change".previous,current:data."state-change".current}'
            )
            args.extend(['--output', 'json', '--query', f'{rows}.{projection}'])
            commands.append(' '.join(quote(arg) for arg in args))
            windows.append({'start_time': first, 'end_time': last})
            start = stop
        return {
            'commands': commands,
            'windows': windows,
            'fetch_all': fetch_all,
            'note': cls.NOTE,
            'documentation': cls.DOCUMENTATION,
        }
