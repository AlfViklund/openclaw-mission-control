# Planner Pipeline Roadmap

This document tracks the staged planner redesign for ClawDev Mission Control.

## Product Goal

Turn a raw specification into a readable and reviewable planning package that includes:

- a specification digest
- planning documents for product, architecture, QA, docs, and ops
- a delivery epic map
- board-ready task packs with dependencies and role hints

The user must be able to read the whole package comfortably in the UI before applying it.

## Desired UX

1. User uploads a specification.
2. User starts planner generation.
3. UI shows a step timeline instead of a blocking spinner.
4. UI progressively exposes generated documents and epics.
5. User reviews the planner package in the browser.
6. User applies the package to the board.
7. Lead starts orchestration from the approved planner package, not from the raw spec alone.

## Pipeline

1. `digest`
   - split spec into chunks
   - summarize chunks
   - synthesize one specification digest
2. `dossier`
   - generate readable Markdown documents
   - product brief
   - architecture brief
   - QA strategy
   - documentation plan
   - release and ops runbook
3. `epics`
   - synthesize delivery epics from the dossier
4. `tasks`
   - expand each epic into a task pack
   - normalize dependencies across task packs
5. `ready`
   - expose planner package for review/apply

## Agent Ownership Rules

- Prefer role specialists when available and online.
- Fallback to lead when the preferred role is missing or unavailable.
- Planner documents should record both preferred role and actual generating agent.

## Backend Checklist

- [x] Add planner output pipeline fields for phase and documents.
- [x] Move planner generation to staged background orchestration.
- [x] Persist readable planner documents as generated artifacts.
- [x] Expand epic tasks in smaller per-epic prompts.
- [ ] Add richer planner API tests for staged generation output.
- [ ] Add service tests for document persistence and dependency normalization.
- [ ] Add migration verification in compose/runtime path.

## UI Checklist

- [x] Replace blocking spinner with generating state and polling.
- [x] Show phase timeline in planner page.
- [x] Render generated planner documents in the UI.
- [x] Add preview sections for documents, epics, and tasks.
- [ ] Refine layout for long documents on desktop and mobile.
- [ ] Add explicit retry actions per failed phase when possible.
- [ ] Show generated artifact links for planner documents.

## Board Bootstrap Checklist

- [ ] After apply, create planner package handoff for lead.
- [ ] Allow lead to start execution from approved dossier and epic/task package.
- [ ] Ensure docs tasks go to Technical Writer when present, fallback to lead otherwise.
- [ ] Expose planner package provenance on board tasks.

## Open Questions

- Should planner documents remain editable before apply?
- Should epic synthesis allow manual reordering before task expansion?
- Should dependency normalization be split into a distinct UI-visible step?
