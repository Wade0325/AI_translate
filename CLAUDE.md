# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run the app (single Docker stack, local Windows)

The whole stack — Postgres, Redis, FastAPI, Celery, Vite — runs from one `docker-compose.yml`
via the `dc.bat` helper (wraps `docker compose`, auto-checks Docker Desktop + `.env`):

```bash
.\dc.bat                          # build + start all services (first run / after code change)
.\dc.bat start                    # start without rebuild (fastest)
.\dc.bat stop                     # stop but keep containers
.\dc.bat down                     # stop and remove containers
.\dc.bat restart celery-worker    # restart one service after editing celery code
.\dc.bat logs backend-service     # follow one service's logs
.\dc.bat rebuild                  # --no-cache rebuild + restart
```

- Frontend: <http://localhost:5173> ｜ API docs: <http://localhost:8000/docs>
- Backend (`uvicorn --reload`) and frontend (Vite HMR) hot-reload on save; source is volume-mounted, so no rebuild for code edits.
- Celery has **no** auto-reload — run `.\dc.bat restart celery-worker` after editing task code.

### Tests

```bash
pytest tests/ -v                                        # full suite (from repo root)
pytest tests/integration/test_model_manager_api.py -v   # single file
```

`pytest.ini` sets `pythonpath = backend`, so tests import from `backend/` (e.g. `from app.api import ...`).
The suite is self-contained (SQLite in-memory + mocked torch); it needs no Postgres/Redis.

### Environment

- Single env file: **`.env`** at the repo root (git-ignored). Copy `.env.example` and fill in `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`.
- `DATABASE_URL` and `REDIS_HOST` are injected by docker-compose — do not set them manually.
- The Google Gemini API key is **not** an env var — enter it in the app's **Settings** page (stored in `model_configurations.api_keys`).

## Architecture

### System Overview

```
Frontend (React/Vite dev server, /api proxied) → FastAPI → Redis + PostgreSQL
                                              ↓
                                        Celery Worker
                                              ↓
                                   VAD (Silero) + Gemini API
```

Communication pattern: Celery Worker publishes results to Redis Pub/Sub → `ConnectionManager` (redis_listener asyncio task) → WebSocket → Frontend.

### Backend Structure (`backend/`)

- `main.py` — FastAPI app entry, lifespan (init DB, start Redis listener, pre-load VAD)
- `app/core/config.py` — Pydantic Settings, singleton via `@lru_cache`
- `app/core/default_prompt.py` — **Single source of truth** for prompt templates (`DEFAULT_PROMPT_TEMPLATE`, `build_prompt()`)
- `app/api/` — Route handlers: `upload.py`, `transcription.py`, `batch.py`, `model_manager.py`, `history.py`
- `app/celery/task.py` — Single-file transcription Celery task
- `app/celery/batch_task.py` — Batch transcription + recovery Celery tasks
- `app/database/session.py` — Engine, SessionLocal, `init_db()`, `_migrate_add_missing_columns()` (auto-migration, no Alembic)
- `app/database/models.py` — SQLAlchemy ORM: `ModelConfiguration`, `TranscriptionLog`, `BatchJob`
- `app/repositories/` — Repository pattern over ORM models
- `app/services/` — Business logic: `vad/`, `transcription/`, `converter/`, `calculator/`
- `app/provider/google/gemini.py` — All Gemini API interactions (`GeminiClient` + standalone functions)
- `app/websocket/manager.py` — `ConnectionManager` singleton, Redis Pub/Sub listener

### Single-File Transcription Flow

1. `POST /api/v1/upload` → save to `temp_uploads/`
2. Frontend connects `WS /api/v1/ws/{file_uid}` and sends `WebSocketTranscriptionRequest`
3. Celery task `transcribe_media_task`: VAD silence removal → upload to Gemini File API → transcribe → remap timestamps → convert LRC→SRT/VTT/TXT → calculate cost → save `TranscriptionLog` → publish to Redis
4. `ConnectionManager` relays Redis message to frontend WebSocket

### Batch Transcription Flow

1. Multiple files uploaded, shared `batch_id`
2. `WS /api/v1/batch/ws/{batch_id}` + `WebSocketBatchRequest`
3. Celery task `batch_transcribe_task`: create `BatchJob` DB record → upload all files → create Gemini Batch API job → poll until done → process results → store in `results_json` → publish per-file results via Redis
4. `GET /api/v1/batch/pending` + `POST /api/v1/batch/{batch_id}/recover` for Docker-restart recovery

### Frontend Structure (`frontend/src/`)

- `context/TranscriptionContext.jsx` — Core state manager (776 lines): file list, WebSocket connections, single/batch transcription control, batch recovery, download
- `context/` (ModelManager in `components/ModelManager.jsx`) — `ModelManagerProvider` wraps `TranscriptionProvider`
- `constants/modelConfig.js` — Available model options per provider; add new models here
- `pages/` + `components/` + `layouts/` — UI components (new structure, untracked files)

### Key Design Decisions

| Decision | Detail |
|----------|--------|
| Prompt source of truth | `backend/app/core/default_prompt.py` — edit here, not in frontend constants |
| DB migration | `session.py:_migrate_add_missing_columns()` auto-alters tables; no Alembic |
| Celery pool | Uses `gevent` (Windows compatibility; prefork not supported on Windows) |
| VAD lazy-load | Silero VAD loads on first use, pre-warmed at startup via lifespan |
| Batch cost discount | `BATCH_COST_DISCOUNT = 0.5` in `batch_task.py` |
| API keys storage | Stored as JSON string in `model_configurations.api_keys` column |
| `google-genai` version | Must be ≥1.64.0 for Batch API inline requests support |

### Adding a New AI Model

1. Add entry to `frontend/src/constants/modelConfig.js` under the appropriate provider
2. For a new provider: create `backend/app/provider/{provider}/` client module

### pytest Configuration

`pytest.ini` sets `pythonpath = backend`, so tests import from `backend/` directly (e.g., `from app.api import ...`).
