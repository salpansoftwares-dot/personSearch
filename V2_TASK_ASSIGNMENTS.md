# PersonSearch - V2 Remaining Task Assignments
> Manager: Samba · Colleague: [@lameckkipsang](https://github.com/lameckkipsang)  
> Scope: **V2 only** - No V3 work until V2 exit criteria are met  
> Audit source: project_audit.md · Generated: 2026-10-05  
> V2 Status at audit time: **~85% complete (162/171 tests pass; 3 adapters missing)**

> [!IMPORTANT]
> **Scaffolds created 2026-10-12.** Files below are ready for implementation - all `# TODO` markers are the remaining work.
> `AsyncMockMixin` warning in [`test_profile_summary.py`](personsearch/tests/test_profile_summary.py) is **fixed**.

## V2 Exit Criteria (from Architecture doc)
> *"Coverage and accuracy gains verified against the evaluation set."*

The only remaining gaps before this criteria is met are the **3 missing source adapters** and the **cross-link entity resolution signal**.

## ⚠️ Remaining V2 Gaps

| # | Feature | Architecture Ref | Assigned To |
|---|---------|-----------------|-------------|
| 1 | **University / registry adapter** | Architecture §9 - "registries, conference and university pages" | 👤 [@lameckkipsang](https://github.com/lameckkipsang) |
| 2 | **Patents adapter** | Architecture §9 - "patents" | 👤 [@lameckkipsang](https://github.com/lameckkipsang) |
| 3 | **Conference page adapter** | Architecture §9 - "conference and university pages" | 👤 Samba (or review) |
| 4 | **Cross-link signal in entity resolution** | Architecture §6 - "Cross-links between sources" is **Strong** signal, not yet scored | 👤 Samba |

## Task 1 - University / Registry Adapter
**Assigned to:** [@lameckkipsang](https://github.com/lameckkipsang)  
**Branch:** `feature/v2-university-adapter`

### Scaffold
- [`app/core/adapters/university_adapter.py`](personsearch/app/core/adapters/university_adapter.py) - created, all `# TODO` sections to implement
- [`tests/test_new_adapters.py`](personsearch/tests/test_new_adapters.py) - `TestUniversityAdapter` class ready, skipped tests to unskip as @lameckkipsang implements

### What to build
A new adapter file `app/core/adapters/university_adapter.py` following the same interface as [`pubmed_adapter.py`](personsearch/app/core/adapters/pubmed_adapter.py).

### Scope
- Search university profile pages and academic directories (e.g., `.ac.ke`, `.edu` domains)
- Kenyan registries: Kenya Medical Practitioners & Dentists Council, LSK, IEK, etc.
- Extract claims: `occupation`, `organization`, `education`, `role`, `profile_url`
- Must enforce the claim-type allowlist via [`scope_filter.py`](personsearch/app/core/scope_filter.py)
- Must respect robots.txt and per-domain throttling (see [`collector.py`](personsearch/app/core/collector.py))

### Deliverables
- [ ] `app/core/adapters/university_adapter.py`
- [ ] Integration into the adapter registry / orchestrator
- [ ] Unit tests in `tests/test_source_adapters.py` (add a new class block)
- [ ] **Minimum: 8 passing tests** (follow PubMed/ORCID pattern)
- [ ] `CHANGELOG` entry

### Definition of Done
All tests pass. Adapter is wired into the orchestrator. Evidence reports generated via the adapter include source URL, retrieval date, and confidence.

## Task 2 - Patents Adapter
**Assigned to:** [@lameckkipsang](https://github.com/lameckkipsang)  
**Branch:** `feature/v2-patents-adapter`

### Scaffold
- [`app/core/adapters/patents_adapter.py`](personsearch/app/core/adapters/patents_adapter.py) - created, all `# TODO` sections to implement
- [`tests/test_new_adapters.py`](personsearch/tests/test_new_adapters.py) - `TestPatentsAdapter` class ready

### What to build
A new adapter `app/core/adapters/patents_adapter.py`.

### Scope
- Target: Google Patents (`patents.google.com`), Kenya Industrial Property Institute (KIPI), WIPO PatentScope
- Extract claims: `publication` (patent title, patent number), `organization` (assignee), `role` (inventor)
- Evidence span must be a verbatim excerpt from the source (enforced by extraction pipeline)
- Must **not** infer inventor identity - only report what the patent document states

### Deliverables
- [ ] `app/core/adapters/patents_adapter.py`
- [ ] Integration into the adapter registry / orchestrator
- [ ] Unit tests in `tests/test_source_adapters.py`
- [ ] **Minimum: 6 passing tests**
- [ ] `CHANGELOG` entry

### Definition of Done
Tests pass. Adapter respects scope filter. No out-of-scope claim types (no personal email, no home address inferred from KIPI records).

## Task 3 - Conference Page Adapter
**Assigned to:** Samba (manager - review required before merge)  
**Branch:** `feature/v2-conference-adapter`

### What to build
A new adapter `app/core/adapters/conference_adapter.py`.

### Scope
- Target: conference proceedings and speaker pages (ACM Digital Library, IEEE Xplore, local EAC/AfricaComm, etc.)
- Extract claims: `publication` (paper/talk title, year), `organization` (affiliation listed), `role` (speaker/panelist), `education`
- Cross-link detection: if a conference page links a GitHub profile, ORCID, or institutional page, extract `profile_url` claim -> this feeds into Task 4

### Deliverables
- [ ] `app/core/adapters/conference_adapter.py`
- [ ] Integration into the adapter registry / orchestrator
- [ ] Unit tests in `tests/test_source_adapters.py`
- [ ] **Minimum: 6 passing tests**
- [ ] `CHANGELOG` entry

## Task 4 - Cross-Link Signal in Entity Resolution
**Assigned to:** Samba (manager)  
**Branch:** `feature/v2-crosslink-signal`

### Context
From `project_audit.md`: *"Cross-link signal in entity resolution - Architecture doc mentions it; not yet a scored signal."*  

The architecture gives this signal **Strong** weight (see §6 of [Architecture.md](personsearch/Professional%20Profile%20Discovery%20Platform_%20Architecture.md)).

### What to build
Add cross-link scoring to [`entity_resolution.py`](personsearch/app/core/entity_resolution.py):

- When source A contains a URL that points to source B already in the cluster -> add a strong positive signal to the cluster score
- When a `profile_url` claim value matches a known source URL in another cluster -> treat as a cross-link bridge
- The score weight should be calibrated: suggest **0.35-0.45** on the existing 0-1 scale (stronger than employer match at ~0.25)
- Must **not** auto-merge on cross-link alone; must remain above the conservative merge threshold **combined with** other signals

### Deliverables
- [ ] Updated `app/core/entity_resolution.py` - new `score_cross_link_signal()` function
- [ ] Updated merge scoring to include cross-link weight
- [ ] New test cases in `tests/test_entity_resolution.py` - cross-link bridge raises score; single cross-link alone stays below merge threshold
- [ ] **Minimum: 4 new passing tests**
- [ ] Re-run `tests/evaluate_entity_resolution.py` - false-merge rate must not increase

## 🐛 Known Issues to Fix (Before / During V2 Work)

These are blocking or medium-priority issues from the audit. Whoever touches the related file should fix these inline:

| Issue | File | Priority | Fix |
|-------|------|----------|-----|
| `AsyncMockMixin` coroutine never awaited | [`test_profile_summary.py`](personsearch/tests/test_profile_summary.py), `orchestrator.py:325` | **Medium** | Use `AsyncMock` properly; ensure coroutine is awaited |
| Frontend CORS port mismatch | [`app/config.py`](personsearch/app/config.py) + `.env` | **Medium** | Frontend runs on 5175, not 5173 - update `cors_origins` |
| httpx deprecation warning | Test client | Low | Pin or upgrade httpx |

## Collaboration Rules & Push Workflow

1. **Mandatory Manager Review**: Samba (manager) must review and approve all code before merging into the `main` branch. Direct pushes to `main` are strictly forbidden.
2. **All Tests MUST PASS**: All tests MUST BE PASSED before merging. Zero test failures or regressions are permitted across all existing tests and new adapter tests.
3. **Strict V2 Requirement Adherence**: All features implemented must strictly conform to V2 requirements (Architecture doc §6, §9). No premature V3 scope or unapproved schema changes.
4. **Adapters must follow the existing interface**: Use [`pubmed_adapter.py`](personsearch/app/core/adapters/pubmed_adapter.py) as the canonical template.
5. **Scope filter is non-negotiable**: All adapters go through [`scope_filter.py`](personsearch/app/core/scope_filter.py); no out-of-scope claim types.
6. **No V3 work**: Tasks 1-4 only; V3 greenfield needs architecture planning first.

## V2 Target Test Count

| Source | Current (audit) | Target after V2 complete |
|--------|----------------|--------------------------|
| Total tests | 171 ✅ | **~200** (add ~29 new tests across 4 tasks) |
| Source adapter tests | Existing ORCID/PubMed/SemScholar | + university (8) + patents (6) + conference (6) = **+20** |
| Entity resolution tests | Existing | + cross-link (4) = **+4** |
| Misc (bug fixes) | 171 | +0 to +5 depending on async mock fix |

## Branch Strategy & PR Workflow

```
main
├── feature/v2-university-adapter   (@lameckkipsang)
├── feature/v2-patents-adapter       (@lameckkipsang)
├── feature/v2-conference-adapter    (Samba)
└── feature/v2-crosslink-signal      (Samba)
```

### Pull Request & Merge Instructions
- **Pushing code**: Always push code to the designated feature branch, never directly to `main`.
- **Review gate**: Samba (manager) has to review and approve all pull requests before merging to `main`.
- **Test verification**: All tests MUST PASS (`pytest`) with clean execution before any PR merge.
- **V2 compliance**: Confirm that all implemented features match the V2 requirements and deliverables outlined in each task.

Merge order recommendation:
1. `university-adapter` -> merge first (simpler, good warm-up for @lameckkipsang)
2. `patents-adapter` -> merge second
3. `conference-adapter` -> merge third (produces `profile_url` cross-links)
4. `crosslink-signal` -> merge last (benefits from conference adapter's cross-links being in place)
