# ClawDev Mission Control

> **Превращайте гигантские спецификации в готовые продукты с помощью команды AI-агентов**

Self-hosted система разработки продукта, построенная поверх OpenClaw + Mission Control + OpenCode. ClawDev добавляет полный pipeline от спецификации до shipped product с автоматическим планированием, исполнением, тестированием и мониторингом.

---

## 🚀 Что такое ClawDev

ClawDev — это операционная система для разработки продуктов, управляемая AI-агентами. Вы передаёте ему спецификацию (документ с описанием продукта), а он:

1. **Разбивает** спецификацию на эпики, задачи и зависимости (DAG)
2. **Создаёт** канбан-доску с backlog
3. **Провижинит** команду AI-агентов с ролями (Lead, Developer, QA, Writer, Ops)
4. **Запускает** pipeline: plan → build → test → review → done
5. **Мониторит** здоровье агентов и автоматически восстанавливается при сбоях
6. **Уведомляет** вас через Telegram о каждом важном событии

Всё работает на вашем домашнем Mac. Вы управляете системой через Telegram или веб-интерфейс.

---

## ✨ Возможности

### 📄 Spec & Artifact Hub

Загружайте, храните и управляйте спецификациями и артефактами проекта.

- **Загрузка файлов** через веб-интерфейс (drag & drop) или Telegram
- **Версионирование** — каждая загрузка создаёт новую версию
- **Preview** текстовых файлов прямо в браузере
- **Скачивание** любых артефактов
- **Привязка к задачам** — каждый артефакт связан с конкретной задачей
- **Типы артефактов**: spec, plan, diff, test_report, release_note, other

### 🧠 Backlog Planner

Автоматическая генерация структурированного backlog из спецификации.

- **AI-генерация** — отправьте spec, получите эпики + задачи + зависимости
- **DAG зависимостей** — визуализация графа зависимостей через React Flow
- **Валидация** — автоматическое обнаружение циклов и self-dependencies
- **Parallelism groups** — определение, какие задачи можно запускать параллельно
- **Редактирование** — правьте задачи перед применением
- **Apply to Board** — одним кликом создаёт реальные задачи на канбан-доске

### ⚡ Runtime Adapters

Три способа запуска AI-агентов для выполнения задач:

| Адаптер | Как работает | Когда использовать |
|---------|-------------|-------------------|
| **ACP (Gateway)** | Через OpenClaw WebSocket RPC | Основной — полная интеграция |
| **OpenCode CLI** | `opencode run --format json` | Локальное исполнение на Mac |
| **OpenRouter API** | Прямой HTTP вызов (feature-flagged) | Когда нужен прямой доступ к LLM |

Каждый run собирает **evidence**: логи, диффы, JSON events — всё сохраняется как артефакты.

### 🔗 Pipeline Orchestration

Guarded pipeline исполнения: **plan → approval → build → test → review → done**

- **Strict for agents** — агенты не могут нарушать порядок стадий
- **Guarded for owner** — ручные переходы в `review/done` требуют явного override и причины
- **Approval gate** — после успешного `plan` создаётся approval перед `build`
- **Авто-цепочка** — `build → test` выполняется автоматически только после успешного прохождения gate
- **Pipeline Visualization** — визуальный прогресс-бар на каждой задаче

### 🧪 QA Testing

Автоматическое тестирование через Playwright.

- **Запуск e2e тестов** через API или UI
- **Парсинг отчётов** — passed/failed/skipped, duration, ошибки, скриншоты
- **Авто-публикация** тест-отчётов как артефактов
- **Блокировка done** при провале тестов (через pipeline validation)
- **Фильтрация** — запуск конкретных тестов через grep

### 📱 Telegram Interface

Полное управление проектом через Telegram-бота.

