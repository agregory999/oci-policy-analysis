"""Generate explicit OCI Logging Search CLI searches without connecting to OCI."""

import re
import shlex
from datetime import UTC, datetime, timedelta


class AuditCommandService:
    """Build compartment-scoped commands split into contiguous fourteen-day windows.

    Commands are suggestions for an operator to run. Snapshot differences alone
    do not establish who made a change or whether an Audit event is available.
    """

    DOCUMENTATION = (
        'https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/logging-search/search-logs.html'
    )
    NOTE = (
        'Commands only; nothing is executed. Search Audit logs through OCI Logging Search. '
        'Use the policy/resource compartment and the appropriate region (often the home region for IAM). '
        'Read access to audit-events is required. Resource OCIDs are filtered on the server. '
        'Policy searches show only CreatePolicy, UpdatePolicy and DeletePolicy attempts; check status for success. '
        'Each command returns at most 100 results, newest first, not a complete history. '
        'Narrow the time range or use --page with the response opc-next-page token for more results '
        '(remove --query and use --output json to see response metadata). '
        'The table shows formatted time with timezone, operation, actor name/OCID, IP and status. '
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
            'instance_principal': False,
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
                start_time/end_time with timezone, shell, and instance_principal.

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
        instance_principal = inputs.get('instance_principal', False)
        if isinstance(instance_principal, str):
            instance_principal = instance_principal.strip().lower() in {'1', 'true', 'yes', 'on'}
        else:
            instance_principal = bool(instance_principal)
        start, end = (cls._time(inputs.get(key) or '') for key in ('start_time', 'end_time'))
        if end <= start or end - start > timedelta(days=366):
            raise ValueError('Choose an increasing date range of at most 366 days.')
        start = start.replace(second=0, microsecond=0)
        if end.second or end.microsecond:
            end = end.replace(second=0, microsecond=0) + timedelta(minutes=1)
        search = f'search "{compartment}/_Audit"'
        if resource:
            search += f" | where data.resourceId = '{resource}'"
        if not resource or resource.startswith('ocid1.policy.'):
            search += (
                " | where (data.eventName = 'CreatePolicy' or data.eventName = 'UpdatePolicy'"
                " or data.eventName = 'DeletePolicy')"
            )
        search += (
            ' | sort by datetime desc'
            " | select time_format(datetime, 'yyyy-MM-dd HH:mm:ss z') as event_time,"
            ' data.eventName as operation, data.identity.principalId as actor_ocid,'
            ' data.identity.principalName as actor, data.identity.ipAddress as ip,'
            ' data.response.status as status'
        )
        commands, windows = [], []
        while start < end:
            stop = min(start + timedelta(days=14), end)
            first, last = (value.strftime('%Y-%m-%dT%H:%M:00Z') for value in (start, stop))
            args = ['oci', 'logging-search', 'search-logs']
            if instance_principal:
                args.extend(['--auth', 'instance_principal'])
            for flag, field in [('--region', 'region'), ('--profile', 'profile')]:
                value = str(inputs.get(field) or '').strip()
                if any(ord(char) < 32 for char in value):
                    raise ValueError('Profile and region cannot contain control characters.')
                if value:
                    args.extend([flag, value])
            if shell == 'posix':
                args.extend(
                    [
                        '--search-query',
                        search,
                        '--time-start',
                        first,
                        '--time-end',
                        last,
                        '--is-return-field-info',
                        'false',
                        '--limit',
                        '100',
                        '--output',
                        'table',
                        '--query',
                        'data.results[].data',
                    ]
                )
                commands.append(' '.join(shlex.quote(arg) for arg in args))
            else:
                commands.append(
                    cls._powershell_command(
                        search,
                        first,
                        last,
                        args[3:],
                    )
                )
            windows.append({'start_time': first, 'end_time': last})
            start = stop
        return {
            'commands': commands,
            'windows': windows,
            'limit': 100,
            'note': cls.NOTE,
            'documentation': cls.DOCUMENTATION,
        }

    @staticmethod
    def _powershell_quote(value: str) -> str:
        """Return a safely single-quoted PowerShell string literal."""
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _powershell_command(cls, search: str, start: str, end: str, cli_options: list[str]) -> str:
        """Build the JSON-file invocation used by OCI CLI PowerShell examples."""
        request_lines = [
            '    searchQuery       = $searchQuery',
            f'    timeStart         = {cls._powershell_quote(start)}',
            f'    timeEnd           = {cls._powershell_quote(end)}',
            '    isReturnFieldInfo = $false',
            '    limit             = 100',
        ]
        command_options = [
            '--from-json',
            '"file://$jsonPath"',
            '--output',
            'table',
            '--query',
            "'data.results[].data'",
        ]
        for index in range(0, len(cli_options), 2):
            flag, value = cli_options[index : index + 2]
            if flag == '--region':
                command_options.extend([flag, cls._powershell_quote(value)])
            elif flag == '--profile':
                command_options.extend([flag, cls._powershell_quote(value)])
            elif flag == '--auth':
                command_options.extend([flag, value])
        command = 'oci logging-search search-logs ' + ' '.join(command_options)
        return '\n'.join(
            [
                "$searchQuery = @'",
                search,
                "'@",
                '',
                '$request = @{',
                *request_lines,
                '}',
                '',
                "$jsonPath = Join-Path $env:TEMP 'oci-log-search.json'",
                '$utf8 = New-Object System.Text.UTF8Encoding($false)',
                '[System.IO.File]::WriteAllText(',
                '    $jsonPath,',
                '    ($request | ConvertTo-Json -Depth 5),',
                '    $utf8',
                ')',
                '',
                command,
            ]
        )
