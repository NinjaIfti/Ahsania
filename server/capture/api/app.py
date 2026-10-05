from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from capture.api import routes_admin, routes_auth, routes_files, routes_records, routes_templates
from capture.config import Settings
from capture.db.base import make_sessionmaker
from capture.extraction.read_id import IdReader

ROUTERS = (
    routes_auth.router,
    routes_templates.router,
    routes_admin.router,
    routes_records.router,
    routes_files.router,
)


def create_app(settings: Settings | None = None, session_factory: sessionmaker | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AMCGH Data Capture", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.sessionmaker = session_factory or make_sessionmaker(settings.database_url)
    app.state.id_reader = IdReader(settings)  # loads PaddleOCR on the first read

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    return app
