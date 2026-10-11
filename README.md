# Freya Autonomous Voice Agent Builder

[![Freya Voice AI](https://img.shields.io/badge/Platform-Freya%20Voice%20AI-blueviolet.svg)](https://staging-app.freyavoice.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: Benchmarked](https://img.shields.io/badge/Benchmark-100%25%20PASS-brightgreen.svg)]()

Autonomous meta-builder and dynamic workflow compiler developed for the **Freya Voice AI Hackathon** (*"Build the Builder"*).

The builder parses arbitrary, unseen banking collections briefs and tool OpenAPI 3.0 specifications, then compiles them into production-ready, ultra-low latency, multi-node conversational phone agent state machines deployed on the Freya Voice AI platform.

---

## 🚀 Key Highlights & Benchmark Performance

- **Brief A (Single-Product Collections):** **10/10 PASS** across the full evaluation suite (`PUB-01` to `PUB-10`).
- **Brief B (Multi-Product Collections):** **3/3 PASS** (`PUB-11`, `PUB-12`, `PUB-13`), completed in **47 seconds** with **0 customer hang-ups** and **3.0s median turn latency**.
- **Execution Speed:** Complete autonomous compilation, schema validation, and remote platform deployment in **< 3 seconds** (well within the hackathon's 30-minute cap).
- **Zero Domain Hardcoding:** Dynamically extracts dates, bank holidays, identity questions, loan bands, deadline calculation rules, and outcome hierarchies directly from input briefs and OpenAPI schemas.
- **Local Autonomy:** Runs entirely self-contained without requiring Anthropic API keys or proprietary local agent CLIs.

---

## 🏛️ Architecture & System Design

```
                     ┌───────────────────────────────┐
                     │   Unseen Bank Brief (.md)     │
                     │  OpenAPI 3.0 Spec (tools.json)│
                     └───────────────┬───────────────┘
                                     │
                                     ▼
 ┌───────────────────────────────────────────────────────────────────────┐
 │                       Smart Compiler Pipeline                         │
 │                                                                       │
 │  ┌─────────────────────────┐          ┌────────────────────────────┐  │
 │  │   Brief Policy Parser   │          │   OpenAPI Tool Synthesizer │  │
 │  │  - Bank holidays regex  │          │  - __function__:api_call   │  │
 │  │  - Deadline calculation │          │  - Lifecycle configurations│  │
 │  │  - Identity requirements│          │  - Error handling hooks    │  │
 │  │  - Multi-product rules  │          │  - Outcome/reason pruning  │  │
 │  └────────────┬────────────┘          └─────────────┬──────────────┘  │
 │               │                                     │                 │
 │               └──────────────────┬──────────────────┘                 │
 │                                  ▼                                    │
 │                    ┌───────────────────────────┐                      │
 │                    │ Workflow Prompt Generator │                      │
 │                    │ - Identity Node (Strict)  │                      │
 │                    │ - Collection Node (State) │                      │
 │                    │ - Latency-budgeted Prompts│                      │
 │                    └─────────────┬─────────────┘                      │
 │                                  │                                    │
 │                                  ▼                                    │
 │                    ┌───────────────────────────┐                      │
 │                    │ Offline Safety Validator  │                      │
 │                    │ - Node transitions & DAG  │                      │
 │                    │ - Tool bindings & hooks   │                      │
 │                    │ - Silence timeout safety  │                      │
 │                    └───────────────────────────┘                      │
 └──────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │                 Freya Platform & Auditing               │
       │  - Remote publish & activation via freya.save_workflow  │
       │  - Workflow JSON artifact export (Rule 75)              │
       │  - Structured audit trace logs (Rule 91)                │
       └─────────────────────────────────────────────────────────┘
```

---

## 🧩 Core Modules

| Module | Location | Description |
|---|---|---|
| **CLI Entry Point** | `kit/build-the-builder/builder/build.py` | Official competition CLI. Ingests briefs & specs, drives compilation, validates schemas, uploads, exports platform artifacts, and writes audit logs. |
| **Brief Parser** | `kit/build-the-builder/smart_builder/brief_parser.py` | Dynamically parses ISO holiday dates, deadline bands, attempts, outcome/reason tables, and multi-product flags. |
| **OpenAPI Parser** | `kit/build-the-builder/smart_builder/openapi_parser.py` | Converts OpenAPI paths to native Freya tool handlers with pre/post-execution hooks (e.g. 3-wrong-answer cap on `verify_identity`, reason pruning for `close_call`). |
| **Workflow Generator** | `kit/build-the-builder/smart_builder/generator.py` | Synthesizes compliant multi-node workflows (`identity` -> `collection`) with compact high-density prompts that eliminate KV-cache latency. |
| **Integrity Validator** | `kit/build-the-builder/smart_builder/validator.py` | Offline safety and schema validator verifying graph reachability, lifecycle hooks, tool bindings, and prompt character budgets. |
| **Freya API Client** | `kit/build-the-builder/freya.py` | Resilient platform client featuring exponential backoff retries for transient 429/502/503/504 gateway responses. |

---

## 🛠️ Getting Started

### 1. Prerequisites
- Python 3.10+ (tested with Python 3.11)
- Freya Workspace API Key (`FREYA_API_KEY`)

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/emredermann/freya-agent-builder.git
cd freya-agent-builder

# Set up your environment variables
cd kit/build-the-builder
cp env.example env.sh
# Edit env.sh with your FREYA_API_KEY and custom FREYA_BANK_TEAM_KEY
source env.sh
```

### 3. Building Agents

To build an agent from a single brief:
```bash
python builder/build.py briefs/brief-a.md tools/openapi.json
```

To build a multi-product agent (combining Brief A and Brief B):
```bash
python builder/build.py briefs/brief-a.md briefs/brief-b.md tools/openapi.json
```

### 4. Running Diagnostic Benchmarks
```bash
# Evaluate Brief A test cases (PUB-01 to PUB-10)
python tools/run_cases.py <AGENT_ID> --brief A --reps 1

# Evaluate Brief B multi-product test cases (PUB-11 to PUB-13)
python tools/run_cases.py <AGENT_ID> --brief B --reps 3
```

---

## 📋 Hackathon Submission Compliance Checklist

- [x] **Sub-30-Minute Execution:** Runs in ~2-3 seconds per brief.
- [x] **Zero Hardcoded Domain Logic:** All dates, bank names, holiday calendars, deadlines, and identity fields are extracted dynamically.
- [x] **Offline Validation:** Automated pre-upload validation prevents invalid schemas and runtime silence timeouts.
- [x] **Rule 75 Artifact Export:** Live workflow JSON is fetched and exported directly from Freya to `out/<slot>.workflow.json`.
- [x] **Rule 91 Audit Trace Logging:** Comprehensive execution traces with timestamps, synthesized nodes, IDs, and validation results written to `traces/<slot>.log`.
- [x] **Secrets Sanitization:** Complete `.gitignore` policy strictly excluding `.env`, `env.sh`, virtual environments, and API tokens.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
