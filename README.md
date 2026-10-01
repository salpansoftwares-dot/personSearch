# PersonSearch: Professional Profile Discovery Platform

> **A sourced, evidence-first platform that discovers and assembles professional and public-role information from fragmented public sources with verifiable provenance.**

Every output is a set of claims tied to a verified source URL, an exact verbatim evidence excerpt, a retrieval timestamp, and a calibrated confidence score. The platform strictly reports **"possible match"** and **"sources indicate"** — never a definitive identity.

---

## 🌟 Core Design Principles

1. **Provenance First:** No claim exists without an authoritative source URL, a verbatim quote excerpt, retrieval date, and confidence level.
2. **LLM Proposes, Deterministic Code Decides:** AI models extract structured claims from text, but all identity decisions and merges are made by auditable, deterministic scoring algorithms.
3. **Default to Unmerged:** A false merge (attributing one individual's employer or history to another) is worse than a missed link. Ambiguous profiles with matching names are displayed as separate clusters.
4. **Privacy by Design:** Scope is enforced in code: personal addresses, personal phone numbers, family/relationship data, and private gated communications are permanently blocked and dropped prior to storage.
5. **Accountable Use:** Built-in purpose capture, immutable query audit logging, per-user/IP rate limits, and dispute/removal mechanisms.

---

## 🏗️ System Architecture

```
[ Web UI (React + Vite) ]
          │
          ▼
[ FastAPI Gateway + Policy Layer ] ── (Audit Log, Rate Limits, Purpose Capture)
          │
          ▼
[ Query Understanding ] ──────────── (AI parsing of names, hints, and spelling variants)
          │
          ▼
[ Candidate Discovery ] ──────────── (Provider-agnostic search adapter: Google, Bing, DDG)
          │
          ▼
[ Source Collector ] ─────────────── (Robots.txt compliance, domain allowlist, rate limiting)
          │
          ▼
[ Extraction & Span Verification ] ─ (LLM extraction with strict verbatim text substring checks)
          │
          ▼
[ Scope Filter ] ─────────────────── (Allowlisted claim types only; drops private/personal data)
          │
          ▼
[ Entity Resolution Engine ] ─────── (Deterministic weighted clustering; conservative merging)
          │
          ▼
[ Profile Builder & Evidence UI ] ── (2-column split dossier layout + multi-profile comparison)
```

---

## 🛡️ Scope & Allowlist Policy

### In Scope
- Full name, aliases, professional headlines
- Occupations, employers, and organizations
- Committee, advisory, and leadership roles
- Academic publications, conference talks, and patents
- Verified professional profiles (GitHub, LinkedIn, Google Scholar, ORCID, Twitter/X)
- Accredited education, degrees, and credentials

### Out of Scope (Permanently Dropped)
- Home addresses, personal phone numbers, and personal emails
- Family, marital status, children, and relationship tracking
- Private or gated communities (closed Slack workspaces, Discord servers, private feeds)
- Biometric facial recognition or open-ended photo-to-identity search
- Leaked, breached, or gated data

---

## 📊 V1 Exit Milestone & Benchmarks

The platform has met the **V1 Exit Criteria**:
> *"Every displayed claim opens to a source; extraction precision measured on a labelled set."*

### Extraction Precision Benchmark
Run the standalone evaluation benchmark against the 12-scenario hand-labelled ground truth dataset:

```bash
python tests/evaluate_extraction.py
```

#### Benchmark Results (Labelled Evaluation Set):
```
========================================================================
  PERSONSEARCH EXTRACTION EVALUATION REPORT (V1 BENCHMARK)
========================================================================
Total Evaluation Examples  : 12
Ground Truth Claims        : 46
Extracted Verified Claims  : 46
True Positives             : 46
False Positives            : 0
------------------------------------------------------------------------
Extraction Precision       : 100.00%
Extraction Recall          : 100.00%
F1 Score                   : 100.00%
Span Verification Failures : 0 (Must be 0)
Out-of-Scope Data Leaks    : 0 (Must be 0)
------------------------------------------------------------------------
Claim Type         | GT    | TP    | FP    | Precision | Recall   
------------------------------------------------------------------------
education          | 4     | 4     | 0     |    100.0% |    100.0%
occupation         | 7     | 7     | 0     |    100.0% |    100.0%
organization       | 16    | 16    | 0     |    100.0% |    100.0%
profile_url        | 1     | 1     | 0     |    100.0% |    100.0%
project            | 2     | 2     | 0     |    100.0% |    100.0%
publication        | 3     | 3     | 0     |    100.0% |    100.0%
role               | 11    | 11    | 0     |    100.0% |    100.0%
talk               | 2     | 2     | 0     |    100.0% |    100.0%
========================================================================
```

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.11+**
- **Node.js 18+** & **npm**
- **PostgreSQL** (with `pg_trgm` extension for fuzzy name queries)
- **Redis** (optional; in-memory fallback enabled by default)

### 1. Backend Setup

```bash
# Clone the repository
git clone https://github.com/salpansoftwares-dot/personSearch.git
cd personSearch

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt  # or install app dependencies

# Configure environment variables
cp .env.example .env
# Edit .env to set your database URL and AI provider keys (NVIDIA, Google, etc.)

# Run database migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000
```

The API documentation will be available at `http://localhost:8000/docs`.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

The web application will be live at `http://localhost:5173`.

---

## 🧪 Testing

Run the automated test suite with pytest:

```bash
pytest tests/
```

- **54 unit, integration, and benchmark tests** covering:
  - Source collector allowlist enforcement (`test_discovery_collector.py`)
  - Verbatim evidence-span validation (`test_smoke.py`, `test_evaluation_set.py`)
  - Entity resolution conservative merge logic (`test_smoke.py`, `test_orchestrator.py`)
  - Dispute intake and audit log recording (`test_disputes_api.py`)
  - Persistence and claim relation storage (`test_persistence.py`)
  - Labelled evaluation set integrity and benchmark verification (`test_evaluation_set.py`)

---

## 🗺️ Roadmap: From V1 to V1.5 and Beyond

| Phase | Core Objective | Key Deliverables |
| :--- | :--- | :--- |
| **V1 (Complete)** | **Name to Sourced Profile** | Name + hints search, robots-aware source collection, span verification, deterministic clustering, AI model adapter, audit logging, dispute form, 2-column dossier UI & side-by-side comparison view, extraction precision benchmark. |
| **V1.5 (Next)** | **Quality, Safety & Governance** | **Suppression list** (hard opt-out preventing re-ingestion), **staleness detection** (SHA-256 content hashes, re-verification expiry), **retention policies**, evaluation harness for common Kenyan and international names, and automated prompt-injection testing. |
| **V2** | **Depth & Broad Coverage** | University registries, publications/patents adapters, embedding-based cluster similarity, cited profile summaries, and exportable due-diligence evidence reports. |
| **V3** | **Platform & Workspaces** | Multi-tenant organization workspaces, analyst assistant over verified claims, team audit exports, and enterprise internal directory connectors. |

---

## ⚖️ Governance and Compliance

- **Kenya Data Protection Act 2019 & GDPR Compliance:** Every profile includes a direct dispute modal (`POST /api/v1/disputes`) allowing data subjects to request corrections or removals.
- **Auditability:** Searches require purpose disclosure (`purpose` parameter) and are recorded in immutable query audit tables.
- **No Shadow Database:** Records expire, are re-verified, and can be suppressed via the governance engine.

---

## 📄 License

Proprietary / Restricted Research & Verification Platform. All rights reserved.
