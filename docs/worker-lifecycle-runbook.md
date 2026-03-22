# Worker Lifecycle Runbook

## Purpose

This runbook explains how to diagnose and recover Mission Control board workers when they stop doing work or fall offline.

Use it to distinguish:
- **auth drift** (`401` on agent endpoints)
- **auth-valid offline** (token works, but worker does not re-enter active lifecycle)
- **wake path failures** (board chat / assignment does not lead to bootstrap + first heartbeat)

---

## Healthy state checklist

A worker is only considered healthy if **all** of the following are true:

1. `POST /api/v1/agent/heartbeat` with current `X-Agent-Token` returns `200`
2. `GET /api/v1/agent/boards` with current `X-Agent-Token` returns `200`
3. `GET /api/v1/agent/boards/<board-id>/tasks` with current `X-Agent-Token` returns `200`
4. `status = online`
5. `last_seen_at` is present and recent
6. the worker stays online long enough to perform real work (not just a transient check-in)

---

## Symptom classes

### 1) Token invalid / auth drift

Symptoms:
- agent endpoints return `401`
- worker session shows pre-flight failures on boards/tasks/heartbeat
- `last_seen_at` becomes stale because the worker cannot check in
- repeated `401` loop in worker logs

Typical meaning:
- worker token in workspace and backend hash drifted apart
- a broken update/reconcile path rotated token unexpectedly

### 2) Token valid but agent offline

Symptoms:
- agent endpoints return `200`
- `status = offline`
- `last_seen_at` is old
- no sustained automatic heartbeat/check-in loop
- board chat may or may not wake the worker

Typical meaning:
- auth is no longer the blocker
- lifecycle re-entry is broken or incomplete
- stale session reuse or broken wake/bootstrap path

### 3) Board chat wake failure

Symptoms:
- board chat memory entry is created
- offline worker stays offline
- no new `last_seen_at`
- no first automatic heartbeat after wake
- no real bootstrap/re-entry evidence in session/logs

Typical meaning:
- board chat did not trigger the correct lifecycle wake
- stale session was reused incorrectly
- wake happened but did not reach bootstrap/check-in

---

## Exact diagnostics to run

### A. Check worker API health with current token

Read current token from the worker workspace `TOOLS.md`, then test:

```bash
POST /api/v1/agent/heartbeat
GET  /api/v1/agent/boards
GET  /api/v1/agent/boards/<board-id>/tasks
```

Interpretation:
- `401` -> auth drift class
- `200` + offline -> lifecycle/liveness class

### B. Check Mission Control state

Inspect:
- `status`
- `last_seen_at`
- `last_provision_error`
- `wake_attempts`
- `last_wake_sent_at`
- `checkin_deadline_at`

### C. Inspect backend + worker logs

Look for:
- `agent auth invalid token`
- `agent.wakeup.sent`
- `lifecycle.queue.enqueued`
- `agent.provision.success`
- `gateway.rpc.call.gateway_error`
- `board.chat.wake.failed`
- `pairing required`
- first post-wake heartbeat/check-in

### D. Inspect worker session logs

For the affected worker, inspect the latest session file and confirm:
- was wake delivered?
- did bootstrap start?
- did the worker read startup/bootstrap files again?
- did automatic heartbeat/check-in happen?
- did the worker post to board chat or tasks after wake?

---

## Exact wake / re-entry chain

Healthy board-agent re-entry chain should be:

1. board activity (board chat mention, assignment, explicit wake path)
2. target selection
3. stale/offline detection
4. controlled wake invocation
5. `reset_session=True` for stale/offline target
6. wakeup delivery
7. bootstrap starts in a fresh runtime context
8. first automatic heartbeat/check-in arrives
9. `last_seen_at` updates
10. status becomes `online`
11. worker performs real work and remains alive long enough to continue

If any step is missing, the worker is **not** considered recovered.

---

## Controlled recovery path

### If auth is broken (`401`)

Use the explicit rotate/recovery flow:
1. `templates/sync?rotate_tokens=true`
2. reprovision/update the affected worker(s)
3. validate heartbeat/boards/tasks = `200`
4. confirm `last_seen_at` and `status = online`

Do **not** rely on ordinary force-update to rotate token implicitly.

### If auth is valid but worker is offline

Use lifecycle wake diagnostics:
1. confirm all three agent endpoints = `200`
2. trigger the real wake path (board chat mention / assignment path under current lifecycle rules)
3. verify:
   - wake happened
   - session reset happened if stale
   - bootstrap started
   - first automatic heartbeat happened
   - `last_seen_at` updated
   - `status = online`
4. if wake does not reach heartbeat, inspect the exact failing transition in backend + worker logs

---

## Controlled validation procedure

Use the same path for all compared agents.

### Validation recipe

1. Put agents into a known stale/offline state
2. Trigger the same wake path for all of them
3. For each agent prove:
   - current token endpoints = `200`
   - wake happened
   - bootstrap started
   - first automatic heartbeat happened
   - `last_seen_at` updated
   - `status = online`
4. Then trigger one small real work step and ensure the worker does not immediately drop back to offline

### Validation is not complete if

- only one agent wakes successfully
- auth is fine but `last_seen_at` never updates
- the worker becomes online only transiently and does no work
- board chat is delivered to stale session instead of proper lifecycle wake

---

## Recovery principles

- Do not assume offline means auth broken
- First distinguish **auth-invalid offline** vs **auth-valid offline**
- Normal worker update must preserve token semantics
- Board chat wake must not rely on stale session reuse
- Worker is not healthy without both auth validation **and** check-in validation
