# GrowthEvo Product Surface v0.2

This layer turns the research harness into a runnable product shell without weakening the causal and evidence boundaries already present in the repository.

## Implemented

- Responsive Growth OS: incremental KPI cockpit, Opportunity Map, Campaign Studio, experiments, approvals, Agent Harness, Evolution Lab, data plane and realtime decision console.
- Growth Agent sidecar that converts natural-language goals into typed claims (`FACT / ESTIMATE / HYPOTHESIS / IDEA`) and structured artifacts.
- Versioned FastAPI contract under `/api/v1/*`.
- Reference decision boundary with first-class `NO_TREATMENT`, action registry validation, consent/frequency/budget/context-freshness guards, idempotency and behavior propensity logging.
- Installable PWA and responsive phone layout.
- Expo/React Native companion for KPI, campaign health and evidence-aware approvals.

The realtime decision endpoint is intentionally marked `reference-contract`: it validates product semantics and the client contract but does not claim to replace the repository's locked CATE/OPE/policy stack. Production deployments should connect `score_actions()` to that stack.

## Architecture

```text
Desktop Web / PWA                 Expo Mobile
        \                            /
         +------- /api/v1/* --------+
                     |
                 FastAPI
                     |
       +-------------+--------------+
       |             |              |
   Agent Plane   Product Store  Decision Boundary
   typed plan    reference data registry + guards
       |                            |
       +-------- Causal Harness ----+
                 CATE / OPE /
                 Safe PI / Evidence
```

Durable side effects should run in a workflow engine rather than inside a long model request. Shadow, approval waits, retries, canary promotion and rollback remain explicit state transitions.

## Reuse decisions

- **FastAPI + Pydantic**: existing optional dependencies; retained for typed APIs.
- **OpenAI Agents SDK patterns**: tool schemas, guardrails, human-in-the-loop and trace/span semantics map directly to the Harness UI. Provider SDKs remain optional because GrowthEvo already supports multiple LLM providers.
- **Temporal / Dapr / Restate durability pattern**: recommended adapter boundary for long-running side-effect workflows; no one-shot model call is treated as a workflow engine.
- **OpenTelemetry-compatible tracing**: intended persistent observability format.
- **Warehouse-native experimentation patterns** from Statsig/GrowthBook: assignment, exposure, metric maturity, holdout and analysis remain separate objects.
- Existing GrowthEvo cross-fitted CATE, safe policy improvement, OPE, conformal verification, locked holdout and canary modules remain authoritative.

## 2025–2026 research reviewed

The product does not assume one universal memory substrate. Context and persistent memory are separated; memory requires provenance/scope/freshness/TTL; long-context remains a valid baseline.

- *EvoMemBench: Benchmarking Agent Memory from a Self-Evolving Perspective* (2026), arXiv:2605.18421.
- *Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers* (2026), arXiv:2603.07670.
- *Harness the Memory: A Holistic Evaluation of Memory Substrates in Memory Agents* (2026), arXiv:2608.15008.
- *MemBench: Towards More Comprehensive Evaluation on the Memory of LLM-based Agents* (2025), arXiv:2506.21605.

The resulting evolution policy is controlled: memory/prompt/skill/tool-routing candidates pass replay, harness evaluation, shadow and canary before promotion.

## API

```http
GET  /api/v1/dashboard
GET  /api/v1/opportunities
GET  /api/v1/campaigns
POST /api/v1/campaigns/draft
GET  /api/v1/experiments
GET  /api/v1/approvals
POST /api/v1/approvals/{id}/decision
GET  /api/v1/harness/runs
GET  /api/v1/evolution/candidates
POST /api/v1/agent/plan
GET  /api/v1/actions
POST /api/v1/decide
GET  /api/v1/decisions/recent
```

`/api/v1/decide` always returns a decision ID, chosen action, behavior propensity, policy version, evidence tier, expiry, guardrail snapshot and audit reasons.

## Run

```bash
pip install -e '.[web]'
growthevo-web
# http://127.0.0.1:8765
# http://127.0.0.1:8765/api/docs
```

Mobile:

```bash
cd apps/mobile
npm install
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```
