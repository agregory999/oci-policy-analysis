OCI Policy Analysis Entry Points
================================

Desktop application
-------------------

.. automodule:: oci_policy_analysis.main
   :members: App, main
   :show-inheritance:

Command-line interface
----------------------

.. automodule:: oci_policy_analysis.cli
   :members: main

Web application
---------------

The ASGI application is available as ``oci_policy_analysis.presentation.web.main.app``.

.. automodule:: oci_policy_analysis.presentation.web.main
   :members: main

Standalone MCP server
---------------------

The MCP tool functions are included explicitly because their docstrings form
part of the context presented to MCP consumers.

.. automodule:: oci_policy_analysis.mcp_server
   :members: main, create_snapshot_server, get_registered_tools, health_check, policy_search,
      tag_based_policy_search, oke_workload_identity_search, policy_search_set,
      policy_history_search, identity_search, data_operations,
      cross_tenancy_search
