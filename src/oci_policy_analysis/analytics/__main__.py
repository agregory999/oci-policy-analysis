##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/__main__.py
#
# Module entry point for ``python -m oci_policy_analysis.analytics``.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Module entry point for the usage analytics UI.

This module allows the analytics UI to be launched via::

    python -m oci_policy_analysis.analytics --days 30

It simply delegates to :func:`oci_policy_analysis.analytics.main.main`.
"""

from .main import main

if __name__ == '__main__':  # pragma: no cover - CLI entry
    main()
