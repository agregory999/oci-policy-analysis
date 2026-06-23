##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# cli.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import argparse
import csv
import json
import time
import warnings
from pathlib import Path

from oci_policy_analysis.application.core.engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.core.models.models import PolicySearch
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.core.support.helpers import (
    for_display_policy,
)
from oci_policy_analysis.application.core.support.logger import get_logger, set_log_level

# Suppress DeprecationWarnings from libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)


def _run_minimal_cli_intelligence(policy_analysis: PolicyAnalysisRepository, logger) -> None:
    """Run CLI-only post-load enrichment without recommendations overlays."""

    logger.warning('[CLI] Running minimal post-load enrichment')
    t0 = time.perf_counter()
    try:
        policy_intel = PolicyIntelligenceEngine(policy_analysis)
        policy_intel.calculate_all_effective_compartments()
        policy_intel.find_invalid_statements()
        policy_intel.run_dg_in_use_analysis()
    except Exception as exc:
        logger.warning('[CLI] Minimal post-load enrichment raised exception: %s', exc)
    t1 = time.perf_counter()
    logger.warning('[CLI] Minimal post-load enrichment completed in %.2fs', t1 - t0)


def _build_cli_permissions_report(policy_analysis: PolicyAnalysisRepository, logger) -> dict:
    """Build the permissions report for explicit CLI export requests."""

    logger.warning('[CLI] Building permissions report for export')
    t0 = time.perf_counter()
    engine = PolicyIntelligenceEngine(policy_analysis)
    report = engine.build_permissions_report()
    summary = report.get('summary', {}) if isinstance(report, dict) else {}
    logger.warning(
        '[CLI] Permissions report generated in %.2fs: direct_rows=%s effective_rows=%s paths=%s principals=%s',
        time.perf_counter() - t0,
        summary.get('direct_grant_row_count', 0),
        summary.get('effective_grant_row_count', len(report.get('grant_rows', []) if isinstance(report, dict) else [])),
        summary.get('path_count', 0),
        summary.get('principal_count', 0),
    )
    return report


def _log_cli_dataset_size(policy_analysis: PolicyAnalysisRepository, logger, *, label: str) -> None:
    """Log a concise dataset size summary visible at the default CLI log level."""

    logger.warning(
        '[CLI] %s: identity_domains=%d dynamic_groups=%d users=%d groups=%d compartments=%d policy_statements=%d cross_tenancy_statements=%d',
        label,
        len(getattr(policy_analysis, 'identity_domains', []) or []),
        len(getattr(policy_analysis, 'dynamic_groups', []) or []),
        len(getattr(policy_analysis, 'users', []) or []),
        len(getattr(policy_analysis, 'groups', []) or []),
        len(getattr(policy_analysis, 'compartments', []) or []),
        len(getattr(policy_analysis, 'regular_statements', []) or []),
        len(getattr(policy_analysis, 'cross_tenancy_statements', []) or []),
    )


def _permissions_report_paths(path_prefix: str, export_format: str) -> list[tuple[str, Path]]:
    """Return concrete output paths for a permissions report export request."""

    base = Path(path_prefix)
    suffix = base.suffix.lower()
    formats = ['json', 'csv'] if export_format == 'both' else [export_format]
    paths = []
    for fmt in formats:
        if suffix == f'.{fmt}' and len(formats) == 1:
            paths.append((fmt, base))
        elif suffix in {'.json', '.csv'}:
            paths.append((fmt, base.with_suffix(f'.{fmt}')))
        else:
            paths.append((fmt, Path(f'{base}.{fmt}')))
    return paths


