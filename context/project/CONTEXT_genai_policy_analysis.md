# GenAI/Large Language Models (LLMs) for Advanced OCI Policy Analysis

## 1. Current State

- "AI Assist" (ai_repo.py) supports LLM-driven *analysis* of a single policy statement using the selected OCI GenAI model and tailored prompt.
- All existing *simplification*, *consolidation*, and *overlap* logic is rule-based, utilizing Python strategies in the consolidation/intelligence engine.

---

## 2. GenAI/LLM Value-Add Scenarios

### a. Simplification

**Goal:** Rewrite multiple policy statements for clarity, conciseness, and minimalism, preserving intent.

**LLM Role:** Transform verbose/redundant language into simpler forms, clarify complex where clauses, and remove unnecessary logic.

**Implementation Strategy:** 
- Extend ai_repo.py with a method to receive a list of statements plus optional context (e.g., compartment JSON/tree).
- Prompt LLM for "minimum equivalent set"—rewriting for clarity and removing redundant logic.

### b. Consolidation & Combination

**Goal:** Merge statements with similar targets or where clauses into fewer, equivalent statements.

**LLM Role:** Reduce a group of narrowly overlapping policies into the minimal form, considering scope and intent.

**Implementation Strategy:** 
- Input a full statement list plus compartment context.
- Prompt: _"Given these OCI IAM policy statements and compartment hierarchy, provide a minimal consolidated version, combining scopes and where clauses as possible."_

### c. Overlap Detection

**Goal:** Identify, flag, and suggest removal or merger of redundant or overlapping statements.

**LLM Role:** Highlight statements with duplicative/overlapping permissions and provide rewrite proposals.

**Implementation Strategy:** 
- Input all statements plus policy/compartment context.
- Prompt for overlap annotation: _"Identify all pairs/groups in this policy list that grant overlapping permissions. Suggest how to remove redundancy."_

---

## 3. Recommended LLMs and Prompting Strategies

- **LLM Requirements:**
  - Fluent in English, excellent summarization and reasoning, can process list logic and semi-structured DSLs.
- **Recommended Models:**
  1. **OCI GenAI Foundation Models** (preferred for secure enterprise use).
  2. **General-Purpose LLMs:** OpenAI GPT-4, Claude, Llama-3-70B (if available).
  3. **Fine-tuned Domain Models:** Ideal but not required—custom prompts with general models are effective.

- **Prompt Engineering Patterns:**
  - Always include multiple statements plus context; present compartment hierarchy visually/textually.
  - System prompt: _"You are an expert in OCI IAM policy design. Rewrite for maximum simplicity and minimalism, without losing original permissions."_
  - For overlap/consolidation: ask for tabular or clearly formatted outputs.

**Example Consolidation Prompt:**
```
System: You are an expert in OCI IAM policy design.
User: Here are several OCI IAM policy statements. The compartment hierarchy is:

(compartment tree pasted here)

Please review these statements and rewrite them as the fewest unique statements granting the same permissions. Combine where clauses where possible, and explain your logic below. Do not remove valid permissions.
(statements pasted here)
```

- **Security/Workflow Consideration:** All LLM-generated outputs should be presented as "suggestions" for human review, not immediately auto-applied.

---

## 4. Roadmap/Integration Approach

- Extend ai_repo.py for multi-statement/policy-batch LLM prompts.
- Prototype and refine prompt templates for simplification, consolidation, and overlap detection.
- Wire up UI/engine to allow users to select LLM-assisted consolidation as an option.
- Human confirmation required before applying any LLM-suggested policy changes.
- Evaluate output against real policies and tune prompt quality iteratively.

---

## 5. Summary Task List

- Implement batch analysis/suggestion calls in ai_repo.py.
- Develop, tune, and validate prompt patterns for the target use cases.
- Integrate LLM-driven logic as an optional pathway in the consolidation UI/engine.
- Test with real and synthetic policy sets, validate for security and correctness.

---

*This context doc was generated on 2026-03-12 as part of ongoing GenAI strategy discussion for OCI Policy Analysis.*