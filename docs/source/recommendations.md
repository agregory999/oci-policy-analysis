# Recommendations

The OCI Policy Analysis tool leverages a dedicated engine for generating actionable **recommendations** and **remediations** to guide users in securing and optimizing their OCI environment. This document outlines the strategies, logic, and display methodology for recommendations, and briefly introduces the concept of Policy Intelligence as it applies within the tool.

---

## Table of Contents

1. [Introduction](#introduction)
2. [How Recommendations Are Created](#how-recommendations-are-created)
   - Data Inputs
   - Analysis Strategies
   - Rule and Pattern-Based Generation
   - Use of Policy Intelligence
3. [Principles for Effective Recommendations](#principles-for-effective-recommendations)
4. [Displaying Recommendations to Users](#displaying-recommendations-to-users)
   - In the UI
   - Integration with MCP Tools and AI Features
5. [Policy Intelligence: Overview](#policy-intelligence-overview)
6. [Further Reading](#further-reading)

---

## Introduction

Modern OCI environments grow increasingly complex, making it challenging for administrators to maintain secure, auditable, and efficient policy configurations. The **Recommendations** feature in OCI Policy Analysis surfaces best-practice guidance, security alerts, cleanup opportunities, and actionable insights based on the current state of policies, users, groups, and compartments.

These recommendations allow administrators to:
- Detect misconfigurations and risky policies
- Identify unused or redundant identities and statements
- Clarify and explain policy effects, especially in complex environments
- Receive targeted advice to improve security posture and manage risk

---

## How Recommendations Are Created

Generating a meaningful recommendation involves several steps, drawing on the full capabilities of the underlying data model and analysis layers. The core strategy combines rule-based logic, cross-resource context, and Policy Intelligence (see below).

### Data Inputs

- **Policy Statements** (parsed, normalized, and enriched)
- **IAM Data** (users, groups, dynamic groups, their relationships)
- **Compartment Hierarchies**
- **Permissions/Resource Mappings** (reference data)
- **Policy Evaluation Results** (e.g., overlaps, effective paths, invalid/ambiguous statements)
- **Simulation Outcomes** (where applicable)

### Analysis Strategies

- **Rule-Based Detection:**  
  Pre-defined rules flag known best practice violations, such as overly-broad policies, dangling resources, or weak conditions. Rules are tuned to align with Oracle's security and compliance guidelines.

- **Pattern Recognition:**  
  Examines policy text and IAM relationships for risky or anomalous patterns—for example, duplicate grants or conflicting denies.

- **Historical Comparison:**  
  By comparing present and past states (see "Policy Comparison" features), recommendations can highlight recent changes, the introduction of new risks, or the effect of policy modifications.

- **AI-Driven Insights:**  
  If enabled, GenAI models can supplement recommendations with natural language explanations and custom suggestions based on policy semantics.

### Rule and Pattern-Based Generation

Typical categories of recommendations include:
- **Remediation:** Identify and propose fixes for risky, invalid, or deprecated policy statements.
- **Cleanup:** Suggest removal of unused users, groups, or policies to reduce surface area.
- **Optimization:** Recommend consolidating or clarifying overlapping/conflicting policies.
- **Security Alert:** Highlight dangerous permissions granted to broad or unintended subjects.
- **Compliance:** Detect gaps against standard frameworks (e.g., CIS, Oracle Security Best Practices).

Recommendations may be **automatically refreshed** when IAM or policy data changes, ensuring they always reflect the current OCI configuration.

### Use of Policy Intelligence

Policy Intelligence adds context and reasoning, going beyond static rules to address scenarios where the interplay of multiple data points determines risk or opportunity. For instance, a recommendation may use Policy Intelligence to explain why a particular group’s access is risky based on its actual effective permissions and observed usage.

---

## Principles for Effective Recommendations

Good recommendations are:
- **Contextual:** Tailored to the user's actual environment and policies
- **Actionable:** Provide clear, prescriptive advice, not just problem statements
- **Explainable:** Include sufficient context and rationale to inform decision-making
- **Prioritized:** Highlight high-risk or high-impact findings before lower priority hints
- **Non-intrusive:** Designed for easy review and dismissal if not desired

The tool ensures that for each recommendation, a concise message, the affected resource/policy, and the suggested action are clearly presented.

---

## Displaying Recommendations to Users

### In the User Interface

- **Recommendations Panel:**  
  A dedicated tab or panel summarizes all current recommendations, grouped by severity or type (e.g., Security, Cleanup, Optimization).
- **Contextual Badges/Markers:**  
  Inline indicators may appear next to policy statements or users in table views, alerting users to relevant recommendations while browsing.
- **Remediation Actions:**  
  Where available, quick actions or links are provided (e.g., "View Policy", "Simulate Impact", "Go to OCI Console") for immediate follow-up.

### Integration with MCP Tools and AI

- **MCP Resources:**  
  Recommendations are exposed via MCP, enabling other clients (like Claude or VSCode) to query and incorporate recommendations via structured tools.
- **AI Features:**  
  With GenAI enabled, explanations for complex recommendations and natural language "why/how" clarifications are made available.

---

## Policy Intelligence: Overview

**Policy Intelligence** in OCI Policy Analysis refers to the holistic, context-aware evaluation of OCI IAM policy environments, combining structured rule logic and advanced analysis across all identity, compartment, and permission data. It powers not just recommendations, but also simulations, effective permission calculations, and security reporting.

Policy Intelligence enables the following:
- Dynamic explanation of how and why a user or group receives certain permissions
- Detection of unintended overlaps, privilege escalation, or policy gaps
- Generation of tailored suggestions and insights aimed at risk mitigation and operational efficiency

By leveraging Policy Intelligence, recommendations become smarter and more relevant, guiding administrators toward concrete improvements and deeper understanding of complex policy effects.

---

## Further Reading

- [Overview](./overview.md)
- [Architecture](./architecture.md)
- [Simulation](./simulation.md)
- [MCP Server and Tools](./mcp.md)
- [Usage and UI Guide](./usage.md)
