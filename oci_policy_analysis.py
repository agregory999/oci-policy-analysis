#!/usr/bin/env python3
##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at  https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application,  It does not supported by Oracle Support.
#
# oci_policy_analysis.py
#
# @author: Andrew Gregory
#
# Supports Python 3 and above
#
# coding: utf-8
##########################################################################

# Python
import argparse
import json
import logging
import datetime

# Local
from policy_statements import PolicyAnalysis
from dynamic_groups import DynamicGroupAnalysis

# Define Logger for module
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
logger = logging.getLogger('oci-policy-analysis')

########################################
# Main Code
# Pre-and Post-processing
########################################

if __name__ == "__main__":
    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
    parser.add_argument("-pr", "--profile", help="Config Profile, named. If not given, will use DEFAULT from ~/.oci/config", default="DEFAULT")
    parser.add_argument("-sf", "--subjectfilter", help="Filter all statement subjects by this text")
    parser.add_argument("-vf", "--verbfilter", help="Filter all verbs (inspect,read,use,manage) by this text")
    parser.add_argument("-rf", "--resourcefilter", help="Filter all resource (eg database or stream-family etc) subjects by this text")
    parser.add_argument("-lf", "--locationfilter", help="Filter all location (eg compartment name)")
    parser.add_argument("-hf", "--hierarchyfilter", help="Filter by compartment hierarchy (eg compartment in tree)")
    parser.add_argument("-cf", "--conditionfilter", help="Filter by Condition")
    parser.add_argument("-pf", "--policynamefilter", help="Filter by Policy Name")
    parser.add_argument("-tf", "--textfilter", help="Filter by Text (anything in policy statement)")
    parser.add_argument("-dgdf", "--dynamicgroupdomainfilter", help="Filter by Dynamic Group Domain Name")
    parser.add_argument("-dgnf", "--dynamicgroupnamefilter", help="Filter by Dynamic Group Name")
    parser.add_argument("-dgof", "--dynamicgroupocidfilter", help="Filter by Dynamic Group OCID (as part of rule)")
    parser.add_argument("-dgtf", "--dynamicgrouptypefilter", help="Filter by Dynamic Group Type (as part of rule)")
    parser.add_argument("-r", "--recurse", help="Recursion or not (default True)", action="store_true")
    parser.add_argument("-c", "--usecache", help="Load from local cache (if it exists)", action="store_true")
    parser.add_argument("-w", "--writejson", help="Write filtered output to JSON", action="store_true")
    parser.add_argument("-ip", "--instanceprincipal", help="Use Instance Principal Auth - negates --profile", action="store_true")
    parser.add_argument("-t", "--threads", help="Concurrent Threads (def=5)", type=int, default=1)
    args = parser.parse_args()
    verbose = args.verbose
    use_cache = args.usecache
    profile = args.profile
    threads = args.threads
    # Policy Filters
    sub_filter = args.subjectfilter
    verb_filter = args.verbfilter
    resource_filter = args.resourcefilter
    location_filter = args.locationfilter
    hierarchy_filter = args.hierarchyfilter
    condition_filter = args.conditionfilter
    policy_name_filter = args.policynamefilter
    text_filter = args.textfilter
    # DG Filters
    dg_domain_filter = args.dynamicgroupdomainfilter
    dg_name_filter = args.dynamicgroupnamefilter
    dg_ocid_filter = args.dynamicgroupocidfilter
    dg_type_filter = args.dynamicgrouptypefilter
    # Generic Args
    recursion = args.recurse
    write_json_output = args.writejson
    use_instance_principals = args.instanceprincipal

    # Update Logging Level
    if verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('oci._vendor.urllib3.connectionpool').setLevel(logging.INFO)

    logger.info(f'Using {"profile" + profile if not use_instance_principals else "instance principals"} with Logging level {"DEBUG" if verbose else "INFO"}')

    # Create the class
    policy_analysis = PolicyAnalysis(progress=None,
                                     verbose=verbose)

    # Instruct it to do stuff
    policy_analysis.initialize_client(profile=profile,
                                      use_instance_principal=use_instance_principals,
                                      use_cache=use_cache,
                                      use_recursion=recursion
                                      )
    # Load the policies
    policy_analysis.load_policies_from_client()

    # Apply Filters
    filtered_statements = policy_analysis.filter_policy_statements(subj_filter=sub_filter if sub_filter else "",
                                                                   verb_filter=verb_filter if verb_filter else "",
                                                                   resource_filter=resource_filter if resource_filter else "",
                                                                   location_filter=location_filter if location_filter else "",
                                                                   hierarchy_filter=hierarchy_filter if hierarchy_filter else "",
                                                                   condition_filter=condition_filter if condition_filter else "",
                                                                   text_filter=text_filter if text_filter else "",
                                                                   policy_filter=policy_name_filter if policy_name_filter else "")

    # Print Results
    json_pol = json.dumps(filtered_statements, indent=2)
    # logger.info(json_pol)

    # Initialize Dynamic Groups
    dynamic_group_analysis = DynamicGroupAnalysis(progress=None,
                                                  verbose=verbose)

    dynamic_group_analysis.initialize_client(profile=profile,
                                             use_instance_principal=use_instance_principals)
    # Load all Dynamic Groups
    dynamic_group_analysis.load_all_dynamic_groups(use_cache=use_cache)

    # Apply Filters
    dg_filtered_statements = dynamic_group_analysis.filter_dynamic_groups(name_filter=dg_name_filter if dg_name_filter else "",
                                                                          domain_filter=dg_domain_filter if dg_domain_filter else "",
                                                                          type_filter=dg_type_filter if dg_type_filter else "",
                                                                          ocid_filter=dg_ocid_filter if dg_ocid_filter else "")

    # Print Results
    json_dg = json.dumps(dynamic_group_analysis.dynamic_groups, indent=2)
    # logger.info(json_dg)

    # Print output
    json_object_pol = json.dumps(filtered_statements, indent=2)
    json_object_dg = json.dumps(dg_filtered_statements, indent=2)
    logger.info("==============Policy Statements (Filtered)=============")
    logger.info(json_object_pol)
    logger.info("==============Dynamic Groups (Filtered)=============")
    logger.info(json_object_dg)

    # To output file if required
    if write_json_output:
        # Build a slim-down
        new_json = []
        for st in filtered_statements:
            obj = {"policy-name": st[0], "policy-ocid": st[1], "policy-compartment": st[2], "policy-comp-hierarchy": st[3], "policy-statement": st[4]}
            new_json.append(obj)

        # Build the real JSON to save
        save_details = {"save-date": str(datetime.datetime.now()),
                        "subject-filter": sub_filter,
                        "verb-filter": verb_filter,
                        "resource-filter": resource_filter,
                        "location-filter": location_filter,
                        "hierarchy-filter": hierarchy_filter,
                        "condition-filter": condition_filter,
                        "text-filter": text_filter,
                        "policy-name-filter": policy_name_filter,
                        "filtered-policy-statements": new_json
                        }

        # Write output
        with open(f"policyoutput-{policy_analysis.tenancy_ocid}.json", "w") as outfile:
            outfile.write(json.dumps(save_details, indent=2))

        # DG - Build a slim-down
        new_json = []
        for dg in dg_filtered_statements:
            obj = {"dynamic-group-domain": dg[0], "dynamic-group-name": dg[1], "dynamic-group-ocid": dg[2], "dynamic-group-rules": dg[3]}
            new_json.append(obj)

        # Build the real JSON
        save_details = {"save-date": str(datetime.datetime.now()),
                        "domain-filter": None,
                        "name-filter": dg_name_filter,
                        "ocid-filter": None,
                        "type-filter": None,
                        "filtered-dynamic-groups": new_json
                        }
        # Write the file
        with open(f"dynamicgroupoutput-{policy_analysis.tenancy_ocid}.json", "w") as outfile:
            outfile.write(json.dumps(save_details, indent=2))

    logger.info(f"-----Complete: ({len(filtered_statements)} Policy Statements)---({len(dg_filtered_statements)} Dynamic Groups)---")
