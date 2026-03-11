"""Tkinter UI components for OCI Policy Analysis."""

from .console_tab import ConsoleTab
from .consolidation_workbench_tab import ConsolidationWorkbenchTab

# REMOVED: import of ConsolidationWorkbenchTab (consolidation feature disabled)
from .data_table import CheckboxTable, DataTable
from .dynamic_group_tab import DynamicGroupsTab
from .historical_tab import HistoricalTab
from .maintenance_tab import MaintenanceTab
from .mcp_tab import McpTab
from .permissions_report_tab import PermissionsReportTab
from .policies_tab import PoliciesTab
from .policy_browser_tab import PolicyBrowserTab
from .policy_recommendations_tab import PolicyRecommendationsTab
from .report_tab import ReportTab
from .resource_principals_tab import ResourcePrincipalsTab
from .settings_tab import SettingsTab
from .users_tab import UsersTab

__all__ = [
    'SettingsTab',
    'PoliciesTab',
    'PolicyBrowserTab',
    'DynamicGroupsTab',
    'UsersTab',
    'ReportTab',
    'ConsoleTab',
    'PolicyRecommendationsTab',
    'McpTab',
    'ResourcePrincipalsTab',
    'DataTable',
    'CheckboxTable',
    'MaintenanceTab',
    'ConsoleTab',
    'HistoricalTab',
    'PermissionsReportTab',
    'ConsolidationWorkbenchTab',
]