| Команда | Описание |
|---------|----------|
| `/board <name>` | Выбрать активный проект |
| `/status` | Сводка: задачи по статусам, блокеры, агенты, approvals |
| `/task <id>` | Детали задачи + артефакты + pipeline статус |
| `/approvals` | Pending approvals с inline кнопками Approve/Reject |
| `/approve <id>` / `/reject <id>` | Решение по approval |
| `/nudge <agent\|task>` | Реально будит агента или запускает plan-stage для нераспределённой задачи |
| `/panic` | Ставит текущую доску на паузу |
| `/resume` | Снимает паузу с текущей доски |
| `/plan` | Запустить генерацию backlog из последней спецификации |

**Приём файлов** — просто отправьте документ в чат, и он автоматически загрузится как спецификация.

**Push-уведомления** — бот сам опрашивает backend и пишет вам при:
- Новом pending approval
- Failed build
- Offline агенте
- Разблокированной задаче
- Завершении pipeline стадии

### 👥 Agent Role Templates

Пять предконфигурированных ролей с шаблонами TOOLS.md, IDENTITY.md, SOUL.md, HEARTBEAT.md:

| Роль | Эмодзи | Heartbeat | Назначение |
|------|--------|-----------|-----------|
| **Board Lead** | 🎯 | 5m | Оркестрация проекта, управление backlog, координация команды |
| **Developer** | 🔧 | 10m | Реализация задач по плану, чистый код, evidence |
| **QA Engineer** | 🧪 | 10m | Тестирование, поиск багов, Playwright e2e |
| **Technical Writer** | 📝 | 15m | Документация, ADR, changelog, README |
| **Ops Guardian** | 🛡️ | 3m | Мониторинг здоровья, восстановление, безопасность |

Каждая роль имеет:
- Уникальный **identity profile** (role, communication style, purpose)
- Оптимальный **heartbeat interval**
- Role-specific **SOUL.md** с поведенческими инструкциями
- Role-specific **workflow** в AGENTS.md

### 🐕 Watchdog

Автоматический мониторинг и восстановление.

- **Heartbeat monitoring** — проверка каждые 30 секунд
- **Idle/dormant aware** — пустые доски не должны жечь токены на тяжёлых LLM-циклах
- **Cheap heartbeat first** — без wake conditions агент делает только дешёвый check-in и не тянет тяжёлый контекст
- **Lead idle mode** — lead тоже умеет работать в лёгком режиме на пустой/тихой доске
- **Авто-retry** — до 3 попыток с exponential backoff
- **Авто-reassign** — задачи offline-агентов возвращаются в inbox
- **Escalation** — уведомления при critical failures
- **Ops команды**:
  - `template-sync` — принудительная синхронизация шаблонов
  - `rotate-tokens` — ротация auth токенов
  - `reset-session` — сброс сессии агента
  - `wake` — пробуждение спящего агента
- **Evidence cleanup** — архивация файлов старше 30 дней
- **Watchdog Dashboard** — полная панель мониторинга в UI

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot (aiogram)                    │
│  /board /status /task /approvals /plan /panic /nudge        │
│  Приём файлов → автозагрузка в Artifact Hub                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP API
┌──────────────────────────▼──────────────────────────────────┐
│                  Mission Control Backend                     │
│                                                              │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌────────────────┐ │
│  │ Artifacts │ │ Planner  │ │  Runs   │ │   Pipeline     │ │
│  │   Hub     │ │ Service  │ │  Store  │ │ Orchestration  │ │
│  └───────────┘ └──────────┘ └─────────┘ └────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Runtime Adapters                          │ │
│  │  ACP (Gateway) │ OpenCode CLI │ OpenRouter API         │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │        QA Service (Playwright) + Watchdog              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  PostgreSQL (данные) + Redis (очереди, FSM)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket RPC
┌──────────────────────────▼──────────────────────────────────┐
│                   OpenClaw Gateway                           │
│  Telegram Channel │ ACP Sessions │ Agent Provisioning       │
│  Template Sync    │ Heartbeats   │ Workspace Management     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Как пользоваться: пошаговый гайд

### Шаг 1: Отправьте спецификацию

Откройте Telegram-бота и отправьте файл с описанием продукта (PDF, MD, TXT).
Бот автоматически загрузит его как спецификацию в Artifact Hub.

