# GrowthEvo · Agent Operating System & Recursive Evolution

GrowthEvo puts two capabilities at the front of the product:

1. **Agent Operating System** — understand a goal, inspect first-party workspace state, choose a typed capability, execute it, observe the real result, and continue until finished or gated.
2. **Evidence-gated recursive evolution** — learn from actual operator traces; propose a bounded change to the operating policy; independently evaluate it; require shadow, canary and an authorized operator to promote it; use the promoted policy as the parent of the next candidate.

Causal evidence, consent, budget and the legal action gate are **not** evolvable targets. No product-generation labels are used.

## Interactive Agent OS cockpit and evidence-ready Evolution Lab

The Agent OS navigation now opens a dedicated three-pane Nightfall workspace:
a browser-session conversation list, live tool-composer/trace panel, and an
operating-context sidebar. The conversation list is **browser-memory-only** and
does not imply durable chat threads or automatic cross-turn memory. The same
existing `POST /api/agent/run` and `POST /api/agent/plan` handlers, consent
checkbox, cancellation and failure behavior power the expanded workspace.

`ui.control` adds **strictly allowlisted first-party UI intentions**:
`open_search`, `open_date_filter`, `open_channel_filter`, and
`focus_campaign_name`. A prior workspace observation is mandatory. The
server emits `ui_pending` and `awaiting_ui_confirmation`; it cannot claim the
browser changed until the client performs and verifies the actual action.
The browser verifies a visible menu, focused input, or matching target state
and displays the local confirmation separately. This is not unrestricted DOM,
browser scripting, or cross-site computer use. Page navigation still uses the
approved route list; Campaign drafts still require user consent and server
verification.

The Evolution Lab now reads `GET /api/evolution/readiness` for **genuine**
minimum-trace counts and status, and operators may trigger
`POST /api/evolution/analyze` to examine their process-local real traces for
eligible bounded policy candidates. The endpoint fails on synthetic Demo
data. Running analysis cannot invent evaluations or promote candidates;
independent offline replay, production shadow/canary attestation and trusted
approval remain separate gates. No live production self-evolving code is
claimed. Model-unavailable workspaces honestly show insufficient traces.

## Implemented execution surface

The live browser sidecar defaults to **执行模式**. It calls POST /api/agent/run, which has a genuine bounded tool-use loop. POST /api/agent/plan remains available as the conservative strategy-only mode.

| Capability | Backend operation | Authority |
| --- | --- | --- |
| Observe the workspace | workspace.read | Read-only, scoped section allowlist |
| Navigate the first-party product | page.navigate | Returns a validated route to the browser UI |
| Create a campaign draft | campaign.draft | User must explicitly enable draft writes; workspace must be read first |
| Request human approval | approval.review | Interrupts the run; it never approves |
| Unrecognized paths or raw code | none | Rejected |

The browser UI changes routes after the server returns an approved navigation target. This is **not** screenshot/coordinate-based desktop control; integrating a sandboxed computer-use driver for external sites remains a distinct future task. Existing application routes remain usable through the original controls.

Model responses are strict structured proposals with a single tool choice and JSON-encoded arguments. The server, not the model, validates the final arguments. Each run has a bounded step budget, duplicate-call detection, redacted tool-argument hashes, and a real stop status. Provider failure never turns into a claim of successful execution. Campaign writes create only a **Draft**; launch/send and approval actions are intentionally not in the model's executable capability set.

Live execution requires a configured, pinned model route. Demo mode has no external model and cannot simulate an autonomous run as real. Traces are currently bounded **process-local** data, not a cross-replica production audit ledger.

### API example

GET /api/agent/tools lists the capabilities. A signed-in operator can request:

~~~json
{
  "goal": "检查增长机会并导航到实验页面",
  "allow_draft_writes": false,
  "max_steps": 6
}
~~~

Send it to POST /api/agent/run. The response contains a concrete status (completed, needs_approval, needs_consent, blocked, provider_failure, step_limit, or model_unavailable), verified tool events and an optional first-party navigation route.

GET /api/harness/runs reports genuine operator traces in live API mode. Reference fixtures remain isolated to demo mode.

## Recursion without unverified self-promotion

growthevo/agent_os/evolution.py provides an isolated archive of operator policies and descendant candidates.

