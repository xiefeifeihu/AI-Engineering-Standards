# Artifact Governance Architecture v1.1

**Document Type**: Architecture Overview  
**Version**: 1.1.0  
**Status**: ACTIVE  
**Last Updated**: 2026-09-23  
**Related Standards**: STD-014 v1.1, STD-015 v1.1, STD-016, STD-019, STD-020

---

## Overview

This document describes the engineering artifact governance model introduced in AI Engineering Standards v1.1.0. It defines how artifacts are classified, stored, retained, and handed off across engineering sessions.

## Artifact Taxonomy

```
All Engineering Artifacts
├── SOURCE          → Git repo source tree (committed)
├── GENERATED       → .artifacts/ (gitignored, reproducible)
│   ├── ACCEPTANCE  → .artifacts/acceptance/<TASK>/<VERSION>/
│   ├── DEMO        → .artifacts/demo/
│   └── TEMPORARY   → .artifacts/handoff/temporary/
└── ARCHIVE         → .artifacts/packages/ (final ZIP deliverables)
```

## Key Design Decisions

### 1. Zero-Git-Pollution
All generated artifacts are stored under `.artifacts/` which is excluded from Git tracking. This ensures the repository remains clean and reproducible. Acceptance ZIPs are handed off out-of-band.

### 2. Task/Version Isolation
Each acceptance run is isolated under `.artifacts/acceptance/<TASK-ID>/<VERSION>/` to prevent mixing evidence across tasks or versions.

### 3. Unified Packaging Script
A single `scripts/package_acceptance.py` script drives all acceptance packaging. Version-specific scripts (e.g., `package_acceptance_v055.py`) are eliminated.

### 4. KPI Semantic Correctness
Resource KPI cards on the Hub homepage reflect true operational state:
- **运行中**: resources where `actual_state == READY/HEALTHY`
- **按需资源**: resources where `lifecycle_policy == ON_DEMAND` (regardless of actual state)
- **总资源**: all registered resources

These metrics are computed independently using separate fields to avoid the v0.5.5 bug where ON_DEMAND resources were conflated with stopped resources.

### 5. Playwright Mode Governance
Three explicit Playwright modes (AUTOMATED_TEST, ACCEPTANCE, DEMO) with mandatory headless/headed and evidence rules prevent ambiguity in test execution context.

## Compliance Matrix

| Standard | v1.0 | v1.1 | Change |
|----------|------|------|--------|
| STD-014 | Basic layers | Four-level matrix (L1-L4) | +SMOKE/CORE/DEEP/DIAGNOSTIC |
| STD-015 | Headless + themes | Three explicit modes | +AUTOMATED_TEST, DEMO modes |
| STD-016 | ZIP naming | Unchanged | - |
| STD-019 | (new) | Six artifact types | NEW |
| STD-020 | (new) | Durable/Temporary handoff | NEW |

## Workspace Hygiene Process

```
milestone_complete
    → run tools/cleanup_audit.py
    → review workspace_cleanup_audit.md
    → run tools/cleanup_plan.py (generates plan)
    → human review workspace_cleanup_plan.md
    → approve and execute plan
    → verify .artifacts/ gitignored
```