Или загрузите через веб-интерфейс: `/artifacts` → Upload → drag & drop.

### Шаг 2: Сгенерируйте backlog

В Telegram: отправьте `/plan`

Или в веб-интерфейсе: `/planner` → Generate Backlog → выберите спецификацию

AI проанализирует документ и создаст:
- **Эпики** — крупные блоки функциональности
- **Задачи** — конкретные actionable items
- **Зависимости** — DAG граф (что от чего зависит)
- **Parallelism groups** — какие задачи можно делать параллельно

### Шаг 3: Проверьте и примените

Откройте `/planner` — вы увидите интерактивный DAG граф.
Проверьте задачи, отредактируйте если нужно.

Нажмите **"Apply to Board"** — задачи создадутся на канбан-доске с правильными зависимостями.

### Шаг 4: Провизините команду

Перейдите в `/agent-roles` → **Provision Team**.

Выберите роли (рекомендуется все 5):
- 🎯 Board Lead — будет координировать
- 🔧 Developer — будет писать код
- 🧪 QA Engineer — будет тестировать
- 📝 Technical Writer — будет документировать
- 🛡️ Ops Guardian — будет следить за здоровьем

Нажмите **Provision** — агенты создадутся с правильными шаблонами.

### Шаг 5: Запустите pipeline

Агенты начнут работать автоматически. Вы можете наблюдать за прогрессом:

- **В Telegram**: `/status` — общая сводка, `/task <id>` — детали задачи
- **В UI**: канбан-доска показывает статус каждой задачи
- **Pipeline Visualization**: на каждой задаче видно plan → build → test прогресс

### Шаг 6: Управляйте через Telegram

Весь процесс управляется через Telegram:

```
/status          → "3 inbox, 2 in_progress, 1 review, 0 done. 1 blocker. 4/5 agents online. 2 pending approvals."
/approvals       → Список pending approvals с кнопками ✅/❌
/task abc123     → Детали задачи + артефакты + pipeline
/nudge dev-agent → Протолкнуть застрявшего разработчика
/panic           → Экстренная пауза всех агентов
```

### Шаг 7: Мониторьте через Watchdog

Откройте `/watchdog` — вы увидите:
- Статус каждого агента (online/offline)
- Активные escalations
- Результаты последнего health check
- Кнопки восстановления: Sync, Rotate, Reset, Wake

Если агент упал — Watchdog автоматически:
1. Переведёт его в offline
2. Вернёт его задачи в inbox
3. Отправит вам уведомление в Telegram
4. Попробует восстановить (wake → reset → sync)

---

## 🛠️ Установка и запуск

### Требования

