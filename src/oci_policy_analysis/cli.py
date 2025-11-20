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
import warnings

from oci_policy_analysis.common.helpers import (
    for_display_dynamic_group,
    for_display_policy,
)
from oci_policy_analysis.common.logger import get_logger, set_log_level
from oci_policy_analysis.common.models import PolicySearch
from oci_policy_analysis.logic.caching import CacheManager
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

# Suppress DeprecationWarnings from libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)


def main():  # noqa: C901
    """Main function to parse arguments and print policies and dynamic groups."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--app-log', action='store_true', help='Enable app.log for logging (default is console)')
    parser.add_argument('--instance-principal', action='store_true', help='Use instance principal authentication')
    parser.add_argument('--get-caches', help='If set, provide the names of tenancy to search for caches')
    parser.add_argument('--print-all', help='Print all of the policies and DGs to screen', action='store_true')
    parser.add_argument(
        '--recursive', help='Recursive Load across all compartments', action='store_true', default=False
    )
    parser.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    parser.add_argument(
        '--dont-save-cache-after-load', help='Save the combined cache after loading from OCI', action='store_true'
    )
    parser.add_argument('--profile', default='DEFAULT', help='OCI CLI profile to use (default: DEFAULT)')
    parser.add_argument('--filter-json', help='JSON string with filter criteria', type=str, default=None)
    parser.add_argument(
        '--export-json',
        help='Export everything that is collected (Policies, Dynamic Groups, Users, Groups, Cross-tenancy Policies) to  provided JSON file',
    )
    args = parser.parse_args()

    # Logging and Console setup
    if args.app_log:
        # Reconfigure logger to use console
        logger = get_logger(component='cli')
        logger.info('Logging to app.log')
    else:
        logger = get_logger(component='cli')
        logger.info('Logging to Console')

    # Configure logging based on verbose flag
    if args.verbose:
        set_log_level('DEBUG')
        # logger.setLevel('DEBUG')
        logger.debug('Verbose logging enabled')

    # Initialize PolicyCompartmentAnalysis
    policy_analysis = PolicyAnalysisRepository()

    # CacheManager Initializartio
    cache_manager = CacheManager(policy_analysis=policy_analysis)

    # Just show caches and quit
    if args.get_caches:  # If get_caches is provided, list available caches
        available_caches = cache_manager.get_available_cache(tenancy_name=args.get_caches)
        if available_caches:
            logger.info('Available caches:')
            for cache in available_caches:
                logger.info(cache)
        else:
            logger.info('No caches available.')
        logger.info('Exiting after listing caches as --get-caches was provided')
        exit(0)

    # Load everything from named cache
    if args.use_cache:
        if not cache_manager.load_combined_cache(named_cache=args.use_cache):
            logger.error('Failed to load combined cache')
            exit(2)
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

        if not args.dont_save_cache_after_load:
            # Save combined cache after loading from OCI
            logger.info('Saving combined cache after loading from OCI')
            cache_manager.save_combined_cache()

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
            logger.info(f'{i} Policy Name: {stmt.get("Policy Name")} | Statement: {stmt.get("Statement Text")}')
        logger.info('-' * 80)

    # Export JSON if needed
    if args.export_json:
        logger.info(f'The file is called {args.export_json}')
        # Save to provided file
        file_object = open(args.export_json, 'w')
        cache_file_name = cache_manager.save_combined_cache(export_file=file_object)
        logger.info(f'Wrote combined cache to {cache_file_name}')
        logger.info('-' * 80)

    elif args.print_all:
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
            dg = for_display_dynamic_group(dg)
            logger.info(f'Domain: {dg.get("Domain")}')
            logger.info(f'Dynamic Group Name: {dg.get("DG Name")}')
            logger.info(f'Description: {dg.get("Description")}')
            logger.info(f'Name: {dg.get("DG Name")}')
            logger.info(f'Matching Rule: {dg.get("Matching Rule")}')
            logger.info(f'In Use: {dg.get("In Use")}')
            logger.info(f'OCID: {dg.get("DG OCID")}')
            logger.info(f'Created: {dg.get("Creation Time")}')
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


if __name__ == '__main__':
    main()
