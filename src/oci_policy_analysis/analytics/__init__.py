##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/__init__.py
#
# Package for usage analytics tooling for the OCI Policy Analysis UI.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Usage analytics package for OCI Policy Analysis.

This package provides a small, standalone Tkinter UI that can read anonymous
usage tracking documents written by :mod:`oci_policy_analysis.common.usage_tracking`
and present basic aggregate metrics (runs, tenancies, tab usage, etc.).

The main entry points are :func:`oci_policy_analysis.analytics.main.main` and
the :class:`oci_policy_analysis.analytics.main.AnalyticsApp` class.
"""

from .main import AnalyticsApp, main

__all__ = ['AnalyticsApp', 'main']
