# Worker Auth and Wake Regressions

This document records the worker regressions found during the CardFlowAI Mission Control incident and how to recognize them again.

---

## 1) Old auth drift bug

### Symptom
- worker was healthy
- then after `PATCH /api/v1/agents/{id}?force=true`
- worker token in workspace and backend auth state drifted apart
- `/api/v1/agent/heartbeat`, `/boards`, `/boards/<board-id>/tasks` started returning `401`
- worker entered a `401` loop and went offline

### Exact broken code path

Normal worker update unexpectedly rotated token:
- `AgentLifecycleService.update_agent(...)`
- `mark_agent_update_pending(agent)`
- `mint_agent_token(agent)`

Then reconcile/update could rotate it again:
- `lifecycle_reconcile`
- `run_lifecycle(... action="update", auth_token=None)`
- `raw_token = auth_token or mint_agent_token(locked)`

### Fix
- normal worker update now preserves token
- implicit token rotation on normal update/reconcile is forbidden
- explicit rotate path remains separate
- update fails closed if existing token cannot be used

### How to recognize it again
- `401` on current worker token
- backend logs show invalid token immediately after a successful-looking worker update
- worker loops on boards/tasks/heartbeat auth failure

---

## 2) Board chat stale-session wake bug

### Symptom
- board chat activity happened
- offline/stale worker remained offline
- no new `last_seen_at`
- no fresh lifecycle re-entry
- board chat was effectively delivered into an old session instead of waking the worker properly

### Exact broken code path
- `POST /boards/{board_id}/memory`
- `_notify_chat_targets(...)`
- `try_send_agent_message(...)`

This was a chat-delivery path, not a real lifecycle wake path.

### Fix
- stale/offline targets are now routed through controlled lifecycle wake first
- stale session reuse is no longer the primary wake mechanism
- if controlled wake fails, board chat is not blindly delivered into the stale session

### How to recognize it again
- board chat memory entries appear
- worker stays offline
- `last_seen_at` does not move
- no evidence of reset/bootstrap/first heartbeat

---

## 3) `TOOLS.md` `AUTH_TOKEN` parser bug

### Symptom
- auth token was visibly present in worker `TOOLS.md`
- manual `X-Agent-Token` checks could succeed
- but controlled wake/update path still failed with:
  - `Worker update requires an existing AUTH_TOKEN in workspace`

### Exact broken code path
`_parse_tools_md(...)` expected plain `KEY=value` lines, but real worker `TOOLS.md` used markdown bullets/backticks such as:

```md
- `AUTH_TOKEN=...`
```

So the token existed but the parser did not see it.

### Fix
- `TOOLS.md` parser now accepts bullet/backtick markdown lines
- existing worker token can be recovered correctly from real workspace files

### How to recognize it again
- manual token checks succeed
- wake path still claims no existing `AUTH_TOKEN` is available
- backend logs point to token lookup failure, not token invalidity

---

## 4) Frontend-specific wrong heartbeat/cron branch

### Symptom
- Frontend sometimes woke and even re-entered partially
- but then dropped again instead of sustaining lifecycle
- logs showed it taking a cron/self-scheduling path for liveness recovery

### Root issue
The runtime guidance allowed a bad liveness interpretation:
- wake/bootstrap recovery drifted into cron usage
- but board-agent re-entry should happen through normal heartbeat/check-in, not cron

### Fix
- board-agent templates now explicitly forbid using cron for wake/bootstrap/liveness recovery
- re-entry must happen through the normal heartbeat/check-in lifecycle

### How to recognize it again
- worker wakes
- then tries to recover or sustain liveness via cron/tool scheduling
- but does not maintain stable `last_seen_at` / online state through normal check-in

---

## 5) Backend↔gateway control-plane/device identity issue

### Symptom
- containerized Mission Control backend or worker could hit:
  - `pairing required`
  - control-plane compatibility/device identity errors
- rotate/sync or worker recovery paths failed even after auth semantics were fixed

### Cause
- device identity for dockerized backend/worker was not persisted
- backend↔gateway local control-plane path was not stable after container recreate

### Fix
- persistent device identity volume for backend + webhook-worker
- trusted local control-plane path for dockerized MC
- host workspace mounted read-only where needed for worker workspace/token recovery

### How to recognize it again
- auth checks may be fine
- but rotate/sync or control-plane lifecycle operations fail with pairing/device identity errors

---

## Exact files that were fixed

- `backend/app/services/openclaw/provisioning_db.py`
- `backend/app/services/openclaw/lifecycle_orchestrator.py`
- `backend/app/services/openclaw/lifecycle_reconcile.py`
- `backend/app/api/board_memory.py`
- `backend/app/services/openclaw/gateway_rpc.py`
- `backend/templates/BOARD_AGENTS.md.j2`
- `backend/templates/BOARD_HEARTBEAT.md.j2`
- `compose.yml`

---

## Recognition checklist

When workers regress, distinguish quickly:

### Auth drift regression
- current token returns `401`
- broken update path likely re-keyed token unexpectedly

### Auth-valid offline regression
- current token returns `200`
- but worker remains offline because lifecycle re-entry is broken

### Stale-session wake regression
- board chat does not produce reset/bootstrap/first heartbeat
- worker remains offline without fresh `last_seen_at`

### Parser regression
- token is visibly present in `TOOLS.md`
- but backend claims no usable `AUTH_TOKEN` exists

### Wrong liveness-branch regression
- worker wakes but tries to sustain itself through cron or another wrong branch instead of normal heartbeat/check-in
