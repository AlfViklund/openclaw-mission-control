# ClawDev Mission Control — Полный план проекта

## Обзор

Self-hosted система разработки продукта поверх OpenClaw + Mission Control + OpenCode с Telegram-управлением, канбаном, DAG-планированием, строгим plan→build→test пайплайном и агентной командой.

**Целевая среда:** macOS (home network), Telegram как основной интерфейс
**Дата:** 2026-04-01

---

## Текущий статус

| Фаза | Статус | Прогресс |
|------|--------|----------|
| 0. Bootstrap | ⏳ Pending | 0% |
| 1. Spec & Artifact Hub | ✅ Complete | 100% |
| 2. Planner Service | ✅ Complete | 100% |
| 3. Runtime Adapters | ✅ Complete | 100% |
| 4. Pipeline Orchestration | ✅ Complete | 100% |
| 5. QA Agent & Playwright | ✅ Complete | 100% |
| 6. Telegram Interface | ✅ Complete | 100% |
| 7. Agent Role Templates | ✅ Complete | 100% |
| 8. Reliability & Watchdog | ✅ Complete | 100% |
| 9. Polish & Documentation | 🔄 In Progress | 95% |

**Общий прогресс: ~97%**

---

## Фаза 0: Bootstrap и настройка

- [ ] 0.1 — Развернуть стек локально (docker compose up)
- [ ] 0.2 — Проверить backend health check и API
- [ ] 0.3 — Проверить frontend UI
- [ ] 0.4 — Подключить к OpenClaw Gateway (WebSocket RPC)
- [ ] 0.5 — Проверить provisioning агента через Gateway

---

## Фаза 1: Spec & Artifact Hub ✅

### Созданные файлы:
- `backend/app/models/artifacts.py` — SQLModel Artifact
- `backend/migrations/versions/ab12cd34ef56_add_artifacts.py` — миграция
- `backend/app/schemas/artifacts.py` — Pydantic схемы
- `backend/app/services/artifact_storage.py` — локальное file storage
- `backend/app/services/artifacts.py` — CRUD операции
- `backend/app/api/artifacts.py` — API endpoints (upload/download/preview/delete)
- `frontend/src/app/artifacts/page.tsx` — страница с карточками, drag&drop, preview
- `backend/.gitignore` — добавлена папка storage/

### API endpoints:
- `POST /api/v1/artifacts` — загрузка файла (multipart)
- `GET /api/v1/artifacts` — список с фильтрацией
- `GET /api/v1/artifacts/{id}` — метаданные
- `GET /api/v1/artifacts/{id}/download` — скачивание
- `GET /api/v1/artifacts/{id}/preview` — текстовый preview
- `DELETE /api/v1/artifacts/{id}` — удаление

---

## Фаза 2: Planner Service ✅

### Созданные файлы:
- `backend/app/models/planner_outputs.py` — SQLModel PlannerOutput
- `backend/migrations/versions/bc23de45fg67_add_planner_outputs.py` — миграция
- `backend/app/schemas/planner.py` — Pydantic схемы
- `backend/app/services/planner_dag.py` — валидация DAG (циклы, topological sort)
- `backend/app/services/planner.py` — генерация backlog через Gateway ACP
- `backend/app/services/planner_crud.py` — CRUD операции
- `backend/app/api/planner.py` — API endpoints
- `frontend/src/app/planner/page.tsx` — React Flow DAG визуализация

### API endpoints:
- `POST /api/v1/planner/generate` — генерация backlog из spec
- `GET /api/v1/planner` — список с фильтрацией
- `GET /api/v1/planner/{id}` — детали
- `PATCH /api/v1/planner/{id}` — редактирование draft
- `POST /api/v1/planner/{id}/apply` — применение (создаёт задачи)
- `DELETE /api/v1/planner/{id}` — удаление draft

---

## Фаза 3: Runtime Adapters ✅

