import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse

from app.env import load_dot_env
from app.routers import auth, expenses, categories, reports, link, shared_expenses, settlements, budgets, recurring

load_dot_env()

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SECRET_KEY"],
    max_age=86400 * 7,
    same_site="lax",
    https_only=False,
)


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(auth.router, prefix="/auth")
app.include_router(expenses.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(shared_expenses.router, prefix="/api")
app.include_router(settlements.router, prefix="/api")
app.include_router(budgets.router, prefix="/api")
app.include_router(recurring.router, prefix="/api")
app.include_router(link.router, prefix="/api")

# Must be LAST — serves the built SvelteKit SPA.
# StaticFiles(html=True) only serves index.html at "/" and files that exist on disk;
# it 404s on client-side routes like /login or /dashboard. The catch-all below provides
# the SPA fallback: real files (assets, robots.txt) are served directly, every other
# non-API path returns index.html so the client router can take over.
_BUILD_DIR = Path("web/build")
if _BUILD_DIR.is_dir():
    if (_BUILD_DIR / "_app").is_dir():
        app.mount("/_app", StaticFiles(directory=_BUILD_DIR / "_app"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        candidate = _BUILD_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_BUILD_DIR / "index.html")
