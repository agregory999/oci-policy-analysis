#!/usr/bin/env python3
##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# oci_policy_dg_viewer.py
#
# @author: Andrew Gregory (original), enhanced by Grok
#
# Supports Python 3.13 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import argparse
import csv
import datetime
import json
import logging
import re
import sys
import time
from typing import List, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread

# Third-party imports
import oci

from oci import config, pagination
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.identity import IdentityClient
from oci.identity.models import Compartment, Domain
from oci.identity_domains import IdentityDomainsClient

# Constants
THREADS = 8
POLICY_REGEX = r'^\s*?(allow|endorse)\s+(?P<subjecttype>service|any-user|any-group|dynamic-group|group|resource)\s*(?P<subject>([\w\/\'\.\\, +-]|,)+?)?\s+(to\s+)?((?P<verb>read|inspect|use|manage)\s+(?P<resource>[\w-]+)|(?P<perm>{[\s*\w\s*|\s*\w\s*,\s*]+}))\s+in\s+(?P<locationtype>any-tenancy|tenancy|compartment\s+id|compartment)\s*(?P<location>[\w\':.-]+)?(?:\s+where\s+(?P<condition>.+))?(?:(?P<optional>\s*\/\/.+))?$'
OCID_REGEX = r"ocid1\.\w+\.\w+\.\w*\.\w+"
CROSS_TENANCY_REGEX = r'^\s*?(?P<action>endorse|admit|define)\s+(?:(?P<subjecttype>service|any-user|any-group|dynamic-group|group|resource)\s*(?P<subject>(?:[\w\/\'\.\\,+-]+(?:\s*,\s*[\w\/\'\.\\,+-]+)*)?)?(?:\s+of\s+(?P<sourcetype>tenancy)\s*(?P<source>[\w\':.-]+)?)?\s+)?(?:(?:to\s+(?P<verb>[\w-]+|\{[\s*\w\s*|\s*\w\s*,\s*]+\})\s+(?P<resource>[\w-]+|all-resources)?)?|(?:(?P<definetype>tenancy|compartment|dynamic-group)\s+(?P<alias>[\w-]+)\s+as\s+(?P<ocid>ocid1\.\w+\.\w+\.\w*\.\w+)))?\s*(?:(?:in)\s+(?P<locationtype>tenancy|any-tenancy|compartment\s+id|compartment)(?:\s+(?P<location>[\w\':.-]+)(?:\s+of\s+(?P<targettenancytype>tenancy)\s*(?P<targettenancy>[\w\':.-]+)?)?)?)?(?:\s+with\s+(?P<withresource>[\w-]+)\s+in\s+(?P<withlocationtype>tenancy|compartment)\s*(?P<withlocation>[\w\':.-]+)?)?(?:\s+where\s+(?P<condition>.+?))?(?:(?P<optional>\s*\/\/.+))?$'


# Global variables
last_error = ""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s'
)
logger = logging.getLogger('oci-policy-dg-viewer')

