##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# config.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import os

from oci_policy_analysis.common.logger import get_logger

SETTINGS_PATH = os.path.expanduser('~/.oci-policy-analysis/settings.json')

logger = get_logger(component='config')


def load_settings():
    """
    Load settings from the settings file.
    Returns an empty dict if the file does not exist or cannot be read.
    """
    try:
        with open(SETTINGS_PATH) as f:
            logger.info(f'Loading settings from {SETTINGS_PATH}')
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f'Settings file not found: {SETTINGS_PATH}')
        return {}
    except Exception:
        return {}


def save_settings(settings: dict):
    """
    Save settings to the settings file.
    Silent failure is acceptable."""
    try:
        logger.debug(f'Settings: {settings}')
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            logger.info(f'Saving settings to {SETTINGS_PATH}')
            json.dump(settings, f, indent=2)
    except Exception:
        # Silent failure is OK for settings writes in this app
        pass
