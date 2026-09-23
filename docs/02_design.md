# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `RetailPartTimeResumeScreeningAgent` (`Graph`)
- **L1 Base**: AgentBaseGraph
- **Three-Layer Separation**:
  - State: flat `State(AgentState)` with JSON-serializable fields only
  - Node: `FunctionNode` implementations with `execute(self, state: dict) -> dict`
  - Graph: outer `Graph(AgentBaseGraph)` + inner `DomainWorkflowGraph(BaseGraph)` via `ResumeScreeningGraphNode`
  - LLM injection: `server.py config["llm"] → ResumeScreeningGraphNode._llm → DomainWorkflowGraph._llm → ResumeParseNode._llm`

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Framework bootstrap | — | default framework fields | InitializeNode (default) |
| pre_process | Validate resume batch payload; APPI S-2 input gate | user_input, resume_batch, job_criteria, job_id | validated_input, resume_batch, job_criteria, job_id, status | PreProcessNode(FunctionNode) |
| main | Execute 3-step resume screening workflow | resume_batch, job_criteria, job_id | parsed_resumes, scored_resumes, ranked_shortlist_report | ResumeScreeningGraphNode(GraphNode) |
| post_process | Format RankedShortlistReport; S-3 output gate | ranked_shortlist_report | formatted_output, status | PostProcessNode(FunctionNode) |
| finalize | Final response packaging | framework state | response envelope | FinalizeNode (default) |

### Data Flow

```text
START → initialize → pre_process → main → post_process → finalize → END
```

`main` subgraph topology:

```text
START → resume_parse → criteria_score → ranking → END
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| resume_batch | list | Raw resume items `{file_path, content_b64, content_text}` — APPI HIGH sensitivity | Yes |
| job_criteria | dict | Criteria config `{required, preferred, shift_requirements, min_jlpt_level, ikusei_shurou_rules_module, score_weights}` | Yes |
| job_id | str | Unique job requisition identifier | Yes |
| parsed_resumes | list | Structured ResumeRecord per candidate (PII-redacted after parse) — APPI HIGH | Yes (after parse) |
| scored_resumes | list | ScoredCandidate per candidate — no raw PII; candidate_id pseudonym — APPI MEDIUM | Yes (after score) |
| ranked_shortlist_report | dict \| None | RankedShortlistReport — PII-redacted, safe for caller — APPI LOW | Yes (after rank) |
| parse_error_count | int \| None | Number of resumes that failed parsing | No |
| score_error_count | int \| None | Number of candidates that failed scoring | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `InvocationContext.from_state(state)` only when a node
  needs caller context (never persisted in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (framework-managed)
- [ ] ConnectionPolicy (Azure transport is managed by the shared AgentCore client)
- [x] SecurityViolationError
- [x] S-2: `_extra_security_gate_input()` in `PreProcessNode` (payload size, injection, batch limits), `ResumeParseNode` (path traversal, batch shape)
- [x] S-3: `_extra_security_gate_output()` in `ResumeParseNode` (PII field scan on parsed_resumes), `CriteriaScoreNode` (PII field scan on scored_resumes), `RankingNode` (unredacted PII scan on report), `PostProcessNode` (credential pattern scan)
- [x] S-4: `emit_trace_event()` in every node execute path

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - All domain nodes are `FunctionNode` subclasses — `@final` gate runs automatically;
>   domain checks extend via `_extra_security_gate_input()` / `_extra_security_gate_output()`

### Composition Pattern

- **Pattern**: GraphNode (subgraph)
- **Composition target**: `DomainWorkflowGraph` (inner BaseGraph)
- **Error propagation strategy**: `propagate`

### Azure OpenAI Boundary

- `ResumeParseNode` masks detected PII before submitting resume text.
- Azure OpenAI is constructed from invocation-scoped secrets and never stored in State.
- Provider failure activates the deterministic heuristic parser.

## EU AI Act Art.13 Design-Time Evidence

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Assist Japan retail HR operators by parsing, scoring, and ranking part-time job applications against job-specific criteria. |
| System capabilities and limitations | Extracts resume fields, evaluates configured criteria, and returns a PII-redacted shortlist. It does not verify document authenticity, determine legal eligibility conclusively, or make a hiring decision. Local-LLM failure activates a lower-capability heuristic parser. |
| User-facing transparency information | Output identifies criterion-level scores, mandatory-gate results, exclusions, and the fact that the shortlist is advisory. PII is pseudonymized/redacted before output. |
| Human oversight mechanism | HR staff review the ranked shortlist and source application before interview or rejection decisions; protected attributes are excluded from scoring and the system has no authority to hire or reject. |

## Import Isolation Confirmation
- [x] Template does not import Level-0 `agenticstar` SDK namespaces
- [x] Import targets are `framework`, `shared`, and local `src` only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Deterministic 3-step pipeline; no autonomous planning required |
| Composition pattern | GraphNode (inner graph) | Flat single-node main | GraphNode | 3-step domain isolation enables independent node testing |
| LLM execution | Process-global client | Invocation-scoped Azure OpenAI | Invocation-scoped Azure OpenAI | Prevents cross-request credential/client leakage; PII is masked first |
| 育成就労法 rules | Hardcoded | Pluggable module | Pluggable module | Act not fully operative until 2028; rules will change; configurable avoids re-deployment |
| Bias mitigation | Exclude protected attributes at scoring | Post-hoc audit | Exclude at scoring | Prevents discriminatory scoring; simpler to audit and verify |