### Созданные файлы:
- `backend/app/models/runs.py` — SQLModel Run
- `backend/migrations/versions/cd34ef56gh78_add_runs.py` — миграция
- `backend/app/schemas/runs.py` — Pydantic схемы
- `backend/app/services/runtime_adapters/base.py` — абстрактный интерфейс
- `backend/app/services/runtime_adapters/acp_adapter.py` — через Gateway ACP
- `backend/app/services/runtime_adapters/opencode_cli_adapter.py` — через opencode run
- `backend/app/services/runtime_adapters/openrouter_adapter.py` — прямой API (feature-flagged)
- `backend/app/services/runs.py` — CRUD + start/complete/cancel
- `backend/app/api/runs.py` — API endpoints
- `frontend/src/app/runs/page.tsx` — страница Run Evidence Store

### API endpoints:
- `POST /api/v1/runs` — создание и запуск run
- `GET /api/v1/runs` — список с фильтрацией
- `GET /api/v1/runs/{id}` — детали
- `GET /api/v1/runs/{id}/evidence` — evidence paths
- `POST /api/v1/runs/{id}/cancel` — отмена
- `GET /api/v1/runs/tasks/{task_id}` — все runs задачи

---

## Фаза 4: Pipeline Orchestration ✅

### Созданные файлы:
- `backend/app/services/pipeline_validation.py` — мягкая валидация (warnings)
- `backend/app/services/pipeline.py` — PipelineService
- `backend/app/api/pipeline.py` — API endpoints
- `frontend/src/components/pipeline/PipelineVisualization.tsx` — компонент

### API endpoints:
- `POST /api/v1/pipeline/tasks/{id}/execute` — выполнить стадию
- `POST /api/v1/pipeline/runs/{id}/auto-next` — авто-запуск следующей
- `GET /api/v1/pipeline/tasks/{id}/validate` — guarded validation с blockers/warnings
- `POST /api/v1/pipeline/tasks/{id}/status-validate` — валидация смены статуса

---

## Фаза 5: QA Agent & Playwright ✅

### Созданные файлы:
- `backend/app/services/qa.py` — PlaywrightRunner + QAService
- `backend/app/api/qa.py` — API endpoints
- `frontend/src/app/qa/page.tsx` — страница QA Testing

### API endpoints:
- `POST /api/v1/qa/test` — запуск Playwright тестов
- `GET /api/v1/qa/test/{run_id}/report` — просмотр отчёта

---

## Фаза 6: Telegram Interface ✅

### Созданные файлы:
- `telegram-bot/pyproject.toml` — зависимости (aiogram, httpx)
- `telegram-bot/Dockerfile` — контейнер
- `telegram-bot/bot/config.py` — настройки (token, allowlist, API URL)
- `telegram-bot/bot/api_client.py` — Mission Control API клиент
- `telegram-bot/bot/middleware.py` — allowlist middleware
- `telegram-bot/bot/handlers/board.py` — /board, /status, /task
- `telegram-bot/bot/handlers/approvals.py` — /approvals + inline кнопки
- `telegram-bot/bot/handlers/control.py` — /nudge, /panic, /plan
- `telegram-bot/bot/handlers/files.py` — приём файлов (spec)
- `telegram-bot/bot/notifications.py` — push уведомления
- `telegram-bot/bot/app.py` — точка входа
- `compose.yml` — добавлен сервис telegram-bot

### Команды бота:
- `/board <name>` — выбор активной доски
- `/status` — сводка по проекту
- `/task <id>` — детали задачи
- `/approvals` — pending approvals с inline кнопками
- `/nudge <agent|task>` — протолкнуть
- `/panic` — аварийная пауза
- `/resume` — снять паузу с текущей доски
- `/plan` — генерация backlog
- Приём файлов — автозагрузка как spec artifact

---

## Фаза 7: Agent Role Templates ✅

