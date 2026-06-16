"""Tkinter UI components for OCI Policy Analysis."""

from .console_tab import ConsoleTab
from .consolidation_workbench_tab import ConsolidationWorkbenchTab

# REMOVED: import of ConsolidationWorkbenchTab (consolidation feature disabled)
from .data_table import CheckboxTable, DataTable
from .dynamic_group_tab import DynamicGroupsTab
from .historical_tab import HistoricalTab
from .maintenance_tab import MaintenanceTab

try:
    from .mcp_tab import McpTab
except ModuleNotFoundError:
    # Optional dependency path: McpTab requires fastmcp via mcp_server.
    # Keep package importable when extras are not installed.
    McpTab = None  # type: ignore[assignment]
from .permissions_report_tab import PermissionsReportTab
from .policies_tab import PoliciesTab
from .policy_browser_tab import PolicyBrowserTab
from .policy_recommendations_tab import PolicyRecommendationsTab
from .settings_tab import SettingsTab
from .users_tab import UsersTab
from .workload_principals_tab import WorkloadPrincipalsTab

__all__ = [
    'SettingsTab',
    'PoliciesTab',
    'PolicyBrowserTab',
    'DynamicGroupsTab',
    'UsersTab',
    'ConsoleTab',
    'PolicyRecommendationsTab',
    'McpTab',
    'WorkloadPrincipalsTab',
    'DataTable',
    'CheckboxTable',
    'MaintenanceTab',
    'ConsoleTab',
    'HistoricalTab',
    'PermissionsReportTab',
    'ConsolidationWorkbenchTab',
]
