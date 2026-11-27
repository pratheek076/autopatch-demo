# AutoPatch 🤖🔒

**Self-Healing CI/CD Agent with Formal Guardrails**

> An agentic AI system that autonomously detects, diagnoses, and patches CI/CD pipeline failures — with formal specification-based guardrails that block any patch violating mathematical invariants or policy rules before it can be merged.

---

## Architecture

```
GitHub Actions (failure)
        │
        ▼ webhook
  ┌─────────────┐
  │ Monitor     │  Fetches structured failure + logs from GitHub API
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │ Diagnosis   │  LLM classifies: flaky_test | regression | dependency | infra
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   Patch     │  LLM generates minimal candidate fix
  └──────┬──────┘
         │
  ╔══════▼══════════════════════╗
  ║   Formal Guardrail Layer    ║
  ║  Z3 (invariants) + OPA      ║  ← This is the novel part
  ║  (policy rules)             ║
  ╚══════╤══════════════════════╝
         │
    ┌────┴────┐
  PASS      FAIL
    │          │
  ┌─▼──┐   ┌──▼──────────────┐
  │ PR │   │ GitHub Issue     │
  │    │   │ "Blocked: why"   │
  └────┘   └─────────────────┘
```

## Key Innovation: Formal Guardrails

The agent never autonomously merges code without passing:

| Check | Tool | What it verifies |
|---|---|---|
| Invariant 1 | Z3 | Patch ≤ 150 lines |
| Invariant 2 | Z3 | Coverage drop ≤ 2% |
| Invariant 3 | Z3 | No secrets introduced |
| Invariant 4 | Z3 | No test disabling |
| Policy 1–5 | OPA/Rego | File scope, secrets, size, coverage |

The **YAML agent contracts** (`specs/agents/*.yaml`) are the single source of truth — Z3 and OPA rules are derived from them at runtime.

## Project Structure

```
autopatch/
├── src/autopatch/
│   ├── main.py                 # FastAPI webhook receiver
│   ├── agents/
│   │   ├── graph.py            # LangGraph multi-agent pipeline
│   │   ├── monitor.py          # Fetches pipeline failure info
│   │   ├── diagnosis.py        # Classifies failure type
│   │   ├── patch.py            # Generates candidate fix
│   │   └── verifier.py         # Creates branch + opens PR
│   ├── guardrails/
│   │   ├── spec_loader.py      # Reads YAML contracts
│   │   ├── z3_checker.py       # SMT-based invariant checking
│   │   └── opa_checker.py      # OPA policy evaluation
│   ├── integrations/
│   │   └── github.py           # GitHub API client
│   └── models/
│       └── schemas.py          # Pydantic data models
├── specs/
│   ├── agents/                 # YAML behavioral contracts (requirements)
│   │   ├── monitor_agent.yaml
│   │   ├── diagnosis_agent.yaml
│   │   └── patch_agent.yaml
│   ├── policies/               # OPA/Rego pipeline safety rules
│   │   └── pipeline_safety.rego
│   └── invariants/             # Z3 invariant reference specs
│       └── patch_properties.py
├── tests/
│   └── test_guardrails.py      # Tests for Z3 + OPA checkers
├── docker-compose.yml          # FastAPI + Redis + OPA
└── .env.example
```

## Quick Start

```bash
# 1. Clone and set up environment
git clone <your-repo>
cd autopatch
cp .env.example .env
# Edit .env with your GOOGLE_API_KEY and GITHUB_TOKEN

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run with Docker Compose (includes Redis + OPA)
docker compose up

# 4. Run guardrail tests (no API keys needed)
pytest tests/test_guardrails.py -v

# 5. API docs available at:
#    http://localhost:8000/docs
```

### Jenkins local runner

The Compose-managed Jenkins image includes Python 3.12, which the `Jenkinsfile`
uses to create its virtual environment. Build and start it with:

```bash
docker compose up -d --build jenkins
```

Rebuild the Jenkins image after changing `Dockerfile.jenkins`. For Jenkins
agents managed outside this Compose setup, install Python 3.12 or newer on the
agent that runs the pipeline.

If AutoPatch runs directly on your host while Jenkins runs in Docker, bind it
to an address reachable from the container and set `AUTOPATCH_WEBHOOK_URL` in
Jenkins to `http://host.docker.internal:8000`:

```bash
uvicorn src.autopatch.main:app --host 0.0.0.0 --port 8000
```

If both services run through Compose, Jenkins can instead use
`http://autopatch:8000`.

## Tech Stack

| Component | Technology |
|---|---|
| Agent Framework | LangGraph |
| LLM | Gemini 1.5 (Flash for diagnosis, Pro for patching) |
| Formal Verification | Z3 SMT Solver + OPA/Rego |
| Requirement Contracts | YAML Agent Contracts |
| Backend | FastAPI |
| State/Queue | Redis + Celery |
| CI/CD Target | GitHub Actions |
| Deployment | Docker Compose |

## Milestones

- [ ] Week 1–2: Monitor Agent + GitHub webhook integration
- [ ] Week 3: Diagnosis Agent (LLM classification)
- [ ] Week 4: Patch Agent (LLM fix generation)
- [ ] Week 5: **Formal Guardrail Layer** (Z3 + OPA)
- [ ] Week 6: Verifier Agent + end-to-end loop
- [ ] Week 7–8: Dashboard + write-up

---

*Built by Pratheek P — combining test automation engineering experience with formal methods research.*
