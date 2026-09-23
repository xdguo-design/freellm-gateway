# React / TypeScript admin console

The Gateway admin UI is implemented in `web/` with React, TypeScript and Vite.

## Development

Run the Python gateway on port 8000, then:

```bash
npm install --prefix web
npm run dev --prefix web
```

Vite proxies `/api`, `/v1` and `/health` to `http://127.0.0.1:8000`.

## Validation

```bash
npm run typecheck --prefix web
npm run test --prefix web
npm run build --prefix web
```

The production build is written to:

```text
freellm_gateway/static/admin/
```

That single production bundle is shared by:

- FastAPI `/admin/`
- FreeLLM Studio / Tauri
- Python package/release builds

The generated bundle is intentionally ignored by Git. Build it before packaging
or running the desktop release build.

## Legacy fallback

The previous single-file console remains available at:

```text
/admin/legacy
```

If a React production bundle has not been built, `/admin` falls back to the
legacy console so Python-only development remains usable.

## Source layout

```text
web/src/
  api/          API client/auth handling
  components/   shared shell/navigation
  lib/          formatting and reusable logic
  pages/        page-level features
  types.ts      typed API contracts
  styles.css    shared visual system
```

New frontend work should go into `web/src`; do not add new business behavior to
`freellm_gateway/templates/admin.html`.
