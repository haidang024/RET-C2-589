# Test Specification

## Test Strategy
- Coverage target: 85%+
- Test types: Unit + Integration + Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | No Pydantic/dataclass in state schema | Implemented |
| TC-02 | SecurityViolationError on invalid input | PreProcessNode rejects injection, oversized, and missing-field payloads | Implemented |
| TC-03 | No JWT/Credential in State | CI credential scan returns 0 violations | Implemented |
| TC-04 | InvocationContext constructed only via `from_state()` inside nodes | No direct node-level construction; standalone entry-point adapter exempt | Implemented |
| TC-05 | S-4 lifecycle duplication check | execute() does not emit node_start/node_complete | Implemented |
| TC-06 | `_security_gate_input()` not overridden | Only `_extra_security_gate_input()` used in PreProcessNode, ResumeParseNode | Implemented |
| TC-07 | `_security_gate_output()` not overridden | Only `_extra_security_gate_output()` used in all nodes | Implemented |
| TC-08 | `required_trust_level` enforced via `node(state)` | Insufficient trust is refused before `execute()` | Implemented |
| TC-09 | `_extra_security_gate_input()` non-trivial | PreProcessNode: size limit, injection, batch shape; ResumeParseNode: path traversal, batch type | Implemented |
| TC-10 | `_extra_security_gate_output()` non-trivial | ResumeParseNode: PII field scan; CriteriaScoreNode: PII field scan; RankingNode: unredacted PII scan; PostProcessNode: credential pattern scan | Implemented |
| TC-11 | Domain `emit_trace_event()` in execute() | ≥1 domain event per node on every invocation path | Implemented |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every node execute path | No silent failures | Implemented |
| PB-2 | State serialization | Post-invoke State fields are primitives/JSON-safe only | No Pydantic/dataclass | Implemented |
| PB-3 | Template → Azure OpenAI | Invocation-secret construction and PII-masked request path | Azure call is invocation-scoped; fallback is non-fatal | Implemented |
| PB-4 | Import isolation | No Level-0 imports (`agenticstar*`, `mediator*`) in src/ | AST scan: 0 violations | Implemented |
| PB-5 | Checkpoint safety *(conditional)* | When checkpointing and framework ingress hooks are enabled, inspect checkpoint, metadata, and pending writes for raw ingress | Auto-waived — checkpointing disabled | Auto-waived |
| PB-6 | Invoke execution order | `__call__()`: S-1 → `node_start` → S-2 → `execute` → S-3 → `node_complete` | Order verified for every concrete node | Implemented |
| PB-7 | HITL interrupt propagation *(conditional)* | Required only when `config/config.yaml` sets `hitl.enabled: true` | Auto-waived — non-HITL | Auto-waived |

> PB-1 through PB-4 and PB-6 are mandatory. PB-5 is auto-waived while
> checkpointing is disabled. PB-7 is auto-waived while HITL is disabled.

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Single resume happy path | 1 resume with 食品衛生責任者 cert, matching shift, JLPT N3 | ranked_shortlist_report with 1 ranked candidate; pass_mandatory=True | Implemented |
| BL-02 | Batch of 20 resumes | 20 resumes with mixed qualifications | ranked_list length ≤ 20; shortlist_top3 length ≤ 3 | Implemented |
| BL-03 | Japanese 履歴書 PDF format | resume with 食品衛生責任者 in certifications text | ResumeParseNode extracts certification; CriteriaScoreNode cert flag = True | Implemented |
| BL-04 | Mandatory criteria hard-gate | Resume missing required certification | pass_mandatory=False; excluded from ranked_list | Implemented |
| BL-05 | 食品衛生責任者 cert present | certification list includes 食品衛生責任者 | cert_flags["食品衛生責任者"] = True; mandatory gate passes | Implemented |
| BL-06 | 食品衛生責任者 cert absent | certification list does not include 食品衛生責任者 | cert_flags["食品衛生責任者"] = False; mandatory gate fails; excluded | Implemented |
| BL-07 | 育成就労法 eligibility flag | No rules module configured | ikusei_shurou_eligible=False; ikusei_shurou_interim=True (safe default) | Implemented |
| BL-08 | Shift overlap — exact match | Candidate available Mon-Fri; job requires Mon-Fri | shift_overlap_pct = 1.0 | Implemented |
| BL-09 | Shift overlap — partial | Candidate available Mon-Wed; job requires Mon-Fri | shift_overlap_pct = 0.6 | Implemented |
| BL-10 | Shift overlap — no match | Candidate available Sat-Sun only; job requires Mon-Fri | shift_overlap_pct = 0.0; does not pass shift preferred criterion | Implemented |
| BL-11 | APPI PII gate — no PII in logs | Resume with known PII (name, address, DOB) | parsed_resumes output: name/address/date_of_birth = "[REDACTED]" | Implemented |
| BL-12 | Empty batch edge case | resume_batch = [] | parsed_resumes = []; ranked_list = []; shortlist_top3 = [] | Implemented |
| BL-13 | All-fail edge case | All resumes missing required certification | ranked_list = []; shortlist_top3 = []; excluded count = total | Implemented |
| BL-14 | JLPT minimum level gate | min_jlpt_level=3; candidate has N5 | jlpt_match=False; mandatory gate fails if JLPT is required | Implemented |
| BL-15 | JLPT match pass | min_jlpt_level=3; candidate has N2 | jlpt_match=True; jlpt gate passes | Implemented |

## Test Execution Summary
- Execution date: 2026-08-18
- Total tests: See `tests/unit/`, `tests/integration/`, `tests/proof_of_boundary/`
- Pass: Pending CI run
- Coverage: Pending
