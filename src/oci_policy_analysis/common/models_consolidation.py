##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# models_consolidation.py
#
# Canonical models for consolidation: plan/step types, protected sets, execution
# status, and audit. Kept logically separate so engines and strategies depend on
# these types only; new strategies and consumers can plug in without redefining
# the data shapes.
#
# @author: Andrew Gregory
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from typing import Annotated, Literal, NotRequired, TypedDict

# ================================
# Core Identifier Models
# ================================


class ProtectedStatementReference(TypedDict):
    """
    Unique reference for a protected statement, captures context for later reconciliation,
    supports fuzzy/orphan recovery.
    """

    internal_id: Annotated[str, 'Hash ID of policy statement (may change if user edits statement)']
    policy_ocid: Annotated[str, 'OCI Policy OCID this statement belongs to']
    policy_name: Annotated[str, 'Human policy name']
    statement_text: Annotated[str, 'Canonical policy statement text at time of protection']
    added_at: NotRequired[Annotated[str, 'Timestamp when statement was protected (ISO-8601)']]


class ProtectedStatementSet(TypedDict):
    """
    Canonical set of protected (non-consolidatable) statements for a session/project.
    Tied to a corpus/policy set for context, supports load validation and orphan reporting.
    """

    corpus_id: Annotated[str, 'Unique ID (e.g., tenancy OCID or user label) for this policy corpus']
    dataset_version: NotRequired[Annotated[str, 'Version label or hash for this snapshot of policy set']]
    protected: Annotated[list[ProtectedStatementReference], 'List of protected statements (with context)']
    orphaned_internal_ids: NotRequired[Annotated[list[str], 'Protected internal_ids not found on load']]
    last_updated: NotRequired[Annotated[str, 'Timestamp']]


class CandidateStatementReference(TypedDict):
    """
    Reference for a candidate statement nominated for consolidation.
    """

    internal_id: Annotated[str, 'Hash/internal ID']
    policy_ocid: Annotated[str, 'Policy OCID']
    statement_text: Annotated[str, 'Policy statement text at time of nomination']
    nominated_at: NotRequired[Annotated[str, 'Timestamp']]


class CandidateSelectionSet(TypedDict):
    """
    Explicit set of statements selected as candidates for consolidation (per session/project).
    """

    corpus_id: Annotated[str, 'Unique ID of policy corpus']
    candidates: Annotated[list[CandidateStatementReference], 'Current set of candidate statements']
    orphaned_internal_ids: NotRequired[Annotated[list[str], 'Candidates not found on load']]
    last_updated: NotRequired[Annotated[str, 'Timestamp']]


# ================================
# Consolidation Plan & Plan Steps
# ================================


class PlanStep(TypedDict):
    """
    Single step in a consolidation plan: add, modify, or delete a policy, or change tags/statements.
    Each step may track before/after, tags, rollback, and execution result.
    """

    step_id: Annotated[str, 'Unique plan step identifier']
    action: Annotated[Literal['add', 'modify', 'delete'], 'Plan step action type']
    policy_ocid: Annotated[str, 'Target policy OCID']
    before_statements: Annotated[list[str], 'Statements before this step is applied']
    after_statements: Annotated[list[str], 'Statements after this step is applied']
    before_tags: Annotated[dict[str, str], 'Tag state before step']
    after_tags: Annotated[dict[str, str], 'Desired tag state after step']
    plan_tags: NotRequired[Annotated[dict[str, str], 'Plan-specific tags to mark plan/step']]
    executed: NotRequired[Annotated[bool, 'Whether this step has been executed/applied']]
    executed_at: NotRequired[Annotated[str, 'Timestamp of execution']]
    execution_status: NotRequired[Annotated[Literal['PENDING', 'COMPLETE', 'ROLLED_BACK', 'DRIFTED'], 'Current status']]
    execution_notes: NotRequired[Annotated[str, 'API/OCI result notes, error etc.']]
    rollback_command: NotRequired[Annotated[str, 'Command or instruction to roll back this step']]
    location_change_notes: NotRequired[
        Annotated[
            list[str], 'Notes when statement location was rewritten due to policy move (e.g. compartment X to A:B).'
        ]
    ]
    # For action='add': policy_ocid empty; use these to render create/rollback. For action='delete': store original for display/rollback.
    compartment_ocid: NotRequired[Annotated[str, 'Compartment OCID (add: where to create; delete: original)']]
    create_policy_name: NotRequired[Annotated[str, 'Policy name (add: new; delete: original, for display/rollback)']]
    create_policy_description: NotRequired[
        Annotated[str, 'Description for the new policy (add step only); user may change.']
    ]


class ConsolidationPlan(TypedDict):
    """
    Full consolidation plan: corpus, steps, plan label, execution log.
    Supports before/after tags/statements, per-policy, per-step.
    """

    plan_id: Annotated[str, 'Unique ID for this plan']
    corpus_id: Annotated[str, 'Corpus or tenancy ID']
    plan_label: Annotated[str, 'User label for this plan (optional)']
    created_at: Annotated[str, 'Creation timestamp']
    plan_steps: Annotated[list[PlanStep], 'Full set of steps for the plan']
    execution_log: NotRequired[Annotated[list[str], 'History of execution attempts']]
    plan_tags: NotRequired[Annotated[dict[str, str], 'Tags used to mark plan/steps in OCI']]


# ================================
# Execution Validation/Check-in & Audit
# ================================


class PlanExecutionCheckResult(TypedDict):
    """
    Outcome of reloading policy data and checking/tagging plan execution.
    """

    step_id: Annotated[str, 'The step being checked']
    policy_ocid: Annotated[str, 'Policy being checked']
    executed: Annotated[bool, 'Does current policy/tag state match after_*?']
    missing: NotRequired[Annotated[bool, 'Policy or tag missing on reload']]
    drifted: NotRequired[Annotated[bool, 'Present but data does not match expected']]
    execution_notes: NotRequired[Annotated[str, 'Details of match/mismatch']]
    checked_at: Annotated[str, 'When check was performed']


class ConsolidationSessionAuditEntry(TypedDict):
    """
    Audit log for session/project, tracking user and system actions for transparency, rollback, and reporting.
    """

    timestamp: Annotated[str, 'Timestamp of action']
    user: Annotated[str, 'User or system role']
    action: Annotated[str, 'What was performed (UI selection, plan create, execute step, rollback, etc)']
    details: NotRequired[Annotated[dict, 'Additional context']]


class ConsolidationSession(TypedDict):
    """
    Links together a persistent session: corpus, protection, candidates, plan, and audit.
    This is the root object to (de)serialize to disk/cloud for long-lived projects.
    """

    corpus_id: Annotated[str, 'Policy corpus/tenancy']
    dataset_version: NotRequired[Annotated[str, 'Loaded data version']]
    protected_set: Annotated[ProtectedStatementSet, 'Set of protected statements']
    candidate_set: Annotated[CandidateSelectionSet, 'Selected statements to consolidate']
    plan: Annotated[ConsolidationPlan, 'Proposed or active plan']
    audit_log: NotRequired[Annotated[list[ConsolidationSessionAuditEntry], 'Full session audit log']]
    execution_results: NotRequired[
        Annotated[dict[str, PlanExecutionCheckResult], 'Most recent per-step execution check']
    ]
