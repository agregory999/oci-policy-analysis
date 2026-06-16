##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# models.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################
"""Legacy re-exports for model modules (compatibility shim)."""

from .models_iam import (  # noqa: F401
    Compartment,
    DynamicGroup,
    DynamicGroupSearch,
    Group,
    GroupSearch,
    User,
    UserSearch,
)
from .models_policy import (  # noqa: F401
    AdmitStatement,
    BasePolicy,
    BasePolicyStatement,
    DefineStatement,
    EndorseStatement,
    PolicyFilterResponse,
    PolicyIntelligence,
    PolicyOverlap,
    PolicySearch,
    PolicyStatementFull,
    PolicySummary,
    Principal,
    RegularPolicyStatement,
)
from .models_reference_data import (  # noqa: F401
    FamilyResourcesRow,
    OperationPermissionsRow,
    ResourceFamilyRow,
)
from .models_responses import (  # noqa: F401
    DynamicGroupSearchFull,
    DynamicGroupSearchResponse,
    DynamicGroupSummary,
    GroupSearchFull,
    GroupSearchResponse,
    GroupSummary,
    ReferenceDataDiffResult,
    UserSearchFull,
    UserSearchResponse,
    UserSummary,
)
from .models_simulation import (  # noqa: F401
    SimulationBatchRequest,
    SimulationBatchResponse,
    SimulationPrepareRequest,
    SimulationPrepareResponse,
    SimulationPrincipalType,
    SimulationResult,
    SimulationScenario,
)
