# Context: Data Model and Data Repository Architecture

This context file explains the core architecture for data management in OCI Policy Analysis—how canonical data models (`models.py`) and the central data repository (`data_repo.py`) work together to supply consistent, strongly-typed data to every UI component.

---

## 1. Canonical Data Models (`common/models.py`)

- **Definition and Purpose**: All tenancy data—policy statements, users, groups, dynamic groups, compartments, simulation requests/results—is defined using `TypedDict` classes with detailed docstrings.
- **Coverage**:
  - **IAM Entities**: Precise models for Users, Groups, Dynamic Groups
  - **Policies**: BasePolicy, RegularPolicyStatement, plus parsed statement types (allow/deny, define, admit, endorse)
  - **Simulation Flows**: Structured request/response formats for simulation, including traces.
  - **Filtering/Search**: Typed constructs for filter criteria—policy/user/group/dynamic group searches with well-documented semantics for AND/OR logic, summary/full result types, etc.
  - **Analysis/Overlay**: Policy overlap, intelligence, and diff result models for advanced analysis.
- **Value Prop to UI**: Uniform response shapes let any UI consumer (tab, filter panel, simulation view) access fields reliably, validate user input, and display specialized content without needing to decipher loose dicts or undocumented structures.

---

## 2. Central Data Repository (`logic/data_repo.py`)

- **Purpose**: `PolicyAnalysisRepository` encapsulates all data loading, parsing, filtering, and search logic for tenancy, identity, and policy analysis.
- **Initialization / Data Load**:
  - Loads all compartments, policies, users, groups, dynamic groups from OCI or offline sources.
  - Recursively parses the entire policy document tree, assigning fields/metadata per models.py.
  - Caches and indexes canonical objects in in-memory lists: policies, statements, users, groups, etc.
- **Filtering/Search**:
  - Provides public filter methods (`filter_policy_statements`, `filter_groups`, `filter_users`, etc.) that accept filter/search criteria modeled in models.py.
  - Resolves fuzzy-to-exact searches (auto-expands group/user/dg queries), always returning lists of model-conformant results.
  - Handles compound search logic: OR within fields, AND across fields; summary/full discriminated unions, etc.
- **Parsing and Normalization**:
  - All parsing, normalization, and validation of statements ("allow/deny/define/admit/endorse") happens centrally, with outputs strictly conforming to the canonical models.
  - Statement normalization, subject resolution, and policy overlap/risk analysis are run post-load and attached to the relevant output objects.
- **Caching, Import/Export**:
  - Loads/saves cached tenancy analysis using JSON/CSV; ensures all persisted data matches the defined models.
  - Supports comparison/diff, offline analysis from compliance output, and easy reload for UI experimentation or backup.

---

## 3. How the Data Model and Repository Serve UI and Tools

- **Separation of Concern**: UI components/tab modules never work directly with OCI raw REST/SDK structures. Instead, they exclusively interact with the repo’s well-typed objects/lists—displaying, sorting, and filtering using field names and types guaranteed by models.py.
- **Stable, Documented API**: All returned objects are self-documenting (with types and field meanings), enabling fast UI dev, strong autocomplete, and robust static/type checks even as the codebase grows.
- **Predictable Output**: Filtering and analysis requests always return predictable content—if a UI requests user search or policy statement list, it gets exactly the matching TypedDict(s), never "fuzzy" or inconsistent structures.
- **Advanced Flows**: Simulation, policy overlap detection, import/export, and bulk analytics all use and return objects that trace directly to models.py, enabling advanced visualizations and workflows with minimal glue code.

---

## 4. Implementation References

- Data Models: [`src/oci_policy_analysis/common/models.py`](../../../src/oci_policy_analysis/common/models.py)
- Repository/Loader: [`src/oci_policy_analysis/logic/data_repo.py`](../../../src/oci_policy_analysis/logic/data_repo.py)

---

**Summary:**  
This architecture delivers clean separation and strong typing for every major object or data flow in policy analysis. UI layers and tools can request, consume, and display data with full confidence in structure and meaning, independent of raw SDK formats or backend changes.