### Задачи:
- [x] 7.1 — Шаблон Main (board lead) — TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md
- [x] 7.2 — Шаблон Dev worker — TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md
- [x] 7.3 — Шаблон QA worker — TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md
- [x] 7.4 — Шаблон Docs worker — TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md
- [x] 7.5 — Шаблон Ops guardian — TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md
- [x] 7.6 — Авто-провижининг агентов с шаблонами через template sync
- [x] 7.7 — Интеграция с agents.create и gateway RPC

---

## Фаза 8: Reliability & Watchdog ✅

### Задачи:
- [x] 8.1 — Heartbeat monitoring сервис
- [x] 8.2 — Таймауты и авто-retry для runs
- [x] 8.3 — Авто-reassign задач при offline агенте
- [x] 8.4 — Escalation к человеку при repeated failures
- [x] 8.5 — Ops команды восстановления: template sync rotate_tokens, reset_sessions
- [x] 8.6 — Evidence retention & cleanup политика
- [x] 8.7 — Интеграция с существующим heartbeat endpoint
- [x] 8.8 — Фронтенд: индикация статуса агентов (online/offline)
- [x] 8.9 — Фронтенд: панель управления watchdog

---

## Фаза 9: Polish & Documentation

### Задачи:
- [ ] 9.1 — UX: улучшить канбан-доску, фильтры, поиск
- [ ] 9.2 — Экспорт проекта (spec + backlog + результаты + improvements)
- [ ] 9.3 — Режим «шаблоны проектов» (scaffold новой доски)
- [ ] 9.4 — Security hardening checklist
- [ ] 9.5 — Cost/usage мониторинг по моделям и агентам
- [x] 9.6 — README проекта
- [x] 9.7 — Документация по архитектуре
- [x] 9.8 — Runbook восстановления
- [x] 9.9 — Security checklist
- [ ] 9.10 — PWA режим для UI

### Последние реализованные улучшения
- Guarded pipeline mode: review/done требуют успешного test-run или owner override с причиной
- Approval gate: после plan создаётся approval перед build
- Approval continuation: approve на pipeline.build возобновляет конвейер автоматически
- Board panic/resume: pipeline может быть поставлен на паузу на уровне доски
- Heartbeat optimization: cheap-first flow и idle/dormant режимы уменьшают расход токенов на пустых досках
- Telegram control actions: `/panic`, `/resume`, `/nudge` теперь делают реальные backend-вызовы
- QA execution path: test-stage выполняется через QA service вместо generic build-like path
- Notification polling: бот сам обнаруживает approvals, failed builds, pipeline completions, unblocked tasks и escalations

---

## Модели данных

### Уже реализовано:
- **Artifact** — spec, plan, diff, test_report, release_note, other
- **PlannerOutput** — epics[], tasks[], dependency_graph, parallelism_groups
- **Run** — task execution (runtime, stage, status, evidence_paths)

### Нужно добавить:
- **PlannerOutput** связи с Task (уже есть через apply)
- **Run** связи с Artifact (evidence)

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot (aiogram)                    │
│  /board /status /task /approvals /plan /panic /nudge        │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP API
┌──────────────────────────▼──────────────────────────────────┐
│                  Mission Control Backend                     │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌────────────────┐ │
│  │ Artifacts │ │ Planner  │ │  Runs   │ │   Pipeline     │ │
│  │   Hub     │ │ Service  │ │  Store  │ │ Orchestration  │ │
│  └───────────┘ └──────────┘ └─────────┘ └────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Runtime Adapters                          │ │
│  │  ACP (Gateway) │ OpenCode CLI │ OpenRouter API         │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              QA Service (Playwright)                   │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   OpenClaw Gateway                           │
│  Telegram Channel │ ACP Sessions │ Agent Provisioning       │
└─────────────────────────────────────────────────────────────┘
```

---

## Следующие шаги

1. **Фаза 0** — Развернуть стек и проверить работоспособность
2. **Фаза 7** — Создать шаблоны агентных ролей
3. **Фаза 8** — Реализовать watchdog и надёжность
4. **Фаза 9** — Полировка и документация
