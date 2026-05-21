---
phase: 3
slug: diffmanager-system
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-08
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `.venv/bin/pytest tests/test_diff*.py tests/test_snapshot.py tests/test_messages.py tests/test_reconstructor.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/ -x` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/test_diff*.py tests/test_snapshot.py tests/test_messages.py tests/test_reconstructor.py -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | R3.2+ (schema) | unit | `.venv/bin/pytest tests/test_experiment_model.py -x` | No — W0 | pending |
| 03-01-02 | 01 | 1 | R3.1, R3.2 | unit | `.venv/bin/pytest tests/test_snapshot.py tests/test_differ.py -x` | No — W0 | pending |
| 03-02-01 | 02 | 2 | R3.2+ (description) | unit | `.venv/bin/pytest tests/test_messages.py -x` | No — W0 | pending |
| 03-02-02 | 02 | 2 | R3.2+ (reconstruction) | unit | `.venv/bin/pytest tests/test_reconstructor.py -x` | No — W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_snapshot.py` — covers R3.1 (snapshot capture, missing files)
- [ ] `tests/test_differ.py` — covers R3.2 (diff generation, hash computation)
- [ ] `tests/test_messages.py` — covers R3.2+ (YML loader, description generation)
- [ ] `tests/test_reconstructor.py` — covers R3.2+ (codebase reconstruction round-trip)
- [ ] `tests/test_experiment_model.py` — covers R3.2+ (field renames, bug fixes)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-08
