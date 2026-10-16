OCI Policy Analysis Application Core
====================================

The core reference covers the maintained models, parsers, repositories,
services, and engines used by the CLI, UI, web application, and MCP server.

Runtime context and lifecycle
-----------------------------

Construct a context, load an input through LoadService, then query through the
focused services below. Full and minimal post-load profiles have different
outputs; successful loading is not a claim of complete data or OCI-authoritative
access. See :doc:`../core_integration` for embedding examples and lifecycle guidance.

.. automodule:: oci_policy_analysis.application.context
   :members: AppContext

.. automodule:: oci_policy_analysis.application.post_load
   :members: run_minimal_post_load_enrichment, run_post_load_pipeline

Policy corpora
--------------

.. automodule:: oci_policy_analysis.application.core.policy_corpus
   :members: CorpusProvenance, PolicyCorpusFact, CorpusExclusion, PolicyCorpus, PolicyCorpusBuilder, permissions_report_projection

.. automodule:: oci_policy_analysis.application.core.cross_tenancy_corpus
   :members: CrossTenancyCorpus, CrossTenancyCorpusBuilder

Models
------

.. automodule:: oci_policy_analysis.application.core.models.models
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.models.models_iam
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.models.models_policy
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.models.models_consolidation
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.models.models_responses
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.models.models_simulation
   :members:
   :show-inheritance:

Repositories and parsing
------------------------

.. automodule:: oci_policy_analysis.application.core.repo.policy_analysis_repository
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.repo.reference_data_repo
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.parser.policy_statement_normalizer
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.parser.policy_subject_parser
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.parser.condition_structure
   :members:
   :show-inheritance:

Engines and services
--------------------

.. automodule:: oci_policy_analysis.application.core.engine.policy_intelligence_engine
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.engine.policy_simulation_engine
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.analysis_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.load_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.simulation_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.recommendations_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.principal_analysis_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.mcp_query_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.policy_graph_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.permissions_report_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.cross_tenancy_analysis_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.intelligence_service
   :members:
   :show-inheritance:

Support
-------

.. automodule:: oci_policy_analysis.application.core.support.caching
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.support.helpers
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.core.support.logger
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.prospective_workbench_service
   :members:
   :show-inheritance:

.. automodule:: oci_policy_analysis.application.services.condition_tester_service
   :members:

.. automodule:: oci_policy_analysis.application.services.simulation_workbench_service
   :members:
