"""Tkinter UI components for OCI Policy Analysis."""

from .console_tab import ConsoleTab
from .data_table import DataTable
from .dynamic_group_tab import DynamicGroupsTab
from .mcp_tab import McpTab
from .policies_tab import PoliciesTab
from .policy_overlap_tab import PolicyOverlapTab
from .report_tab import ReportTab
from .resource_principals_tab import ResourcePrincipalsTab
from .settings_tab import SettingsTab
from .users_tab import UsersTab

__all__ = [
    'SettingsTab',
    'PoliciesTab',
    'DynamicGroupsTab',
    'UsersTab',
    'ReportTab',
    'ConsoleTab',
    'PolicyOverlapTab',
    'McpTab',
    'ResourcePrincipalsTab',
    'DataTable',
]
