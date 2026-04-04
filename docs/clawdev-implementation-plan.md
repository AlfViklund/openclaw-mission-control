# ClawDev Mission Control — Implementation Plan

## A. Upstream audit

### Already present in upstream
- FastAPI backend + Next.js frontend.
- Boards, tasks, agents, gateways, approvals, activity, tags, custom fields.
- Dependency-aware task model (`depends_on_task_ids`) and blocking behavior.
- Dashboard surfaces for boards, tasks, approvals, activity, agents.
- OpenClaw Gateway integration and ACP/OpenCode execution primitives in the broader ecosystem.

### Reusable as-is
- Board/task CRUD and dependency handling.
- Approvals API and UI patterns.
- Existing dashboard shell and backend API conventions.
- Background job / webhook / activity patterns.

### Needs extension
- Execution runs / steps / evidence / recovery state.
- Planner service from spec to backlog/DAG.
- Runtime adapter layer (ACP/OpenCode first).
- Policy engine for approvals.
- Reconciler / resume / heartbeat loop.

### Missing
- First-class execution lifecycle model.
- Spec / artifact hub.
- Evidence / verification model.
- Resume-safe orchestration across sessions.
- Product-level control plane flow.

## B. Target architecture

### Core domain model
- Project
- SpecArtifact
- Task / TaskDependency
- ExecutionRun
- ExecutionArtifact
- ApprovalRule / ApprovalRequest
- RuntimeSession
- Heartbeat / RecoveryState

### Services
- Spec ingestion
- Planner / DAG generation
- Execution orchestrator
- Policy engine
- Evidence collector
- Reconciler / recovery loop
- Runtime adapters

### Runtime orchestration
- PLAN → BUILD → TEST → REVIEW → DONE
- Evidence required at every stage
- Approval gates only when policy demands it

### Dashboard surfaces
- Overview
- Spec Hub
- Backlog / DAG
- Task detail
- Execution timeline
- Approvals queue
- Evidence viewer
- Runtime sessions / recovery

## C. MVP

Vertical slice:
- ingest spec
- generate backlog/DAG
- execute one task via OpenCode plan/build/test/review
- capture evidence
- persist state
- show progress in dashboard

## D. Phase plan

### Phase 1 — Execution foundation
- Persisted execution runs
- Evidence artifacts
- Recovery state
- Basic API endpoints
- Acceptance: create/list/update runs and artifacts

### Phase 2 — Planner / DAG
- Spec ingestion
- Backlog generation
- Dependency graph builder
- Acceptance: spec -> tasks -> dependencies

### Phase 3 — Runtime orchestration
- OpenCode/ACP adapter
- Plan/build/test/review pipeline
- Evidence capture
- Acceptance: one task runs end-to-end

### Phase 4 — Dashboard UX
- Execution panels
- Timeline and evidence UI
- Acceptance: operator can inspect runs and artifacts

### Phase 5 — Recovery / resume
- Heartbeats
- Stale session detection
- Safe resume
- Acceptance: interrupted runs can be resumed safely

## E. First execution batch

1. Add execution foundation models and migrations.
2. Add execution run/artifact API.
3. Add smoke tests for the new execution layer.
4. Hook dashboard UI to execution state in the next increment.

## Current focus
- Build the execution foundation backend first.
- Keep the implementation small and verifiable.
- Add UI after the backend contract is stable.

## Status
- Phase 1 execution foundation is now implemented:
  - persisted execution runs and artifacts backend
  - smoke coverage for router registration
  - dashboard-sideboard execution run panel wired into board detail UI
- Phase 2 planner / DAG generation is now started:
  - persisted spec artifacts backend
  - deterministic spec-to-DAG draft/apply service
  - planner API routes and smoke coverage
  - board sidebar spec-artifact panel for create/draft/apply flow
  - backlog / DAG workspace on the board overview with task tree and spec detail views
- Phase 3 runtime orchestration scaffolding is now started:
  - runtime adapter scaffold for OpenCode/ACP prompts
  - persisted phase/result evidence service helpers
  - HTTP start/phase-result seam on execution runs
  - runtime dispatch handoff endpoint that sends the current phase instruction to a runtime session and records checkpoint evidence
  - queue/worker dispatch automation with retry-safe idempotency for run handoffs
  - targeted runtime scaffold tests
- Phase 4 dashboard UX is now started:
  - execution runs panel now shows a selectable evidence timeline
  - artifact detail preview for execution evidence bodies and state payloads
  - run list remains the primary control surface for start / inspect
- Phase 5 recovery / resume semantics is now started:
  - stale-run detection based on heartbeat age
  - safe resume endpoint for stale/paused/failed runs
  - resume updates retry/recovery state and re-dispatches the current phase
  - dashboard resume action and stale badge for execution runs
  - heartbeat endpoint and live-run heartbeat button for evidence/state refresh
- Phase 5 recovery metadata is now centralized on the backend:
  - execution run responses now include computed stale/resume/heartbeat flags
  - dashboard uses recovery flags when available and falls back to local heuristics for compatibility
  - execution runs panel now shows heartbeat age on each run card
  - selected run detail now includes a recovery summary card with resume/heartbeat eligibility and raw recovery state
  - generated frontend execution-run model now includes the recovery flags so the dashboard contract stays aligned
  - selected run detail now also surfaces last dispatch, heartbeat source/message, and execution-state context
  - recovery overview strip now summarizes healthy/stale/resumable/heartbeatable counts across the run list
- Phase 5 UI recovery polish is now effectively complete for the current slice:
  - recovery controls are visible at board, list, and detail levels
  - backend flags drive the contract end-to-end
  - recovery overview strip now filters runs by healthy/stale/resumable/heartbeatable posture
- Phase 5 runtime/session follow-up is now represented by a derived runtime-sessions surface in the execution runs panel.
- Phase 5 runtime/session surface now shows grouped sessions, latest-run health, and an inspect-latest action derived from existing runs.
- Phase 5 runtime/session surface now also filters by live/stale/resumable posture.
- Phase 5 board-page polish now exposes execution runs as a named anchor section for discoverability.
- Next focus: broaden recovery UX further if needed, then move toward any remaining polish or integration gaps.
