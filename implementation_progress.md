# Micromix Implementation Progress

## Scope
Implementing P0 fixes from `micromix_codebase_exploration.md` incrementally with minimal-risk changes.

## Running Log
- [completed] Started P0 implementation pass.
- [completed][P0-1 Router inconsistency] Updated `Website/frontend/src/main.js` to import `./router.js` explicitly instead of `./router`.
  - What changed: explicit router import path now points to Vue 2 router file.
  - Why: avoids ambiguous module resolution with legacy `src/router/index.js` (Vue 3 API) and prevents accidental build/runtime mismatch.
  - Risks/follow-up: `Website/frontend/src/router/index.js` remains as legacy artifact; safe cleanup is to remove/archive it in a dedicated pass once confirmed unused across tooling.

- [completed][P0-2 Export crash] Updated CSV export fallback logic in `Website/backend/app.py` (`df_to_csv`).
  - What changed: CSV export now safely checks whether `filtered` dataframe exists before dereferencing it.
  - Why: prevents KeyError crash when no filtered dataframe is present for a session.
  - Risks/follow-up: none significant; behavior remains unchanged for filtered sessions.

- [completed][P0-3 Environment-based host/url config] Replaced key hardcoded service endpoints with env-driven defaults.
  - Files changed:
    - `Website/frontend/src/App.vue`: `backend_url` now from `VUE_APP_WEBSITE_BACKEND_URL` with existing localhost fallback.
    - `Website/backend/plugins/Heatmap.py`: heatmap URL now from `HEATMAP_FRONTEND_URL` with existing localhost fallback.
    - `Website/backend/app.py`: MongoDB host/port now from `MONGODB_HOST`/`MONGODB_PORT` with existing defaults.
    - `Heatmap/backend/app.py`: MongoDB host/port now from `MONGODB_HOST`/`MONGODB_PORT` with existing defaults.
    - `Heatmap/frontend/src/components/deckglCanvas.vue`: heatmap backend base URL now from `VUE_APP_HEATMAP_BACKEND_URL`; settings fetch now uses it.
    - `Heatmap/frontend/src/components/mainMenu.vue`: settings save endpoint now uses `VUE_APP_HEATMAP_BACKEND_URL`.
  - Why: improves portability and deployment consistency across local/container/prod environments.
  - Risks/follow-up: env vars must be supplied per environment; defaults preserve current behavior.

- [completed][P0-4 Plugin ID consistency cleanup] Normalized default plugin IDs to string IDs in `Website/backend/app.py`.
  - What changed: `PRE_CONFIGURED_PLUGINS` now uses string IDs aligned with frontend `plugins.json` (`Clustergrammer`, `Heatmap`) rather than unrelated ObjectIds.
  - Why: reduces mismatch between frontend plugin `_id` strings and backend defaults, avoiding fragile ID assumptions.
  - Risks/follow-up: existing historical DB entries may still contain legacy ObjectIds; migration/backward-compatibility normalization can be added later if needed.

- [completed][P0-5 transform_dataframe import/path hardening] Added safe import guard in `Website/backend/process_file.py`.
  - What changed: `transform_dataframe` import is now wrapped in `try/except ImportError`; when missing, transformation is skipped with warning instead of crashing upload/update.
  - Why: scanned codebase does not include `transform_dataframe.py`; this prevents runtime failure on transformation-enabled requests.
  - Risks/follow-up: transformation requests silently degrade (with server warning). Best follow-up is to restore the missing module or explicitly disable/remove transformation option in UI until implemented.

## TODO / Follow-up
- Optional cleanup: remove or archive `Website/frontend/src/router/index.js` Vue 3 artifact after confirming no tooling references.
- Add environment variable documentation for Website/Heatmap frontend and backend services.
- Optional DB migration utility to normalize legacy plugin IDs in existing documents.
- Restore or replace missing `transform_dataframe` implementation for full transformation feature parity.