- **Observation:** at least eight actual tool-run traces are needed before proposing a change. Static demonstration rows are excluded.
- **Mutation:** only the bounded step budget or a scoped first-read preference can change. Metrics, permissions, safety gates, and tool implementations remain immutable.
- **Independent evaluation:** a trusted caller supplies an actual held-out evaluator, with baseline/candidate task success, safety violations, cost, sample size and evidence identity. Inadequate or regressive evidence rejects a candidate.
- **Promotion:** a separate trusted operator must attest to shadow/canary success and explicitly authorize promotion. The model has no promotion endpoint.
- **Recursive parentage:** the accepted policy becomes the active policy and influences subsequent operator requests; the next mined candidate points to that policy's fingerprint.

A simulation unit test verifies this succession. **There is not yet an automatic production held-out runner, cryptographically verified promotion evidence, persistent cross-replica archive, or autonomous code-editing agent.** The built-in evaluate / promote methods are interfaces for independent trusted evaluation and promotion; supplying arbitrary Boolean flags is not proof of production performance. These steps must not be silently bypassed or marketed as completed production self-improvement.

This deliberately separates **proven policy improvement**, **candidate discovery**, and **open-ended self-modification**. The last is a research direction requiring sandboxing, benchmark hygiene and external oversight.

## Design lineage and what we reuse

