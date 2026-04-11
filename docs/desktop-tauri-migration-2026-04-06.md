# Desktop Migration Note (2026-04-06)

## What was added
- New `desktop/` workspace using:
  - Tauri (Rust shell)
  - React + TypeScript (Vite)
  - Tailwind CSS
- Existing web dashboard UI/pages were migrated to desktop routes:
  - `/`, `/markets`, `/backtest`, `/optimize`, `/compare`, `/selector`, `/validate`, `/trades`, `/config`
- Existing API layer/types/components are reused under `desktop/src/lib` and `desktop/src/components`.

## Runtime contract
- Desktop app talks to bot API at `VITE_API_BASE_URL`.
- Default: `http://localhost:8000`.
- Bot service is still managed separately (docker compose).

## Verification done
- `npm install` (desktop)
- `npm run build` (desktop) ✅
- `npm run tauri:dev -- --help` command wiring ✅

## Known limitations
- Native Tauri compile (`cargo check`, `tauri build`) requires local Rust toolchain (`cargo`) on host.
- Bundle optimization is not yet applied (single large JS chunk warning from Vite).
