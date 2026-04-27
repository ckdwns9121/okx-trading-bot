# Repository Guidelines

## Project Structure & Module Organization
This repo has three apps plus docs. `bot/` contains the FastAPI API, Alembic migrations, trading strategies in `bot/strategies/`, and backend tests in `bot/tests/`. `dashboard/` is the Next.js web UI with routes in `dashboard/src/app/`, shared components in `dashboard/src/components/`, and API helpers in `dashboard/src/lib/`. `desktop/` is the Tauri client with React pages in `desktop/src/pages/`, shared UI in `desktop/src/components/`, and native code in `desktop/src-tauri/`. Store runbooks and strategy notes in `docs/`.

## Build, Test, and Development Commands
- `docker compose up -d --build` — start PostgreSQL, the bot API and dashboard.
- `cd bot && python -m pip install -e '.[dev]' && pytest` — install backend dev deps and run tests.
- `cd bot && uvicorn app.main:app --reload --port 8000` — run the API locally.
- `cd dashboard && npm install && npm run dev` — start the Next.js app on port 3000.
- `cd dashboard && npm run build && npm run lint` — production build and lint.
- `cd desktop && npm install && npm run tauri:dev` — run the desktop app.
- `cd desktop && npm run build` — type-check and bundle the desktop UI.

## Coding Style & Naming Conventions
Match existing code before introducing new patterns. Python uses 4-space indentation, type hints, and `snake_case`; keep route handlers thin and move logic into `app/core` or `strategies`. TypeScript/React uses 2-space indentation, `PascalCase` components, and `camelCase` helpers. Reuse existing API utilities instead of duplicating request code.

## Testing Guidelines
Backend tests live in `bot/tests/test_*.py` and use `pytest` with `pytest-asyncio`. Update tests whenever API contracts, scoring, replay policy, or risk logic changes. For frontend changes, at minimum run `npm run build` in `dashboard/` and `desktop/`, plus `npm run lint` in `dashboard/`. Include the exact verification commands in your PR.

## Commit & Pull Request Guidelines
Recent commits use short, imperative, why-first subjects such as `Prevent Tauri dev from binding to a stale Vite server`. Keep commits scoped to one app or behavior change. PRs should summarize user impact, touched areas (`bot`, `dashboard`, `desktop`), env or migration changes, and include screenshots for UI updates.

## Security & Configuration Tips
Never commit live OKX credentials or `.env` files. Start from `.env.example`, keep `OKX_MODE=demo` outside production, and document any new required variables in the root README and the relevant app README.
