.. _context:

===============================
AI & Project Context Reference
===============================

This section contains deep context documentation for both generic standards (UI/coding conventions) and **project-specific** feature architecture and subsystems for OCI Policy Analysis.

Use these docs for onboarding, design reviews, and as canonical references for internal contracts, extension points, and major architectural decisions.

Organization
------------

There are two types of context documentation included here:

Generic Context

General coding standards, UI guidelines, and overall policy for any project:

Project-specific Context

Architecture, wiring, contracts, and component-level context for all features and UI tabs. These files are the canonical documentation for how subsystems are designed and connected.

Naming Convention for Context File Titles
-----------------------------------------

To ensure consistent indexing throughout the Sphinx documentation:

- Project files should start with::

    # Context: <Short Feature or Area Title>
    (e.g., "Context: Policy Intelligence and Recommendations")

- Generic files should start with::

    # Generic <Subject or Convention>
    (e.g., "Generic Coding Standards")

The first heading of each file will appear as its title in the documentation navigation/sidebar.

----

.. toctree::
   :maxdepth: 1
   :caption: Generic Context

   context/generic/GENERIC_README.md
   context/generic/GENERIC_CODING_STANDARDS.md
   context/generic/GENERIC_DOCUMENTATION.md

.. toctree::
   :maxdepth: 1
   :caption: Project-specific Context

   context/project/CONTEXT_cli.md
   context/project/CONTEXT_cross_tenancy.md
   context/project/CONTEXT_data_repo.md
   context/project/CONTEXT_historical_analysis.md
   context/project/CONTEXT_intelligence_strategies.md
   context/project/CONTEXT_logging.md
   context/project/CONTEXT_logic.md
   context/project/CONTEXT_mcp_server_and_tab.md
   context/project/CONTEXT_policies_tab.md
   context/project/CONTEXT_policy_browser_tab.md
   context/project/CONTEXT_policy_intelligence_and_recommendations.md
   context/project/CONTEXT_settings_tab.md
   context/project/CONTEXT_simulation_engine.md
   context/project/CONTEXT_tests.md
   context/project/CONTEXT_ui.md