- Docker & Docker Compose
- OpenClaw Gateway (работает на вашем Mac)
- Telegram Bot Token (получите у [@BotFather](https://t.me/BotFather))
- Ваш Telegram User ID (узнайте у [@userinfobot](https://t.me/userinfobot))

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/AlfViklund/openclaw-mission-control.git
cd openclaw-mission-control
```

### 2. Настройте окружение

Создайте `.env` файл в корне:

```env
# Auth
AUTH_MODE=local
LOCAL_AUTH_TOKEN=<сгенерируйте 50+ случайных символов>

# OpenClaw Gateway
OPENCLAW_GATEWAY_URL=ws://ваш-mac.local:8080
OPENCLAW_GATEWAY_TOKEN=<токен вашего gateway>

# Telegram Bot
TELEGRAM_BOT_TOKEN=<токен от BotFather>
TELEGRAM_ALLOWED_USER_IDS=<ваш Telegram user ID>

# Database
POSTGRES_DB=mission_control
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

Создайте `telegram-bot/.env`:

```env
TELEGRAM_BOT_TOKEN=<тот же токен>
TELEGRAM_ALLOWED_USER_IDS=<тот же user ID>
API_BASE_URL=http://backend:8000
API_TOKEN=<тот же LOCAL_AUTH_TOKEN>
```

### 3. Запустите стек

```bash
docker compose -f compose.yml --env-file .env up -d --build
```

### 4. Откройте UI

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/docs
- **Telegram**: Начните чат с вашим ботом

### 5. Подключите OpenClaw Gateway

В Mission Control UI перейдите к настройкам Gateway и подключите ваш OpenClaw Gateway.
После подключения запустите Template Sync для провижининга агентов.

---

## 📡 API Reference

### Artifacts

```
POST   /api/v1/artifacts                  Загрузить файл (multipart)
GET    /api/v1/artifacts                  Список с фильтрацией
GET    /api/v1/artifacts/{id}             Метаданные
GET    /api/v1/artifacts/{id}/download    Скачать файл
GET    /api/v1/artifacts/{id}/preview     Текстовый preview
DELETE /api/v1/artifacts/{id}             Удалить
```

### Planner

```
POST   /api/v1/planner/generate           Сгенерировать backlog из spec
GET    /api/v1/planner                    Список планов
GET    /api/v1/planner/{id}               Детали плана
PATCH  /api/v1/planner/{id}               Редактировать draft
POST   /api/v1/planner/{id}/apply         Применить к доске
DELETE /api/v1/planner/{id}               Удалить draft
```

### Runs

```
POST   /api/v1/runs                       Запустить execution run
GET    /api/v1/runs                       Список с фильтрацией
GET    /api/v1/runs/{id}                  Статус run
GET    /api/v1/runs/{id}/evidence         Evidence paths
POST   /api/v1/runs/{id}/cancel           Отменить run
GET    /api/v1/runs/tasks/{task_id}       Все runs задачи
```

### Pipeline

```
POST   /api/v1/pipeline/tasks/{id}/execute        Выполнить стадию
POST   /api/v1/pipeline/runs/{id}/auto-next       Авто-запуск следующей
GET    /api/v1/pipeline/tasks/{id}/validate       Валидация с warnings
POST   /api/v1/pipeline/tasks/{id}/status-validate Валидация смены статуса
```

### QA

```
POST   /api/v1/qa/test                    Запустить Playwright тесты
GET    /api/v1/qa/test/{id}/report        Просмотр отчёта
```

### Watchdog

```
POST   /api/v1/watchdog/health-check              Полный health check
POST   /api/v1/watchdog/check-heartbeats          Проверить heartbeats
POST   /api/v1/watchdog/retry-stuck-runs          Авто-retry застрявших runs
POST   /api/v1/watchdog/reassign-tasks            Reassign задач offline агентов
GET    /api/v1/watchdog/escalations               Текущие escalations
POST   /api/v1/watchdog/agents/{id}/template-sync Синхронизировать шаблоны
POST   /api/v1/watchdog/agents/{id}/rotate-tokens Ротация токенов
POST   /api/v1/watchdog/agents/{id}/reset-session Сброс сессии
POST   /api/v1/watchdog/agents/{id}/wake          Пробудить агента
POST   /api/v1/watchdog/cleanup-evidence          Очистка старых evidence
```

### Agents

```
GET    /api/v1/agents/presets                     Список role presets
POST   /api/v1/agents/presets/{preset}/create     Создать из пресета
POST   /api/v1/agents/boards/{id}/team/provision  Провизинить команду
```

---

## 📁 Структура проекта

```
openclaw-mission-control/
├── backend/                          # FastAPI backend
│   ├── app/
│   │   ├── api/                      # API endpoints
│   │   │   ├── artifacts.py          # Spec & Artifact Hub
│   │   │   ├── planner.py            # Backlog Planner
│   │   │   ├── runs.py               # Run tracking
│   │   │   ├── pipeline.py           # Pipeline orchestration
│   │   │   ├── qa.py                 # QA Testing
│   │   │   ├── watchdog.py           # Health monitoring
│   │   │   └── agents.py             # Agent presets + provisioning
│   │   ├── models/                   # SQLModel entities
│   │   │   ├── artifacts.py
│   │   │   ├── planner_outputs.py
│   │   │   └── runs.py
│   │   ├── schemas/                  # Pydantic schemas
│   │   ├── services/                 # Business logic
│   │   │   ├── runtime_adapters/     # ACP, OpenCode CLI, OpenRouter
│   │   │   ├── watchdog.py
│   │   │   ├── pipeline.py
│   │   │   ├── qa.py
│   │   │   └── ...
│   │   └── main.py
│   ├── migrations/                   # Alembic migrations
│   └── templates/                    # Jinja2 agent templates
│       ├── BOARD_SOUL.md.j2          # Role-specific soul
│       ├── BOARD_IDENTITY.md.j2      # Role-specific identity
│       ├── BOARD_HEARTBEAT.md.j2     # Role-specific heartbeat
│       └── BOARD_AGENTS.md.j2        # Role-specific instructions
├── frontend/                         # Next.js 16 UI
│   └── src/app/
│       ├── artifacts/                # Spec & Artifact Hub page
│       ├── planner/                  # Backlog Planner + React Flow DAG
│       ├── runs/                     # Run Evidence Store
│       ├── qa/                       # QA Testing page
│       ├── agent-roles/              # Team composition management
│       └── watchdog/                 # Health monitoring dashboard
├── telegram-bot/                     # Telegram bot (aiogram)
│   └── bot/
│       ├── handlers/
│       │   ├── board.py              # /board, /status, /task
│       │   ├── approvals.py          # /approvals + inline buttons
│       │   ├── control.py            # /nudge, /panic, /plan
│       │   └── files.py              # File upload handler
│       ├── api_client.py             # Mission Control API client
│       ├── middleware.py             # Allowlist middleware
│       ├── notifications.py          # Push notifications
│       └── app.py                    # Entry point
├── compose.yml                       # Docker Compose (6 services)
├── docs/
│   ├── clawdev-architecture.md       # Detailed architecture
│   ├── clawdev-runbook.md            # Recovery procedures
│   └── clawdev-security.md           # Security checklist
└── PROJECT_PLAN.md                   # Full project plan
```

---

## 🔐 Безопасность

ClawDev спроектирован с безопасностью в основе:

- **Жёсткий allowlist** — только ваш Telegram user ID может управлять системой
- **OpenClaw policies** — двойная защита через dmPolicy/allowFrom
- **Секреты не логируются** — маскирование в evidence файлах
- **Trust boundary** — один gateway на инстанс, нет мульти-тенантности
- **Token rotation** — регулярная ротация auth токенов
- **Security audit** — встроенная команда `openclaw security audit`

Подробнее: [`docs/clawdev-security.md`](docs/clawdev-security.md)

---

## 📖 Документация

- [Архитектура](docs/clawdev-architecture.md) — детальное описание системы
- [Runbook](docs/clawdev-runbook.md) — процедуры восстановления при сбоях
- [Security](docs/clawdev-security.md) — чеклист безопасности
- [Project Plan](PROJECT_PLAN.md) — полный план проекта со статусом

---

## 🛠️ Разработка

```bash
# Полный стек
docker compose -f compose.yml --env-file .env up -d --build

# Локальная разработка
docker compose -f compose.yml --env-file .env up -d db redis
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# Запуск всех проверок
make check

# Генерация API клиента
make api-gen
```

---

## 📊 Статус проекта

| Фаза | Статус |
|------|--------|
| 1. Spec & Artifact Hub | ✅ Завершено |
| 2. Planner Service | ✅ Завершено |
| 3. Runtime Adapters | ✅ Завершено |
| 4. Pipeline Orchestration | ✅ Завершено |
| 5. QA Agent & Playwright | ✅ Завершено |
| 6. Telegram Interface | ✅ Завершено |
| 7. Agent Role Templates | ✅ Завершено |
| 8. Reliability & Watchdog | ✅ Завершено |
| 9. Polish & Documentation | 🔄 В процессе |

**Прогресс: ~90%** — ядро, guarded pipeline и operator control уже работают; остаётся дальнейший UX/polish.

---

## 📄 Лицензия

MIT. См. [`LICENSE`](./LICENSE).

---

<p align="center">
  <strong>ClawDev Mission Control</strong> — от спецификации к продукту, управляемо AI-агентами.
</p>
