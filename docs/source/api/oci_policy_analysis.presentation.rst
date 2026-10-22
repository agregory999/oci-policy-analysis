OCI Policy Analysis Presentation
================================

Desktop UI
----------

The desktop reference lists the maintained tab and reusable table modules. UI
callbacks and private widget helpers remain implementation details.

.. automodule:: oci_policy_analysis.presentation.desktop.base_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.settings_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.policies_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.policy_browser_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.policy_recommendations_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.mcp_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.workload_principals_tab
   :members:
   :show-inheritance:
   :no-index:

.. automodule:: oci_policy_analysis.presentation.desktop.dynamic_group_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.users_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.permissions_report_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.historical_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.simulation_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.condition_tester_tab
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.desktop.data_table
   :members:
   :show-inheritance:

Qt desktop prototype
--------------------

Install the optional ``qt`` extra to run this source-level desktop exploration.
See :doc:`../core_integration` for launch commands and lifecycle limitations.

.. automodule:: oci_policy_analysis.presentation.qt

.. automodule:: oci_policy_analysis.presentation.qt.main
   :members: WorkbenchWindow, main


.. automodule:: oci_policy_analysis.presentation.qt.controller
   :members: WorkbenchController

.. automodule:: oci_policy_analysis.presentation.qt.loading
   :members: LoadWorker

.. automodule:: oci_policy_analysis.presentation.qt.pages.overview
   :members: OverviewSettingsPage

.. automodule:: oci_policy_analysis.presentation.qt.pages.browser
   :members: PolicyBrowserPage

.. automodule:: oci_policy_analysis.presentation.qt.pages.graph
   :members: PolicyGraphPage

.. automodule:: oci_policy_analysis.presentation.qt.pages.activity
   :members: LoadActivityPage

.. automodule:: oci_policy_analysis.presentation.qt.logging_panel
   :members: LogBridge, LoggingPanel, LiveLogView

.. automodule:: oci_policy_analysis.presentation.qt.settings_panels
   :members: IntelligencePanel, AppearancePanel

.. automodule:: oci_policy_analysis.presentation.qt.icons
   :members: application_icon

Web UI
------

For the ASGI application and server launcher, see :doc:`oci_policy_analysis`.

.. automodule:: oci_policy_analysis.presentation.web.api.routes_core
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.qt.pages.users_groups
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.dynamic_groups
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.tables
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.details
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.themes
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.preferences
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.logger_catalog
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.mcp
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.mcp_host
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.codex_client
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.claude_client
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.resource_principals
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.launcher
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.experience
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.selection_table
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.workflows
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.consolidation
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.prospective
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.condition_tester
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.simulation
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.simulation_statements
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.simulation_controller
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.simulation_request
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.simulation_results
   :members:


.. automodule:: oci_policy_analysis.presentation.qt.frozen_smoke
   :members:


.. automodule:: oci_policy_analysis.presentation.qt.pages.reports
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.pages.recommendations
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.qt.pages.historical
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.qt.json_view
   :members:
   :show-inheritance:


.. automodule:: oci_policy_analysis.presentation.qt.pages.maintenance
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.presentation.qt.api_calls
   :members:


.. automodule:: oci_policy_analysis.analytics.qt
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.analytics.loader
   :members:

.. automodule:: oci_policy_analysis.analytics.model
   :members:

.. automodule:: oci_policy_analysis.presentation.qt.policy_limits
   :members: PolicyLimitsDialog


.. automodule:: oci_policy_analysis.presentation.qt.pages.tag_based
   :members:
