# RET-C2-589 — Retail Part-Time Resume Screening Agent

> **Category**: Cat 2 (specific use-case orchestration)
> **Industry**: Retail

## Overview

RET-C2-589 orchestrates a 3-step resume screening pipeline for retail part-time
hiring: parses Japanese resumes (履歴書/職務経歴書) via Azure OpenAI extraction,
scores candidates against configurable job criteria (certifications, shift availability,
JLPT level, 育成就労法 2028 eligibility), and produces a PII-redacted RankedShortlistReport
with a top-3 interview shortlist for HR review.

**Key compliance constraints:**
- APPI (個人情報保護法): resume text is PII-masked before LLM submission and all output is redacted
- 育成就労法 2028: eligibility scoring via configurable pluggable rules module
- Bias mitigation: protected attributes (nationality, age, gender) excluded from scoring

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/` for the design specification and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