class PolicyCompartmentAnalysis:
    def __init__(self, verbose: bool):
        self.logger = logging.getLogger('oci-policy-compartment-analysis')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        self.compartments = []  # List of dicts: {id, name, parent_id, hierarchy_path, hierarchy_ocids}
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = {}  # Store define statements: {alias: (definetype, ocid)}

        self.data_as_of = ""
        self.tenancy_ocid = None
        self.identity_client = None
        self.logger.info("Initialized PolicyCompartmentAnalysis")

    def initialize_client(self, use_instance_principal: bool, profile: str = "DEFAULT") -> bool:
        try:
            if use_instance_principal:
                self.logger.debug("Using Instance Principal Authentication")
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            else:
                self.logger.debug(f"Using Profile Authentication: {profile}")
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.tenancy_ocid = self.config["tenancy"]
            self.logger.info(f"Set up Identity Client for tenancy: {self.tenancy_ocid}")
            return True
        except (ConfigFileNotFound, Exception) as exc:
            self.logger.fatal(f"Authentication failed: {exc}")
            return False

    def get_compartment_path(self, compartment: Compartment, level: int, comp_string: str) -> tuple[str, list[str]]:
        hierarchy_ocids = [compartment.id]
        self.logger.debug(f"Processing compartment {compartment.name} (OCID: {compartment.id}) at level {level}")
        if not compartment.compartment_id:
            self.logger.debug(f"Reached root compartment: {compartment.name} (OCID: {compartment.id})")
            return f"ROOT{comp_string}", hierarchy_ocids # type: ignore
        try:
            parent_response = self.identity_client.get_compartment(compartment_id=compartment.compartment_id)
            if parent_response.data is None:
                self.logger.warning(f"Failed to get parent compartment for {compartment.id}")
                return comp_string, hierarchy_ocids # type: ignore
            parent_path, parent_ocids = self.get_compartment_path(parent_response.data, level + 1, f"/{compartment.name}{comp_string}")
            hierarchy_ocids.extend(parent_ocids)
            self.logger.debug(f"Compartment {compartment.name} path: {parent_path}, OCIDs: {hierarchy_ocids}")
            return parent_path, hierarchy_ocids
        except Exception as e:
            self.logger.error(f"Error getting parent compartment for {compartment.id}: {e}")
            return comp_string, hierarchy_ocids

    def check_invalid_location(self, compartment_ocid) -> bool:
        # Given a compartment OCID-based location, return False if there is no compartment (any more)
        try:
            comp:Compartment = self.identity_client.get_compartment(compartment_id=compartment_ocid).data
            if comp.lifecycle_state == Compartment.LIFECYCLE_STATE_ACTIVE:
                return True
            else:
                self.logger.warning(f"Found Compartment but not ACTIVE: {compartment_ocid} was: {comp.lifecycle_state}")
                return False

        except Exception as e:
            # Any error means it is invalid
            self.logger.warning(f"Compartment OCID {compartment_ocid} not valid: {e}")
            return False
        return True

    def parse_subjects(self, subject_string) -> List[Tuple[str, str]]:
        """Parse a comma-separated string of subjects and return list of (domain, name) tuples"""
        # Split by comma and strip whitespace
        subject_parts = [part.strip() for part in subject_string.split(',')]
        results: List[Tuple[str, str]] = []
        
        for part in subject_parts:
            if not part:  # Skip empty parts
                continue
            
            self.logger.debug(f"  DEBUG: Processing part: '{part}'")
            
            # Check if it contains a separator (/ or \)
            if '/' in part or '\\' in part:
                # Split on the separator
                if '/' in part:
                    separator_parts = part.split('/', 1)  # Split only on first occurrence
                else:
                    separator_parts = part.split('\\', 1)  # Split only on first occurrence
                
                if len(separator_parts) == 2:
                    domain_part = separator_parts[0].strip()
                    name_part = separator_parts[1].strip()
                    
                    # Remove quotes from domain and name
                    domain = domain_part.strip('\'"')
                    name = name_part.strip('\'"')
                    
                    self.logger.debug(f"  DEBUG: Found separator - domain: '{domain}', name: '{name}'")
                    results.append((domain, name))
                else:
                    # Shouldn't happen, but fallback
                    clean_name = part.strip('\'"')
                    self.logger.debug(f"  DEBUG: Separator found but couldn't split properly - using as simple name: '{clean_name}'")
                    results.append(("Default", clean_name))
            else:
                # No separator, it's just a name
                clean_name = part.strip('\'"')
                self.logger.debug(f"  DEBUG: No separator - simple name: '{clean_name}'")
                results.append(("Default", clean_name))
        
        return results

    def parse_statement(self, statement: str, comp_id: str, policy: oci.identity.models.Policy) -> bool:
        comp = self.get_compartment_by_id(comp_id)
        comp_string = comp["hierarchy_path"] if comp else "ROOT"

        # Only for ROOT compartment, check to see if there is a cross-tenancy policy
        self.logger.debug(f"Checking to see if Cross-tenancy: {statement}")
        result = re.search(CROSS_TENANCY_REGEX, statement, re.IGNORECASE | re.MULTILINE)
        if result and result.group('action') in ['endorse', 'admit', 'define']:
            self.logger.info(f"Cross-tenancy statement parsed: {statement}")
            try:
                statement_list = [
                    policy.name,    #0
                    policy.id,      #1
                    # comp_id,        #2
                    # comp_string,    #3
                    statement,      
                    result.group('action') != 'define',  # Valid if not define
                    result.group('action') if result.group('action') == 'define' else result.group('subjecttype') or 'other',
                    [(None, result.group('subject'))] if result.group('subject') else [],
                    result.group('verb') or '',
                    result.group('resource') or '',
                    result.group('verb') if result.group('verb') and result.group('verb').startswith('{') else '',  # Store custom permissions
                    result.group('locationtype') or '',
                    result.group('location') or '',
                    result.group('condition') or '',
                    result.group('optional') or '',     
                    str(policy.time_created), 
                    True,                               
                    result.group('sourcetype') or '',      # Source tenancy type
                    result.group('source') or '',          # Source tenancy name/OCID
                    result.group('definetype') or '',      # Define type (tenancy, compartment, dynamic-group, group)
                    result.group('alias') or '',           # Tenancy, compartment, dynamic-group, or group alias
                    result.group('ocid') or '',            # OCID (for define)
                    result.group('targettenancytype') or '',  # Target tenancy type
                    result.group('targettenancy') or '',   # Target tenancy name/OCID
                    result.group('withresource') or '',    # With resource
                    result.group('withlocationtype') or '',# With location type
                    result.group('withlocation') or ''     # With location
                ]
                if statement_list[6] in ['any-user', 'any-group']:
                    statement_list[7] = [(None, statement_list[6])]
                # elif statement_list[7] and statement_list[6] in ['group', 'dynamic-group']:
                #     # subject_result = re.findall(SUBJECT_REGEX, statement_list[7][0][1], re.IGNORECASE)
                #     subject_result = self.parse_subjects(statement_list[7])
                #     statement_list[7] = [(a[2] or 'Default', a[4]) for a in subject_result]
                
                # Store cross-tenancy statements and defined aliases
                self.cross_tenancy_statements.append(statement_list)
                if result.group('action') == 'define' and result.group('alias') and result.group('ocid'):
                    self.defined_aliases[result.group('alias')] = (result.group('definetype'), result.group('ocid'))
                
                # Success - CT
                return True
            except Exception as e:
                self.logger.warning(f"Failed to parse cross-tenancy statement: {e}")
                return False
                # return [policy.name, policy.id, comp_id, comp_string, statement,
                #         False, 'other', [], '', '', '', '', '', '', '', str(policy.time_created), False, '', '', '', '', '', '', '', '']

        else:   
            # Regular Statements
            self.logger.debug(f"Hierarchy string: {comp_string}")
            result = re.search(POLICY_REGEX, statement, re.IGNORECASE | re.MULTILINE)
            if result:
                self.logger.debug(f"Subject parsed 1: {result.group('subject')} ||| Statement: {statement}")
                try:
                    statement_list = [
                        policy.name, policy.id, comp_id, comp_string, statement,
                        True, result.group('subjecttype'),
                        result.group('subject') or "",
                        result.group('verb') or "",
                        result.group('resource') or "",
                        result.group('perm') or "",
                        result.group('locationtype') or "",
                        result.group('location') or "",
                        result.group('condition') or "",
                        result.group('optional') or "",
                        str(policy.time_created), True
                    ]

                    # Additional Subject Parsing
                    if statement_list[6] in ["any-user", "any-group"]:
                        statement_list[7] = [(None, statement_list[6])]
                    else:
                        #subject_result = re.findall(SUBJECT_REGEX, statement_list[7], re.IGNORECASE)
                        # Try new subject parser
                        subject_result = self.parse_subjects(statement_list[7])
                        self.logger.debug(f"Subject parsed: {subject_result}")
                        # statement_list[7] = [(a[2] or "Default", a[4]) for a in subject_result]
                        statement_list[7] = subject_result

                    # Additional check for Location Validity
                    if statement_list[11].casefold() == "compartment id":
                        # Check and change validity accordingly
                        statement_list[5] = self.check_invalid_location(statement_list[12])
                        logger.debug(f"Checked OCID {statement_list[12]} - Valid: {statement_list[5]}")
                
                    # Store regular statements
                    self.regular_statements.append(statement_list)
                    
                    # Success
                    return True
                
                except Exception as e:
                    self.logger.warning(f"Failed to parse statement: {e}")
                    return False
                    # return [policy.name, policy.id, comp_id, comp_string, statement,
                    #         False, "other", [], "", "", "", "", "", "", "", str(policy.time_created), False]
            self.logger.info(f"No regex match: {statement}")
            return False
            # return [policy.name, policy.id, comp_id, comp_string, statement,
            #         statement.startswith("define"), "define" if statement.startswith("define") else "other",
            #         [], "", "", "", "", "", "", "", str(policy.time_created), False]

        # Catch All - should never get here
        return False

    def load_compartment_and_policies(self, compartment: Compartment):
        try:
            # Load compartment data
            self.logger.debug(f"Processing compartment: {compartment.name} (OCID: {compartment.id})")
            path, ocids = self.get_compartment_path(compartment, 0, "")
            self.compartments.append({
                "id": compartment.id,
                "name": compartment.name if compartment.id != self.tenancy_ocid else "ROOT",
                "parent_id": compartment.compartment_id,
                "hierarchy_path": path,
                "hierarchy_ocids": ocids
            })
            self.logger.debug(f"Loaded compartment: {compartment.name}, Path: {path}, OCID: {compartment.id}")
            start_time = time.perf_counter()

            # Load policies for the compartment
            policies_response = self.identity_client.list_policies(compartment_id=compartment.id, limit=1000)
            if policies_response.data is None:
                self.logger.warning(f"No policies found for compartment: {compartment.id}")
                return
            policies = policies_response.data
            if not policies:
                return
            load_pol_time = time.perf_counter()
            for policy in policies:
                for statement in policy.statements:
                    # Maybe just let the parser add to either list - returns False if not parsed
                    if not self.parse_statement(str.casefold(statement), compartment.id, policy):
                        self.logger.warning(f"Statement was unable to parse: {statement}")
                    # if parsed_statement[6] == "cross-tenant":
                    #     self.cross_tenancy_statements.append(parsed_statement)
                    # else:
                    #     self.regular_statements.append(parsed_statement)
            parse_time = time.perf_counter()
            self.logger.info(f"{compartment.name}: Policy Load in {load_pol_time-start_time:.2f} and parse all in {parse_time-load_pol_time:.2f}s")

        except Exception as se:
            self.logger.error(f"Failed to load compartment or policies for {compartment.id}: {se}")

    def load_policies_and_compartments(self) -> bool:
        self.compartments = []
        self.regular_statements = []
        start_time = time.perf_counter()
        try:
            root_comp_response = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid)
            if root_comp_response.data is None:
                self.logger.error(f"Failed to get root compartment: {self.tenancy_ocid}")
                return False
            root_comp = root_comp_response.data
            comp_list = [root_comp]
            comp_response = pagination.list_call_get_all_results(
                self.identity_client.list_compartments, self.tenancy_ocid, access_level="ACCESSIBLE",
                sort_order="ASC", compartment_id_in_subtree=True, lifecycle_state="ACTIVE", limit=1000
            )
            if comp_response.data is None:
                self.logger.error("Failed to list compartments")
                return False
            comp_list.extend(comp_response.data)
            comp_load_time = time.perf_counter()
            with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="thread") as executor:
                executor.map(self.load_compartment_and_policies, comp_list)
            self.data_as_of = str(datetime.datetime.now())
            policy_finish_time = time.perf_counter()
            self.logger.info(f"Loaded {len(self.compartments)} compartments in {comp_load_time-start_time:.2f} and {len(self.regular_statements)} policies in {policy_finish_time-comp_load_time:.2f}s")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load policies and compartments: {e}")
            return False

    def save_to_cache(self):
        cache_dir = Path.home() / ".oci" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        compartments_cache_file = cache_dir / f"compartments_{self.tenancy_ocid}.json"
        policies_cache_file = cache_dir / f"policies_{self.tenancy_ocid}.json"
        cross_tenancy_policies_cache_file = cache_dir / f"cross_tenancy_policies_{self.tenancy_ocid}.json"

        # Save compartments
        compartments_data = {
            "compartments": [
                {"id": c["id"], "name": c["name"], "parent_id": c["parent_id"], 
                "hierarchy_path": c["hierarchy_path"], "hierarchy_ocids": c["hierarchy_ocids"]}
                for c in self.compartments
            ],
            "data_as_of": self.data_as_of
        }
        with open(compartments_cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(compartments_data, filehandle, ensure_ascii=False)
        self.logger.info(f"Saved {len(self.compartments)} compartments to cache: {compartments_cache_file}")

        # Save policies
        policies_data = {
            "policies": self.regular_statements,
            "data_as_of": self.data_as_of
        }
        with open(policies_cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(policies_data, filehandle, ensure_ascii=False)
        self.logger.info(f"Saved {len(self.regular_statements)} policies to cache: {policies_cache_file}")

        # Save Cross Tenant and Defined
        policies_data = {
            "cross_tenancy_policies": self.cross_tenancy_statements,
            "defined_aliases": self.defined_aliases,
            "data_as_of": self.data_as_of
        }
        with open(cross_tenancy_policies_cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(policies_data, filehandle, ensure_ascii=False)
        self.logger.info(f"Saved {len(self.cross_tenancy_statements)} policies to cache: {cross_tenancy_policies_cache_file}")
       
    def load_policies_from_cache(self) -> bool:
        cache_dir = Path.home() / ".oci" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        compartments_cache_file = cache_dir / f"compartments_{self.tenancy_ocid}.json"
        policies_cache_file = cache_dir / f"policies_{self.tenancy_ocid}.json"
        cross_tenancy_policies_cache_file = cache_dir / f"cross_tenancy_policies_{self.tenancy_ocid}.json"
        
        # Load compartments
        if compartments_cache_file.exists():
            with open(compartments_cache_file, 'r', encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                self.compartments = cache_data.get("compartments", [])
                self.data_as_of = cache_data.get("data_as_of", time.ctime(compartments_cache_file.stat().st_mtime))
            self.logger.info(f"Loaded {len(self.compartments)} compartments from cache: {compartments_cache_file}")
        else:
            self.logger.warning(f"Compartments cache file not found: {compartments_cache_file}")
            return False

        # Load policies
        if policies_cache_file.exists():
            with open(policies_cache_file, 'r', encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                self.regular_statements = cache_data.get("policies", [])
                if not self.data_as_of:
                    self.data_as_of = cache_data.get("data_as_of", time.ctime(policies_cache_file.stat().st_mtime))
            self.logger.info(f"Loaded {len(self.regular_statements)} policies from cache: {policies_cache_file}")
            # return True
        else:
            self.logger.warning(f"Policies cache file not found: {policies_cache_file}")
            return False

        # Load Cross Tenant and Defined
        if cross_tenancy_policies_cache_file.exists():
            with open(cross_tenancy_policies_cache_file, 'r', encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                self.cross_tenancy_statements = cache_data.get("cross_tenancy_policies", [])
                self.defined_aliases = cache_data.get("defined_aliases", [])
                if not self.data_as_of:
                    self.data_as_of = cache_data.get("data_as_of", time.ctime(cross_tenancy_policies_cache_file.stat().st_mtime))
            self.logger.info(f"Loaded CT policies from cache: {cross_tenancy_policies_cache_file}")
            # return True
        else:
            self.logger.warning(f"Cross Tenancy Policies cache file not found: {cross_tenancy_policies_cache_file}")
            return False
        return True

    def get_compartment_by_id(self, compartment_id: str) -> dict:
        return next((c for c in self.compartments if c["id"] == compartment_id), None)

    def get_hierarchy_ocids(self, compartment_id: str) -> list[str]:
        comp = self.get_compartment_by_id(compartment_id)
        return comp["hierarchy_ocids"] if comp else []

    def get_user_group_statements(self, user_id: str, compartment_id: str = "", user_group_names: List = [], user_domain_name:str = "") -> list:
        try:
            self.logger.info(f"Found {len(user_group_names)} groups for user {user_id}")

            filtered_statements = []
            target_compartment_ocids = self.get_hierarchy_ocids(compartment_id) if compartment_id != "All Compartments" else [c["id"] for c in self.compartments]
            for statement in self.regular_statements:
                if statement[6] == "group":
                    # get the tuples - enumerate list
                    for i, (subj_domain, subj_name) in enumerate(statement[7]):
                        for group_name in user_group_names:
                            
                            self.logger.debug(f"User Group {user_domain_name}/{group_name} in request against tuple ({subj_domain}/{subj_name}) in Policy")
                            # if (subj_domain is None or subj_domain == "Default") and subj_name == group_name:
                            # Need to compare domain name and subject
                            if user_domain_name.casefold() == subj_domain.casefold() and subj_name.casefold() == group_name.casefold():
                                if not compartment_id or statement[2] in target_compartment_ocids:
                                    filtered_statements.append(statement)
                                    self.logger.info(f"Statement Match Subject << {statement[3]} >>  User Group: {user_domain_name}/{group_name} == Policy Subject {subj_domain}/{subj_name}")

                                    # Check now for compartment, if defined
                                    self.logger.info(f"Check matching statement against select compartments {target_compartment_ocids}. Statement Loc: {statement[12]}")
                                break
            self.logger.info(f"Found {len(filtered_statements)} policy statements for user {user_id}")
            return filtered_statements
        except Exception as e:
            self.logger.error(f"Failed to get user group statements: {e}")
            return []

    def get_cross_tenancy_suggestions(self, current_tenancy: str = "CurrentTenancy") -> List[Dict[str, Any]]:
        """
        Generate suggested matching policies for admit and endorse statements.
        Returns a list of dictionaries with original and suggested statements.
        """
        suggestions = []
        for stmt in self.cross_tenancy_statements:
            self.logger.info(f"CT Policy: {stmt[3]}")
            action = stmt[5]  # Valid field indicates action type indirectly
            subject_type = stmt[6]  # Subject type or 'define'
            subject = stmt[7][0][1] if stmt[7] else ''  # Subject name
            verb = stmt[8]  # Verb
            resource = stmt[9]  # Resource
            location_type = stmt[11]  # Location type
            location = stmt[12]  # Location
            condition = stmt[13]  # Condition
            source = stmt[16]  # Source tenancy (for admit)
            target_tenancy = stmt[21]  # Target tenancy (for endorse)
            with_resource = stmt[22]  # With resource
            with_location_type = stmt[23]  # With location type
            with_location = stmt[24]  # With location

            if action and subject_type != 'define':  # Process admit and endorse
                if subject_type in ['group', 'dynamic-group', 'any-user', 'any-group', 'service']:
                    original = stmt[4]  # Original statement
                    suggested = None
                    if action == 'admit':
                        # Suggest endorse in source tenancy
                        source_ocid = self.defined_aliases.get(source, (None, None))[1]
                        target = current_tenancy
                        suggested = f"endorse {subject_type} {subject} to {verb} {resource or 'all-resources'}"
                        if location_type:
                            suggested += f" in {location_type} {location}"
                            if target_tenancy:
                                suggested += f" of tenancy {target_tenancy}"
                        if with_resource and with_location_type:
                            suggested += f" with {with_resource} in {with_location_type} {with_location or ''}"
                        if condition:
                            suggested += f" where {condition}"
                        suggestions.append({
                            "original": original,
                            "suggested": suggested,
                            "target_tenancy": source or source_ocid or "UnknownTenancy",
                            "action": "endorse"
                        })
                    elif action == 'endorse':
                        # Suggest admit in target tenancy
                        target_ocid = self.defined_aliases.get(target_tenancy, (None, None))[1]
                        source = current_tenancy
                        suggested = f"admit {subject_type} {subject} of tenancy {source} to {verb} {resource or 'all-resources'}"
                        if location_type:
                            suggested += f" in {location_type} {location}"
                            if target_tenancy:
                                suggested += f" of tenancy {target_tenancy}"
                        if with_resource and with_location_type:
                            suggested += f" with {with_resource} in {with_location_type} {with_location or ''}"
                        if condition:
                            suggested += f" where {condition}"
                        suggestions.append({
                            "original": original,
                            "suggested": suggested,
                            "target_tenancy": target_tenancy or target_ocid or "UnknownTenancy",
                            "action": "admit"
                        })
        
        return suggestions

    def filter_policy_statements(self, subj_filter: str, verb_filter: str, resource_filter: str, location_filter: str,
                                hierarchy_filter: str, condition_filter: str, text_filter: str, policy_filter: str) -> list:
        filtered = self.regular_statements
        for filt in subj_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in str(st[7]).casefold()]
        for filt in verb_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[8].casefold()]
        for filt in resource_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[9].casefold()]
        for filt in location_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in (st[11] if "tenancy" == filt.lower() else st[12]).casefold()]
        for filt in hierarchy_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[3].casefold()]
        for filt in condition_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[13].casefold()]
        for filt in text_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[4].casefold()]
        for filt in policy_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[0].casefold()]
        self.logger.info(f"Filtered to {len(filtered)} policy statements")
        return filtered

    def filter_policies(self, type_principal: str, principals_style: str, resource_type: str = None, selected_dynamic_group: Tuple = ()) -> List[List[str]]:
        """Filter policies based on principal type, principals style, resource type, and optional dynamic group."""
        filtered = []
        resource_map = {
            'ADB': ['autonomous-databases', 'database', 'db'],
            'Function': ['functions', 'serverless']
        }
        self.logger.info(f"Filtering type: {type_principal} style: {principals_style} resource_type {resource_type} and selected_dynamic_group {selected_dynamic_group}")
        try:
            for stmt in self.regular_statements:
                subject_type = stmt[6]
                resource = stmt[9]
                subject = stmt[7] if stmt[7] else []
                condition = stmt[13]
                
                # self.logger.info(f"Subject Type {subject_type}")

                # Cases
                # If IP / DG and selected row name contains DG name, subj type is DG, then append if DG domain and subject match policy domain/Subj
                # Principal type filter
                principal_match = subject_type in ['dynamic-group', 'any-user']
                if not principal_match:
                    # Only interested in statements related to DG and any-user
                    continue

                if type_principal == 'Instance Principals':
                    # If no DG selected, just allow if prinicpal match
                    if selected_dynamic_group == () and subject_type == 'any-user':
                        self.logger.debug(f"MATCH any-user to IP based on principal type alone")
                        filtered.append(stmt)
                    elif selected_dynamic_group != () and subject_type == 'dynamic-group':
                        # There is a selected DG so we can assume this comparison will work. Iterate subject and look for match
                        for subj in subject:
                            self.logger.debug(f"Policy Subject: {subj} against {selected_dynamic_group}")
                            
                            if subj[0].casefold() == selected_dynamic_group[0].casefold() and subj[1].casefold() == selected_dynamic_group[1].casefold():
                                self.logger.debug(f"MATCH IP based on subject domain and DG match")
                                filtered.append(stmt)

                elif type_principal == 'Resource Principals':
                    if selected_dynamic_group == () and subject_type == 'any-user':
                        self.logger.debug(f"MATCH any-user to RP based on principal type alone")
                        filtered.append(stmt)
                    elif selected_dynamic_group != () and subject_type == 'dynamic-group':
                        # There is a selected DG so we can assume this comparison will work. Iterate subject and look for match
                        for subj in subject:
                            self.logger.debug(f"Policy Subject: {subj} against {selected_dynamic_group}")
                            
                            if subj[0].casefold() == selected_dynamic_group[0].casefold() and subj[1].casefold() == selected_dynamic_group[1].casefold():
                                self.logger.debug(f"MATCH RP based on subject domain and DG match")
                                filtered.append(stmt)
                    
                # # Resource type filter for Resource Principals
                # resource_match = True
                # if type_principal == 'Resource Principals' and resource_type and resource_type != 'Any':
                #     resource_match = resource in resource_map.get(resource_type, [])
                
                # if principal_match:
                #     if principals_style == 'any-user + conditions':
                #         if subject_type == 'any-user' and condition and (type_principal == 'Instance Principals' or resource_match):
                #             filtered.append([
                #                 stmt[4], stmt[6], stmt[7][0][1] if stmt[7] else '', stmt[8], stmt[9],
                #                 stmt[11], stmt[12], stmt[13]
                #             ])
                #     elif principals_style == 'Dynamic Group':
                #         if subject_type == 'dynamic-group' and (type_principal == 'Instance Principals' or resource_match):
                #             if not selected_dynamic_group or subject == selected_dynamic_group:
                #                 filtered.append([
                #                     stmt[4], stmt[6], stmt[7][0][1] if stmt[7] else '', stmt[8], stmt[9],
                #                     stmt[11], stmt[12], stmt[13]
                #                 ])
        except Exception as e:
            self.logger.warning(f"Failed to filter: {e}")
        self.logger.info(f"Principals-based Filter returning {len(filtered)} policies")
        return filtered

