##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_strategies – Pluggable consolidation strategy protocol and registry.
#
# Implement Strategy (from .base) in your own module and register with
# ConsolidationEngine via register_strategy() or the strategies= constructor argument.
# The engine does not depend on concrete strategy implementations.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from oci_policy_analysis.logic.consolidation_strategies.base import Strategy

__all__ = ['Strategy']