def _export_permissions_report(report: dict, path_prefix: str, export_format: str, logger) -> None:
    """Write permissions report JSON and/or CSV files."""

    fieldnames = [
        'effective_path',
        'grant_path',
        'principal_key',
        'original_subject_key',
        'principal_kind',
        'action',
        'resource',
        'permission',
        'conditional',
        'inherited',
        'inherited_from',
        'policy_name',
        'statement_id',
        'statement_text',
    ]
    for fmt, path in _permissions_report_paths(path_prefix, export_format):
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == 'json':
            with path.open('w', encoding='utf-8') as file_object:
                json.dump(
                    {
                        'report': report.get('report', {}),
                        'grant_rows': report.get('grant_rows', []),
                        'summary': report.get('summary', {}),
                    },
                    file_object,
                    indent=2,
                    ensure_ascii=False,
                )
        else:
            with path.open('w', encoding='utf-8', newline='') as file_object:
                writer = csv.DictWriter(file_object, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for row in report.get('grant_rows', []) or []:
                    writer.writerow(row)
        logger.warning('[CLI] Wrote permissions report %s export to %s', fmt.upper(), path)


def main():  # noqa: C901
    """
    Entry point for the OCI Policy and Dynamic Group Viewer CLI.

    Parses command-line arguments to load, filter, display, or export OCI identity and policy information
    from Oracle Cloud Infrastructure (OCI) using cached or live data.

    Parameters
    ----------
    --verbose : bool
        Enable verbose logging.
    --log-level : str
        Set CLI log level (CRITICAL, ERROR, WARNING, INFO, or DEBUG).
    --app-log : bool
        Log output to app.log instead of console.
    --instance-principal : bool
        Use instance principal authentication.
    --get-caches : str
        List available caches for the given tenancy.
    --print-all : bool
        Print all policies and dynamic groups.
    --recursive : bool
        Recursively load policies across all compartments.
    --use-cache : str, optional
        Load data from a specified combined cache file.
    --dont-save-cache-after-load : bool
        Prevent saving a new combined cache after loading from OCI.
    --profile : str
        OCI CLI profile to use (default ``DEFAULT``).
    --filter-json : str, optional
        A JSON filter expression for policies.
    --export-json : str, optional
        Write collected data to a JSON file.
    --export-permissions-report : str, optional
        Write the calculated permissions report to a JSON/CSV path prefix.

    Usage Examples:
        To print all policies and dynamic groups using the ADMIN profile with verbose logging:

        ``python -m oci_policy_analysis.cli --verbose --profile ADMIN --print-all``

        To list available caches for a tenancy named "example-tenancy":

        ``python -m oci_policy_analysis.cli --get-caches example-tenancy``

        To load data from a specific cache and export to JSON:

        ``python -m oci_policy_analysis.cli --use-cache 2024-11-17T10-43-08+00-00``

        To filter policies with a JSON expression:

        ``python -m oci_policy_analysis.cli --filter-json '{"Subject": "group1", "Verb": "read"}'``

    Returns:
        None. Provides console output and/or writes files as specified.

    """
    cli_start_time = time.perf_counter()
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable DEBUG logging')
    parser.add_argument(
        '--log-level',
        choices=('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'),
        type=str.upper,
        default=None,
        help='Set CLI log level without enabling full verbose mode (for example: --log-level INFO)',
    )
    parser.add_argument('--app-log', action='store_true', help='Enable app.log for logging (default is console)')
    parser.add_argument('--instance-principal', action='store_true', help='Use instance principal authentication')
    parser.add_argument('--get-caches', help='If set, provide the names of tenancy to search for caches')
    parser.add_argument('--print-all', help='Print all of the policies and DGs to screen', action='store_true')
    parser.add_argument(
        '--recursive', help='Recursive Load across all compartments', action='store_true', default=False
    )
    parser.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    parser.add_argument(
        '--load-from-compliance',
        help='provide the directory containing compliance output CSVs',
        required=False,
        default=None,
    )
    parser.add_argument(
        '--dont-save-cache-after-load',
        help='Do not save the combined cache after loading from OCI',
        action='store_true',
    )
    parser.add_argument('--profile', default='DEFAULT', help='OCI CLI profile to use (default: DEFAULT)')
    parser.add_argument('--filter-json', help='JSON string with filter criteria', type=str, default=None)
    parser.add_argument(
        '--export-json',
        help='Export everything that is collected (Policies, Dynamic Groups, Users, Groups, Cross-tenancy Policies) to  provided JSON file',
    )
    parser.add_argument(
        '--export-permissions-report',
        help='Export the permissions report to the provided path prefix. Use --export-permissions-report-format to choose JSON, CSV, or both.',
    )
    parser.add_argument(
        '--export-permissions-report-format',
        choices=('json', 'csv', 'both'),
        default='both',
        help='Permissions report export format (default: both).',
    )
    args = parser.parse_args()

    effective_log_level = 'DEBUG' if args.verbose else args.log_level
    if effective_log_level:
        set_log_level(effective_log_level, announce=False)

    # Logging and Console setup
    if args.app_log:
        # Reconfigure logger to use console
        logger = get_logger(component='cli')
        logger.info('Logging to app.log')
    else:
        logger = get_logger(component='cli')
        logger.info('Logging to Console')

    if args.verbose:
        logger.debug('Verbose logging enabled')
    elif effective_log_level:
        logger.info('CLI log level set to %s', effective_log_level)

    # Initialize PolicyCompartmentAnalysis
    policy_analysis = PolicyAnalysisRepository()
    cache_manager = CacheManager()
    save_cache_after_cli_post_load = False

    # 1. Load from compliance CSVs if requested
    if args.load_from_compliance:
        logger.info(f'[CLI] Loading compliance output from directory: {args.load_from_compliance}')
        result = policy_analysis.load_from_compliance_output_dir(args.load_from_compliance)
        logger.info(f'[CLI] Compliance output load success: {result}')
        logger.info(
            f'[CLI] Entities loaded: {len(policy_analysis.identity_domains)} identity_domains, '
            f'{len(policy_analysis.dynamic_groups)} dynamic_groups, {len(policy_analysis.users)} users, '
            f'{len(policy_analysis.groups)} groups, {len(policy_analysis.compartments)} compartments, '
            f'{len(policy_analysis.regular_statements)} policy statements'
        )
        _log_cli_dataset_size(policy_analysis, logger, label='Loaded compliance dataset')

        _run_minimal_cli_intelligence(policy_analysis, logger)

    else:
        # Just show caches and quit
        if args.get_caches:  # If get_caches is provided, list available caches
            available_caches = cache_manager.get_available_cache(tenancy_name=args.get_caches)
            if available_caches:
                logger.warning('Available caches:')
                for cache in available_caches:
                    logger.warning(cache)
            else:
                logger.warning('No caches available.')
            logger.warning('Exiting after listing caches as --get-caches was provided')
            exit(0)

        # Load everything from named cache
        if args.use_cache:
            if not cache_manager.load_combined_cache(named_cache=args.use_cache, policy_analysis=policy_analysis):
                logger.error('Failed to load combined cache')
                exit(2)
            _log_cli_dataset_size(policy_analysis, logger, label=f'Loaded cache {args.use_cache}')
        else:
            if not policy_analysis.initialize_client(
                use_instance_principal=args.instance_principal,
                profile=args.profile,
                recursive=True if args.recursive else False,
            ):
                logger.error('Failed to initialize PolicyCompartmentAnalysis client')
                exit(2)
            logger.info(f'Initialized PolicyCompartmentAnalysis client for tenancy: {policy_analysis.tenancy_name}')
            if not policy_analysis.load_complete_identity_domains():
                logger.error('Failed to load identity domains, groups, and users from OCI')
                exit(2)
            if not policy_analysis.load_policies_and_compartments():
                logger.error('Failed to load policies and compartments from OCI')
                exit(2)
            # Completed the Load
            logger.info(f'Loaded policies and compartments for tenancy: {policy_analysis.tenancy_name}')
            _log_cli_dataset_size(policy_analysis, logger, label='Loaded OCI tenancy dataset')

            save_cache_after_cli_post_load = not args.dont_save_cache_after_load

        _run_minimal_cli_intelligence(policy_analysis, logger)

        if save_cache_after_cli_post_load:
            logger.info('Saving combined cache after loading from OCI and post-load enrichment')
            cache_manager.save_combined_cache(policy_analysis=policy_analysis)

    # Print some basic details
    logger.info('-' * 80)
    logger.info(f'Tenancy Name: {policy_analysis.tenancy_name}')
    logger.info(f'Tenancy OCID: {policy_analysis.tenancy_ocid}')
    logger.info(f'Data As Of: {policy_analysis.data_as_of}')
    logger.info('-' * 80)

    # Apply JSON filter if provided
    if args.filter_json:
        filter: PolicySearch = eval(args.filter_json)
        logger.info(f'Applying filter: {filter}')
        # filtered_statements = policy_analysis.filter_policy_statements_json(filters=filter)
        filtered_statements = policy_analysis.filter_policy_statements(filters=filter)
        logger.info(f'Filtered down to {len(filtered_statements)} policy statements:')
        for i, stmt in enumerate(filtered_statements, start=1):
            stmt = for_display_policy(stmt)
            logger.info(f'{i} Policy Name: {stmt.get("Policy Name")} | Statement: {stmt.get("Statement Text")}')
        logger.info('-' * 80)

    # Export JSON if needed
    if args.export_json:
        logger.info(f'The file is called {args.export_json}')
        # Save to provided file
        with open(args.export_json, 'w', encoding='utf-8') as file_object:
            cache_file_name = cache_manager.save_combined_cache(
                export_file=file_object, policy_analysis=policy_analysis
            )
        logger.info(f'Wrote combined cache to {cache_file_name}')
        logger.info('-' * 80)

    if args.export_permissions_report:
        permissions_report = _build_cli_permissions_report(policy_analysis, logger)
        _export_permissions_report(
            permissions_report,
            args.export_permissions_report,
            args.export_permissions_report_format,
            logger,
        )
        logger.info('-' * 80)

    if args.print_all:
        # Print regular policies
        logger.info('\nRegular Policies:')
        # Use helper to print nicely
        for stmt in policy_analysis.regular_statements:
            stmt = for_display_policy(stmt)
            logger.info(f'Policy Name: {stmt.get("Policy Name")}')
            logger.info(f'Statement: {stmt.get("Statement Text")}')
            logger.info(f'Compartment Hierarchy: {stmt.get("Policy Compartment")}')
            if stmt.get('parsed'):
                logger.info(f'Subject Type: {stmt.get("Subject Type")}')
                logger.info(f'Subject: {stmt.get("Subject")}')
                logger.info(f'Verb: {stmt.get("Verb")}')
                logger.info(f'Resource: {stmt.get("Resource")}')
                logger.info(f'Permission: {stmt.get("Permission")}')
                logger.info(f'Location Type: {stmt.get("Location Type")}')
                logger.info(f'Location: {stmt.get("Location")}')
                logger.info(f'Condition: {stmt.get("Condition")}')
                logger.info(f'Comment: {stmt.get("Comment")}')
                logger.info(f'Created: {stmt.get("Creation Time")}')
            else:
                logger.info('Statement could not be parsed into components')
            logger.info('-' * 80)

        # Print cross-tenancy policies
        logger.info('\nCross-Tenancy Policies:')
        logger.info('-' * 80)
        for stmt in policy_analysis.cross_tenancy_statements:
            stmt = for_display_policy(stmt)
            logger.info(f'Policy Name: {stmt.get("Policy Name")}')
            logger.info(f'Statement: {stmt.get("Statement Text")}')
            logger.info(f'Compartment Hierarchy: {stmt.get("Policy Compartment")}')
            logger.info('-' * 80)

        # Print dynamic groups
        logger.info('\nDynamic Groups:')
        logger.info('-' * 80)
        for dg in policy_analysis.dynamic_groups:
            # for_display_dynamic_group expects a class or TypedDict, but compliance loads produce plain dicts
            # Defensive: pass only keys that exist in both
            safe_keys = [
                'domain_name',
                'dynamic_group_name',
                'description',
                'matching_rule',
                'in_use',
                'dynamic_group_ocid',
                'creation_time',
            ]
            dg_struct = {k: dg.get(k) for k in safe_keys}
            logger.info(f'Domain: {dg_struct.get("domain_name")}')
            logger.info(f'Dynamic Group Name: {dg_struct.get("dynamic_group_name")}')
            logger.info(f'Description: {dg_struct.get("description")}')
            logger.info(f'Matching Rule: {dg_struct.get("matching_rule")}')
            logger.info(f'In Use: {dg_struct.get("in_use")}')
            logger.info(f'OCID: {dg_struct.get("dynamic_group_ocid")}')
            logger.info(f'Created: {dg_struct.get("creation_time")}')
            logger.info('-' * 80)
        # Print summary counts

    # Summary
    logger.info('-' * 80)
    logger.info(f'Total Regular Policies: {len(policy_analysis.regular_statements)}')
    logger.info(f'Total Cross-Tenancy Policies: {len(policy_analysis.cross_tenancy_statements)}')
    logger.info(f'Total Dynamic Groups: {len(policy_analysis.dynamic_groups)}')
    logger.info(f'Total Identity Domains: {len(policy_analysis.identity_domains)}')
    logger.info(f'Total Groups: {len(policy_analysis.groups)}')
    logger.info(f'Total Users: {len(policy_analysis.users)}')
    logger.warning('[CLI] Completed in %.2fs', time.perf_counter() - cli_start_time)


if __name__ == '__main__':
    main()
