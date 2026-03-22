# Local Patches

This file records the local Mission Control divergences currently carried in this workspace.

As of this incident, the files below are **local divergences from upstream `origin/master`**.

---

## 1) `backend/app/services/openclaw/provisioning_db.py`

### Why changed
- fix worker auth drift
- preserve token semantics on normal update
- support reading existing `AUTH_TOKEN` from real worker `TOOLS.md` markdown format
- add acceptance/auth validation helpers and host-workspace token fallback for lifecycle wake/re-entry

### Coverage / proof
- targeted regression tests in `backend/tests/test_worker_auth_update_semantics.py`
- live worker endpoint checks (`heartbeat/boards/tasks = 200`)
- real lifecycle recovery / wake validation during incident

---

## 2) `backend/app/services/openclaw/lifecycle_orchestrator.py`

### Why changed
- forbid implicit token rotation on normal worker update
- force explicit token semantics on update path
- fail closed instead of silently drifting into broken auth

### Coverage / proof
- targeted regression tests in `backend/tests/test_worker_auth_update_semantics.py`

---

## 3) `backend/app/services/openclaw/lifecycle_reconcile.py`

### Why changed
- reconcile/update path must use explicit existing worker token
- avoid hidden re-key on update/re-entry

### Coverage / proof
- targeted regression tests in `backend/tests/test_worker_auth_update_semantics.py`

---

## 4) `backend/app/api/board_memory.py`

### Why changed
- board chat path previously reused stale sessions and did not reliably wake offline workers
- add stale/offline detection
- route stale/offline targets through controlled lifecycle wake with `reset_session=True`
- do not blindly deliver board chat into stale session when controlled wake fails

### Coverage / proof
- targeted regression tests in `backend/tests/test_board_chat_wake_path.py`
- live wake validation against Leo / Frontend / Backend during incident

---

## 5) `backend/app/services/openclaw/gateway_rpc.py`

### Why changed
- improve logging on gateway RPC failures so lifecycle regressions show the actual error body instead of a vague gateway error line

### Coverage / proof
- incident diagnostics; used to isolate downstream lifecycle/control-plane failures precisely

---

## 6) `backend/templates/BOARD_AGENTS.md.j2`

### Why changed
- document that board agents must not use cron for wake/bootstrap/liveness recovery
- enforce that re-entry belongs to normal heartbeat/check-in lifecycle

### Coverage / proof
- live debugging of Frontend-specific wrong liveness branch
- runtime template reprovision during incident

---

## 7) `backend/templates/BOARD_HEARTBEAT.md.j2`

### Why changed
- reinforce that post-wake/bootstrap liveness must re-enter through heartbeat/check-in, not cron

### Coverage / proof
- incident runtime behavior; template reprovision used in wake/liveness recovery

---

## 8) `compose.yml`

### Why changed
- add persistent device identity volume for dockerized backend + webhook worker
- mount host workspace read-only so lifecycle/re-entry can recover existing worker `TOOLS.md` state when needed
- stabilize backend↔gateway local control-plane behavior

### Coverage / proof
- live recovery of backend↔gateway control-plane path
- successful rotate/sync and worker recovery after pairing/device-identity blocker

---

## 9) `backend/tests/test_worker_auth_update_semantics.py`

### Why changed
- add regression coverage for create / normal update / explicit rotate / fail-closed behavior around worker auth semantics

### Coverage / proof
- targeted suite result: `6 passed`

---

## 10) `backend/tests/test_board_chat_wake_path.py`

### Why changed
- add regression coverage for board chat wake behavior on stale/offline targets
- ensure stale session is not reused incorrectly
- verify controlled wake uses `reset_session=True`
- verify parser accepts real `TOOLS.md` markdown format

### Coverage / proof
- targeted suite result together with worker-auth tests: `11 passed`

---

## Upstream status

These changes are currently treated as **local patches**. They should be reviewed for upstreaming later, but for now they are recorded as explicit local divergence so future operators know this install carries behavior that upstream may not yet contain.
