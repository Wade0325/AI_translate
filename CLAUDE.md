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
- **Local ASR worker** (provider `Local`, VibeVoice + Qwen3-ASR): runs on the **host GPU**, not in Docker — start with `local_worker.bat` (uses `backend/.venv`, consumes the `local_asr` queue via host-published Redis port).

### Run standalone mode (no Docker — basis of the Windows portable release)

```powershell
$env:APP_MODE='standalone'; cd backend; .\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

`APP_MODE=standalone` swaps infrastructure in-process: SQLite (in `data/app.db`) replaces Postgres,
`app/runtime/` ThreadPoolExecutors replace Celery workers, and an asyncio queue (`app/runtime/local_bus.py`)
replaces Redis Pub/Sub. FastAPI also serves `frontend/dist` (SPA fallback) so Vite/Node isn't needed.
Default mode is `docker` — compose never sets `APP_MODE`, so Docker behavior is unchanged.
Standalone reads `.env` only from the data dir (`AIT_DATA_DIR`), never `backend/.env`.

Release packaging: `.\build_release.ps1 -Version vX.Y.Z` → `build\AI_Translate-*-win64.zip`
(small zip; deps are installed on the user's first launch by bundled `uv` per
`backend/requirements-standalone.txt`). Launcher source: `tools/launcher.cs`
(compiled with the built-in .NET Framework `csc.exe` — C# 5 syntax only).
Tag push `v*` triggers `.github/workflows/release.yml` to build + publish the Release.

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
                    Celery Worker (Docker, queue "celery") ── VAD (Silero) + Gemini API
                    Local ASR Worker (host GPU, queue "local_asr") ── VibeVoice + Qwen3-ASR
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
- `app/provider/local/asr.py` — Local provider (VibeVoice diarization + Qwen3-ASR + ForcedAligner); lazy-imported only on the host GPU worker
- `app/celery/cancellation.py` — Redis-flag based cooperative task cancellation (solo pool can't terminate)
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
4. `GET /api/v1/batch/tasks` + `POST /api/v1/batch/{batch_id}/recover` for Docker-restart recovery

### Key Design Decisions

| Decision | Detail |
|----------|--------|
| Dual run modes | `APP_MODE=docker` (default) vs `standalone`; mode branches live in `config.py`, `session.py`, `notifier.py`, `cancellation.py`, `manager.py`, `runtime/dispatch.py` — interfaces stay identical, implementations swap |
| Task bodies | Framework-free in `app/tasks/{transcribe_core,batch_core}.py`; `app/celery/task.py` & `batch_task.py` are thin Celery shims (task names unchanged on the broker) |
| Standalone executor | `app/runtime/executor.py`: `local_asr` pool =1 (mirrors solo GPU worker), `celery` pool =N (mirrors gevent); retry wrapper mirrors `autoretry_for` backoff |
| Timestamps | `models.py` defaults use Python `datetime.now` (not `func.now()`) — local-time semantics identical on Postgres (TZ=Asia/Taipei) and SQLite (whose CURRENT_TIMESTAMP is UTC and would be 8h off) |
| ffmpeg lookup | `app/utils/binaries.py` — PATH by default; `AIT_FFMPEG_DIR` points to bundled binaries in standalone |
| Prompt source of truth | `backend/app/core/default_prompt.py` — edit here, not in frontend constants |
| DB migration | `session.py:_migrate_add_missing_columns()` auto-alters tables; no Alembic |
| Celery pool | Docker worker uses `gevent` (prefork unsupported on Windows); host GPU worker uses `--pool=solo -c 1` |
| Task queues | Provider `Local` → queue `local_asr` (host worker); everything else → default `celery` queue |
| Redelivery safety | `visibility_timeout=12h` in `celery.py`; `insert_log` is an upsert so redelivered tasks re-run cleanly |
| VAD lazy-load | Silero VAD loads on first use, pre-warmed at startup via lifespan |
| Batch/Flex cost discount | `BATCH_COST_DISCOUNT` / `FLEX_COST_DISCOUNT` = 0.5, configurable via Settings env |
| API keys storage | Stored as JSON string in `model_configurations.api_keys` column |
| `google-genai` version | ≥1.64.0 for Batch API inline requests; ≥1.69.0 for Flex `service_tier` |

### Adding a New AI Model

1. Add entry to `frontend/src/constants/modelConfig.js` under the appropriate provider
2. For a new provider: create `backend/app/provider/{provider}/` client module