class IdentityDomainsAnalysis:
    def __init__(self, verbose: bool):
        self.logger = logging.getLogger('oci-policy-analysis')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        self.tenancy_ocid = None
        self.identity_client = None
        self.signer = None
        self.config = None
        self.use_instance_principal = False
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users = []
        self.domain_clients = {}
        self.policies = []
        self.data_as_of = ""

        self.logger.info("Initialized IdentityDomainsAnalysis")

    def initialize_client(self, use_instance_principal: bool, profile: str = "DEFAULT") -> bool:
        try:
            self.use_instance_principal = use_instance_principal
            if use_instance_principal:
                self.logger.debug("Using Instance Principal Authentication")
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            else:
                self.logger.debug(f"Using Profile Authentication: {profile}")
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.tenancy_ocid = self.config["tenancy"]
            self.logger.info(f"Set up Identity Client for tenancy: {self.tenancy_ocid}")
            return True
        except (ConfigFileNotFound, Exception) as exc:
            self.logger.fatal(f"Authentication failed: {exc}")
            return False

    def parse_dynamic_group(self, dg_name: str, dg_ocid: str, dg_domain: str, dg_rule: str, dg_created: str) -> list:
        # rules = re.findall(r'[\w.]+\s*=\s*\'[\w\s.]+\'', dg_rule, re.IGNORECASE | re.MULTILINE)
        return [dg_domain, dg_name, dg_rule, True, dg_ocid, dg_created]
        # To-do: Add back invalid OCID analysis

    def load_all_dynamic_groups(self) -> bool:
        self.dynamic_groups = []

        # We need to go through all domains
        try:
            domains_response = self.identity_client.list_domains(compartment_id=self.tenancy_ocid)
            if domains_response and domains_response.data:
                for domain in domains_response.data:
                    self.logger.debug(f"Domain {domain.display_name}, OCID {domain.id}")
                    if self.use_instance_principal:
                        domain_client = IdentityDomainsClient(config={}, signer=self.signer, service_endpoint=domain.url)
                    else:
                        domain_client = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
                    self.domain_clients[domain.id] = domain_client

                    dg_response = domain_client.list_dynamic_resource_groups(attribute_sets=["all"])
                    if dg_response and dg_response.data and dg_response.data.resources:
                        
                        self.logger.debug(f"Got the List of DG for {domain.display_name}.  Count: {len(dg_response.data.resources)}")
                        for dg in dg_response.data.resources:
                            self.logger.info(f"DG: {dg}")

                            time_created = dg.meta.created
                            self.dynamic_groups.append(self.parse_dynamic_group(
                                dg_domain=domain.display_name, dg_name=dg.display_name, dg_ocid=dg.ocid,
                                dg_rule=dg.matching_rule, dg_created=str(time_created)
                            ))
                    else:
                        self.logger.error("Failed to list dynamic groups")
                        return False
                    self.logger.info(f"Loaded {len(self.dynamic_groups)} dynamic groups")
            self.data_as_of = str(datetime.datetime.now())
            return True
        except ServiceError as se:
            self.logger.error(f"Failed to load dynamic groups: {se}")
            return False

    def set_statements(self, statements: list):
        self.policies = statements

    def dg_in_use(self, dg: list) -> bool:
        for statement in self.policies:
            for subj in statement[7]:
                if subj[0] and dg[0].casefold() == subj[0].casefold() and dg[1].casefold() == subj[1].casefold():
                    return True
        return False

    def run_dg_in_use_analysis(self) -> list:
        unused_dynamic_groups = []
        for dg in self.dynamic_groups:
            dg[3] = self.dg_in_use(dg)
            if not dg[3]:
                unused_dynamic_groups.append(dg)
        self.logger.info(f"Found {len(unused_dynamic_groups)} unused dynamic groups")
        return unused_dynamic_groups

    def filter_dynamic_groups(self, domain_filter=None, name_filter=None, type_filter=None, ocid_filter=None) -> list:
        filtered = []

        domain_terms = [dom.strip().lower() for dom in domain_filter.split("|") if dom.strip()] if domain_filter else []
        name_terms = [term.strip().lower() for term in name_filter.split("|") if term.strip()] if name_filter else []
        type_terms = [ty.strip().lower() for ty in type_filter.split("|") if ty.strip()] if type_filter else []
        ocid_terms = [oc.strip().lower() for oc in ocid_filter.split("|") if oc.strip()] if ocid_filter else []
        self.logger.debug(f"Filtering DGs based on Domain: {domain_filter} and Name: {name_filter}")
        for dg in self.dynamic_groups:
            matches_domain = not domain_terms or any(term in str(dg[0]).lower() for term in domain_terms)
            matches_name = not name_terms or any(term in str(dg[1]).lower() for term in name_terms)
            matches_type = not type_terms or any(term in str(dg[2]).lower() for term in type_terms)
            matches_ocid = not ocid_terms or any(term in str(dg[4]).lower() for term in ocid_terms)
            if matches_name and matches_domain and matches_type and matches_ocid: 
                self.logger.debug(f"Adding DG {dg[0]}/{dg[1]} due to filter match")
                filtered.append(dg)

        self.logger.info(f"Filtered to {len(filtered)} dynamic groups")
        return filtered

    def get_user_groups(self, domain_id: str, user_id: str) -> List[str]:
        domain_client = self.get_domain_client(domain_id)
        if not domain_client:
            self.logger.error(f"No client for domain {domain_id}")
            return []
        try:
            response = domain_client.get_user(user_id=user_id, attribute_sets=["all"])
            if response and response.data:
                group_names = [g.display for g in getattr(response.data, 'groups', [])]
                self.logger.debug(f"Found {len(group_names)} groups for user {user_id} in domain {domain_id}")
                return group_names
        except Exception as e:
            self.logger.error(f"Failed to list users for groups in domain {domain_id}: {e}")
            return []

    def load_domains_groups_users(self) -> bool:
        try:
            domain_response = self.identity_client.list_domains(compartment_id=self.tenancy_ocid) # type: ignore
            if domain_response.data is None: # type: ignore
                self.logger.error("Failed to list identity domains")
                return False
            self.identity_domains = domain_response.data
            self.logger.info(f"Loaded {len(self.identity_domains)} identity domains")

            self.domain_clients = {}
            self.groups = []
            self.users = []
            for domain in self.identity_domains:
                try:
                    if self.use_instance_principal:
                        domain_client = IdentityDomainsClient(config={}, signer=self.signer, service_endpoint=domain.url)
                    else:
                        domain_client = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
                    self.domain_clients[domain.id] = domain_client

                    start_index = 1
                    limit = 1000
                    while True:
                        group_response = domain_client.list_groups(start_index=start_index, count=limit, sort_by="displayName", sort_order="ASCENDING")
                        if group_response.data is None or not group_response.data.resources:
                            break
                        self.groups.extend([{"domain_id": domain.id, "id": g.id, "display_name": g.display_name} for g in group_response.data.resources])
                        if len(group_response.data.resources) < limit or start_index + limit > group_response.data.total_results:
                            break
                        start_index += limit

                    start_index = 1
                    while True:
                        user_response = domain_client.list_users(start_index=start_index, count=limit, sort_by="displayName", sort_order="ASCENDING")
                        if user_response.data is None or not user_response.data.resources:
                            break
                        self.users.extend([{"domain_id": domain.id, "id": u.id, "display_name": u.display_name} for u in user_response.data.resources])
                        if len(user_response.data.resources) < limit or start_index + limit > user_response.data.total_results:
                            break
                        start_index += limit
                except Exception as e:
                    self.logger.error(f"Failed to load groups/users for domain {domain.id}: {e}")
                    continue
            self.logger.info(f"Loaded {len(self.groups)} groups and {len(self.users)} users across all domains")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load identity domains: {e}")
            return False

    def get_domain_client(self, domain_id: str) -> IdentityDomainsClient:
        return self.domain_clients.get(domain_id) # type: ignore

    def get_domains(self) -> list:
        return [{"id": d.id, "display_name": d.display_name, "url": d.url} for d in self.identity_domains]

    def get_domain_name_by_id(self, domain_id: str) -> str:
        for dom in self.identity_domains:
            if dom.id == domain_id:
                return dom.display_name
        return "Unk"

    def get_users_by_domain(self, domain_id: str) -> list:
        return [u for u in self.users if u["domain_id"] == domain_id]

    def save_to_cache(self):
        cache_dir = Path.home() / ".oci" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"oci_analysis_{self.tenancy_ocid}.json"
        cache_data = {
            "dynamic_groups": self.dynamic_groups,
            "identity_domains": [{"id": d.id, "display_name": d.display_name, "url": d.url} for d in self.identity_domains],
            "groups": self.groups,
            "users": self.users,
            "data_as_of": self.data_as_of
        }
        with open(cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(cache_data, filehandle, ensure_ascii=False)
        self.logger.info(f"Saved data to cache: {cache_file}")

    def load_from_cache(self) -> bool:
        cache_dir = Path.home() / ".oci" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"oci_analysis_{self.tenancy_ocid}.json"
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                self.dynamic_groups = cache_data.get("dynamic_groups", [])
                self.identity_domains = [
                    Domain(id=d["id"], display_name=d["display_name"], url=d["url"])
                    for d in cache_data.get("identity_domains", [])
                ]
                self.groups = cache_data.get("groups", [])
                self.users = cache_data.get("users", [])
                for domain in self.identity_domains:
                    if self.use_instance_principal:
                        self.domain_clients[domain.id] = IdentityDomainsClient(config={}, signer=self.signer, service_endpoint=domain.url)
                    else:
                        self.domain_clients[domain.id] = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
            self.logger.info(f"Loaded data from cache: {cache_file}")
            return True
        self.logger.warning(f"Cache file not found: {cache_file}")
        return False
