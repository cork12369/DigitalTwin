from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routes import analysis, health, sessions, tokens, training

settings = get_settings()

app = FastAPI(title="Digital Twin API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(health.router)
app.include_router(analysis.router)
app.include_router(tokens.router)
app.include_router(sessions.router)
app.include_router(training.router)
app.include_router(training.admin_router)
