# ClawDev Architecture

## System Overview

ClawDev Mission Control extends OpenClaw Mission Control into a complete product development pipeline. The system transforms specifications into shipped products through an AI agent team with strict governance.

## Core Components

### 1. Control Plane (Mission Control Backend)

**Tech Stack:** FastAPI + SQLModel + PostgreSQL + Redis

**Key Modules:**

| Module | Path | Purpose |
|--------|------|---------|
| Artifact Hub | `backend/app/api/artifacts.py` | File upload, storage, preview, download |
| Planner Service | `backend/app/api/planner.py` | Spec → backlog generation with DAG |
| Run Store | `backend/app/api/runs.py` | Execution tracking and evidence |
| Pipeline | `backend/app/api/pipeline.py` | Plan→build→test orchestration |
| QA Service | `backend/app/api/qa.py` | Playwright test execution |
| Watchdog | `backend/app/api/watchdog.py` | Health monitoring and auto-recovery |
| Agent Roles | `backend/app/api/agents.py` | Role presets and team provisioning |

### 2. Runtime Plane (OpenClaw Gateway + OpenCode)

**Agents execute work through three runtime adapters:**

| Runtime | Adapter | Use Case |
|---------|---------|----------|
| ACP (Gateway) | `acp_adapter.py` | Primary — uses OpenClaw WebSocket RPC |
| OpenCode CLI | `opencode_cli_adapter.py` | Local execution via `opencode run` |
| OpenRouter API | `openrouter_adapter.py` | Direct LLM calls (feature-flagged) |

### 3. Telegram Interface

**Tech Stack:** aiogram 3.x + httpx

**Location:** `telegram-bot/`

**Commands:** `/board`, `/status`, `/task`, `/approvals`, `/nudge`, `/panic`, `/plan`

### 4. Frontend (Next.js 16)

**Key Pages:**

| Page | Path | Purpose |
|------|------|---------|
| Artifacts | `/artifacts` | Spec & artifact management |
| Planner | `/planner` | Backlog generation with React Flow DAG |
| Runs | `/runs` | Execution tracking |
| QA Testing | `/qa` | Playwright test runner |
| Agent Roles | `/agent-roles` | Team composition management |
| Watchdog | `/watchdog` | Health monitoring panel |

## Data Flow

### Spec → Product Pipeline

```
1. User uploads spec via Telegram or Web UI
   ↓
2. Artifact stored in Artifact Hub
   ↓
3. Planner generates backlog (epics → tasks → DAG)
   ↓
4. User reviews and approves backlog
   ↓
5. Planner applies backlog → creates Tasks on Board
   ↓
6. Team agents provisioned with role templates
   ↓
7. Pipeline executes: plan → build → test → review → done
   ↓
8. Watchdog monitors health, recovers from failures
   ↓
9. Continuous improvement backlog generated
```

### Agent Execution Flow

```
Task assigned to agent
   ↓
Runtime adapter selected (ACP/CLI/OpenRouter)
   ↓
Run created with stage (plan/build/test)
   ↓
Pipeline validation (soft warnings)
   ↓
Agent executes via runtime
   ↓
Evidence collected (logs, diffs, reports)
   ↓
Run completed → artifact created
   ↓
Next stage auto-triggered (if applicable)
```

## Database Schema

### Core Tables (from fork)
- `organizations`, `boards`, `tasks`, `agents`, `gateways`
- `approvals`, `activity_events`, `tags`, `board_groups`

### ClawDev Extensions
- `artifacts` — Uploaded/generated documents
- `planner_outputs` — Generated backlogs
- `runs` — Execution records

## Security Model

- **Trust Boundary:** Single gateway per instance
- **Auth:** Local token or Clerk JWT
- **Telegram:** Strict allowlist by user ID
- **Secrets:** Never logged, masked in evidence
- **API:** All endpoints require authentication

## Deployment

- **Target:** Self-hosted on macOS (home network)
- **Access:** Local network + Tailscale for remote
- **Stack:** Docker Compose (6 services)
  - PostgreSQL, Redis, Backend, Frontend, Webhook Worker, Telegram Bot
