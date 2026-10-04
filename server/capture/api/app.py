from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from capture.api import routes_auth
from capture.config import Settings
from capture.db.base import make_sessionmaker

ROUTERS = (routes_auth.router,)


def create_app(settings: Settings | None = None, session_factory: sessionmaker | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AMCGH Data Capture", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.sessionmaker = session_factory or make_sessionmaker(settings.database_url)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    return app