| Reference | Practice adopted |
| --- | --- |
| [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/running-agents) | Model / tool / observation loop, bounded stop conditions and tracing |
| [Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents) | Simple composable tool interfaces and environmental ground truth |
| [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview) | Explicit tool authority, state, controlled execution and approval boundaries |
| [Google ADK Tool Confirmation](https://adk.dev/tools-custom/confirmation/) | Pause for a person before effectful high-risk operations |
| [Reflexion — NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html) | Use execution feedback and failures as future improvement signals |
| [SWE-agent — NeurIPS 2024](https://proceedings.nips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html) | Design interfaces specifically for an agent, not arbitrary UI scripting |
| [DSPy — ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f1cf02ce09757f57c3b93c0db83181e0-Abstract-Conference.html) | Optimize declared model/agent programs against measured tasks |
| [AlphaEvolve — Google DeepMind](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) | Candidate archive, verifier-driven selection and empirical improvement |
| [Darwin Gödel Machine — preprint](https://arxiv.org/abs/2505.22954) | Experimental recursive code mutation; **not** a production-ready guarantee |

These are architectural references, not claims that this repository reproduces their experimental results.

## Nonblocking recursive evaluation

The EvolutionAuthority uses a three-stage critical section for held-out evaluations: **claim candidate and snapshot the active policy → release the operator lock while an independent evaluator runs → reacquire the lock to validate lineage and record evidence**. This prevents multi-task replay from blocking live operator policy reads. Competing evaluations of the same candidate are rejected; evaluator failures release the claim without manufacturing measurements. If an independently promoted policy replaces the parent while replay is running, the old candidate is marked `stale_evaluation` and cannot be promoted.

This is in-process concurrency safety, not durable distributed ownership. Multiple replicas still require persistent compare-and-swap claims and external evidence verification before production promotion.

## Offline paired replay harness

The built-in **PairedReplayEvaluator** in `growthevo/agent_os/benchmark.py` now runs the same locked task manifest twice through the actual `GrowthOperator` loop, using a fresh isolated model and tools for each task and candidate. It verifies actual first-party workspace observations and navigation intents, and counts blocked operations as safety failures. A model-generated final message alone does **not** pass an evaluation.

The evaluator returns normalized task completion, safety violations, tool-call cost proxy, sample count and a SHA-256 suite fingerprint. It requires at least 30 distinct cases and is accepted by `EvolutionAuthority.evaluate` without writing a second promotion implementation.

**Boundaries:** This is an offline paired replay, not an online causal lift measurement, statistically conclusive randomized canary, or independent attestation of a deployed browser action. The manifest and model factory must be kept outside the candidate's control, and the evaluator itself must be independently provisioned. The model cannot promote its own candidate.

**Desktop and mobile product navigation now starts with Agent Operating System and Evolution Lab**. The Agent remains a first-party typed tool user; for arbitrary GUI operations follow [OpenAI Computer use](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use) or [Anthropic Computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) with an isolated browser, screenshot feedback, domain consent, and independent observation of effects. Do not add unrestricted DOM/JavaScript execution to this business application.

**Microsoft's durable workflows and human-in-the-loop checkpoints** demonstrate the next production step: persistent, tenant-isolated checkpoints and resumable authorization barriers rather than only an in-memory trace deque. See [Agent Framework HITL](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop) and [Durable Task Extension](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-agents-microsoft-agent-framework).

## Required gates before production claims

The next execution improvements are a durable, tenant-isolated run/checkpoint ledger; constrained session continuations; domain-specific tool adapters for every operational page; replayed independent task suites; randomized shadow/canary comparisons and automatic rollback; and an authenticated, auditable policy promotion service using signed evidence. Every claimed success should identify the exact task, observed side effect, independent evaluation set and policy fingerprint.

The next recursive research layer can use sandboxed code changes and tree-structured candidate search. Candidate programs must be executed in isolated workers with restricted network/secrets, replayed benchmark tasks, a locked holdout, provenance and operator approval. Never grant an evolving candidate the ability to rewrite its own legal gate, evidence verifier, permissions, or promotion authority.

## Running tests

~~~bash
python -m pytest tests/test_agent_operating_system.py -q
~~~

This suite uses fake model responses and local product state only. It validates the actual handler's contracts; it does **not** measure real-model task success or prove online causal lift.

## Browser receipts and an executable offline evaluation gate

A run now returns an ordered `ui_actions` list with the original `step_index`,
plus a run-specific `ui_confirmation_token`. Navigation, opening search/filter
menus and focusing the campaign field execute sequentially in the browser. A
successful model finish with pending UI actions is `awaiting_ui_confirmation`,
not a claim of completed browser work.

The browser posts `{token, receipts: [{step_index, status}]}` to
`POST /api/agent/runs/{run_id}/ui-confirmation`. A receipt must cover exactly the
issued steps in order. Tokens are not included in history reads; conflicting
replays are rejected, identical retries are idempotent, and evicting a run revokes
its token. History reads return detached copies. The final trace records
`ui_confirmed` or `ui_failed`, with `confirmation_source: browser_reported`.
A browser report is client-supplied evidence, **not independent verification** or
an input that can bypass the offline evaluation/promotion gates. Existing blocked,
step-limit and approval stop conditions remain unchanged by a receipt.

Candidate mining counts distinct run IDs from the **current policy fingerprint**.
At least eight eligible traces are needed. Old-policy samples, duplicate IDs and
records without a matching fingerprint do not count toward readiness.

An operator may provision a separate, sanitized, held-out manifest and configure:

~~~bash
GROWTHEVO_AGENT_BENCHMARK_PATH=/absolute/path/to/heldout.json
GROWTHEVO_AGENT_BENCHMARK_SHA256=<sha256-of-the-exact-file-bytes>
~~~

The JSON has exactly three fields:

- `suite_id`: a stable 12–128 character identifier.
- `tasks`: 30–200 distinct objects with `id`, `goal`, `expected_route` and
  `required_section`. Routes and sections must use the existing allowlists.
- `workspace`: recorded, sanitized snapshots for all ten sections: `dashboard`,
  `opportunities`, `campaigns`, `experiments`, `approvals`, `evidence`, `actions`,
  `decisions`, `harness` and `evolution`.

The file is limited to 1 MB. A missing or mismatched digest makes a configured
live runtime fail startup; Demo mode does not open the file. Keep held-out goals
and snapshots outside candidate generation and remove personal data before
provisioning. Pinning a digest proves file identity, not data independence.

`GET /api/evolution/readiness` reports `evaluation_available`, the suite identifier
and digest. When configured with an active model, the product enables
`POST /api/evolution/candidates/{candidate_id}/evaluate`. The client cannot supply
an evaluator or measurements. A fresh provider pool runs the baseline and proposal
against isolated copies of the locked workspace on a separate thread/event loop;
live campaigns cannot be mutated. The run has a five-minute measurement deadline,
closes its provider clients, and releases a failed evaluation claim for retry.
Provider failures are not converted into negative task scores or fake evidence.

The product shows the measured baseline/candidate contract pass rates, violations,
sample count and `replay:<full-manifest-digest>` evidence ID. These measurements
check **offline tool/route contracts**, not rendered browser effects or customer
outcomes. Passing only advances to `awaiting_shadow_canary`; there is no public
promotion endpoint. An evaluation in progress remains visible on refresh.

Traces, confirmation tokens, candidates and active policies remain bounded or
process-local. A service restart loses this state, and multiple replicas do not
share evaluation ownership. This change does not provide durable task recovery,
tenant-isolated history, signed promotion evidence or autonomous source editing.

~~~bash
python -m pytest tests/test_agent_operating_system.py tests/test_agent_ui_receipts.py tests/test_agent_replay_manifest.py
~~~
