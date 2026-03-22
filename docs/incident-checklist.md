# Incident Checklist

## If workers go offline, do this first

1. Check current worker token against:
   - `POST /api/v1/agent/heartbeat`
   - `GET /api/v1/agent/boards`
   - `GET /api/v1/agent/boards/<board-id>/tasks`
2. If all three are `200`, treat it as a lifecycle/liveness issue, not an auth issue.
3. Check:
   - `status`
   - `last_seen_at`
   - `last_provision_error`
   - `wake_attempts`
   - `last_wake_sent_at`
4. Inspect backend + worker logs for:
   - `agent auth invalid token`
   - `board.chat.wake.failed`
   - `agent.wakeup.sent`
   - `gateway.rpc.call.gateway_error`
   - `pairing required`

---

## If 401 appears, do this

1. Confirm the token being tested is the current worker `AUTH_TOKEN` from `TOOLS.md`
2. If `heartbeat/boards/tasks` return `401`, classify it as auth drift
3. Use explicit rotate/recovery path
4. Do **not** assume normal force-update should re-key the worker
5. Validate again until:
   - `heartbeat = 200`
   - `boards = 200`
   - `tasks = 200`
   - `status = online`
   - `last_seen_at` updated

---

## If board chat does not wake agents, do this

1. Check whether the target is stale/offline
2. Confirm board chat wake path is using controlled wake, not stale session reuse
3. Check backend logs for `board.chat.wake.failed`
4. Confirm the worker can resolve existing `AUTH_TOKEN` from `TOOLS.md`
5. Confirm wake leads to:
   - reset session
   - bootstrap
   - first automatic heartbeat
   - `last_seen_at` update
   - `status = online`

---

## When to recreate worker vs update worker

### Use normal update when
- changing instructions/templates/policy
- auth is still valid
- worker token should be preserved

### Use explicit rotate/recovery when
- worker endpoints return `401`
- backend and workspace token state drifted
- token must be re-keyed intentionally

### Do not recreate worker just because
- it is offline but endpoints still return `200`
- board chat wake failed once
- stale session reuse confused the runtime

Recreate/delete should be the last resort, not the first operator move.

---

## How to validate a real fix

A fix is only real if all of these hold:

1. current token checks are correct (`200` or `401`) and classification is clear
2. the real broken path is identified
3. the code path is patched minimally and explicitly
4. regression tests exist for that bug class
5. live validation shows:
   - wake happened
   - first automatic heartbeat happened
   - `status = online`
   - `last_seen_at` updated
   - worker stays alive long enough to do real work
