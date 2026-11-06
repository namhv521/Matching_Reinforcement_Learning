# Semester-Only V3 Nested RL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild source-bound nested RL inputs so V1 uses 2024 student theses plus 2024 advisor corpus, V2 uses 2025.1 student theses plus advisor corpus through 2025.1, and V3 uses only 2025.2 student thesis data while inheriting V2's frozen advisor representation.

**Architecture:** Create a new immutable prepared-input package that excludes students without an exact roster-mapped thesis supervisor. Make advisor feature sources version-specific: V1 reads pool 2024, V2 reads pools 2024 and 2025.1, V3 reuses V2 advisor source IDs and vectors without reading a 2025.2 advisor corpus. Freeze the expanded taxonomy in the new feature contract, regenerate suites, source audit, feedback bindings, checkpoints, and a machine-readable plus Markdown run report.

**Tech Stack:** Python 3, CSV/JSON, NumPy/SciPy, PyTorch PPO, pytest, existing UniMatch source-bound RL pipeline.

**Spec:** `C:\Su\KLTNv2\KLTN\PRD.md` and user requirements from 2026-11-05.

## Global Constraints

- Keep 2025 advisor artifacts only in `2025.1`; reject calendar year 2026+ advisor artifacts.
- V3 must not read or require `2025.2/advisors/faculty_corpus/advisors_corpus.csv`.
- Remove thesis students whose extracted supervisor cannot be mapped exactly to the fixed advisor registry; never guess a name mapping.
- Do not fabricate advisor acceptance. KLTN supervisor links are historical outcome proxies with explicit semantics.
- Do not approve raw skill claims or fabricate `advisor_skill_scores.jsonl`.
- Freeze taxonomy hash, input hashes, source hashes, feedback hashes, and checkpoint contract hashes in new output namespaces.
- The final report must distinguish continuous assignment scores from categorical labels.

---

### Task 1: Build a supervisor-filtered immutable input package

**Files:**
- Create: `scripts/prepare_semester_rl_inputs.py`
- Test: `tests/rebuild/test_semester_rl_inputs.py`

**Interfaces:**
- Consumes: legacy prepared package, canonical student CSVs, fixed advisor roster, `student_advisor_links.csv`.
- Produces: `prepare_inputs(source: Path, destination: Path) -> dict` and `manifest.json`, `checksums.json`, filtered CSVs, exclusion receipts.

- [ ] Write tests for exact mapped supervisor retention and missing/unmapped supervisor exclusion.
- [ ] Implement row filtering keyed by student ID and exact normalized advisor name/ID from reviewed link records.
- [ ] Copy only immutable allowed input files into a fresh destination and rewrite checksums.
- [ ] Record excluded students and reasons per semester.
- [ ] Run input-package tests.

### Task 2: Encode advisor-source policy by version

**Files:**
- Modify: `src/features/semester_suite.py`
- Test: `tests/rebuild/test_semester_training.py`

**Interfaces:**
- Produces: `ADVISOR_SOURCE_POOLS = {'2024': ('2024',), '2025.1': ('2024', '2025.1'), '2025.2': ('2024', '2025.1'), '2025.3': ('2024', '2025.1')}`.
- Consumes: canonical advisor corpus paths and processed `source_record_ids` only for the declared source pool.

- [ ] Add a failing test proving V3 uses V2 advisor source IDs and never opens the 2025.2 corpus.
- [ ] Implement source-pool helper and frozen V2 advisor representation inheritance for V3.
- [ ] Persist source-pool policy and advisor representation origin in suite/snapshot metadata.
- [ ] Update audit reconstruction to use the same source-pool policy.
- [ ] Run semester-suite tests.

### Task 3: Create explicit R3 historical supervision-outcome feedback

**Files:**
- Modify: `src/features/survey_feedback.py`
- Test: `tests/rebuild/test_semester_training.py`

**Interfaces:**
- R2 consumes real survey priority fields.
- R3 consumes filtered `student_advisor_links.csv` and emits `type='verified_outcome'`, `historical_supervision_outcome_proxy`, never `advisor_feedback` unless independent approval evidence exists.

- [ ] Add a failing test for an exact supervisor link producing a train-only R3 outcome signal.
- [ ] Exclude unknown supervisor names from the package before feedback generation.
- [ ] Bind R3 source records with source hash, observed-at proxy, and no eligibility mutation.
- [ ] Update readiness report to separate independent advisor acceptance from historical supervision outcome proxy.
- [ ] Run feedback tests.

### Task 4: Freeze taxonomy and regenerate artifacts

**Files:**
- Create: `scripts/rebuild_semester_rl_run.py`
- Create: `outputs/semester_rl_20261105/` artifacts

**Interfaces:**
- Consumes: new prepared inputs and registration survey receipt.
- Produces: suites, source audit, feedback, training checkpoints, external test evaluation, and a run manifest.

- [ ] Create a new namespace only.
- [ ] Copy/hash the current taxonomy as a frozen input and record its 125-tag order/hash.
- [ ] Run `prepare`, `audit-sources`, `feedback`, `train`, then `evaluate` with source-bound hashes.
- [ ] Require at least 100,000 steps per main round and retain rejected candidates according to existing engine behavior.
- [ ] Verify all resulting manifests/checkpoints.

### Task 5: Report model/data semantics and skill-score readiness

**Files:**
- Create: `outputs/semester_rl_20261105/final_report.md`
- Create: `outputs/semester_rl_20261105/final_report.json`

**Interfaces:**
- Consumes: new prepared manifest, suite readiness, source audit, feedback readiness, training status, external results, taxonomy freeze, and advisor-skill snapshot status.
- Produces: reproducible summary with exact counts, exclusions, model type, output semantics, metrics, and explicit limitations.

- [ ] Report V1/V2/V3 data composition and V3 inherited advisor representation.
- [ ] Report removed students and unmapped supervisor names.
- [ ] State model output: constrained assignment action and continuous compatibility/value scores, not a supervised class label.
- [ ] State that advisor skill scores remain unavailable unless reviewed claims and feasible baseline exist.
- [ ] Run report consistency verification.