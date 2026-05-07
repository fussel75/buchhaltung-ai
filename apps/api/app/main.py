from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import documents, health
from app.services.database import init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    yield


app = FastAPI(
    title="buchhaltung-ai API",
    description="Mandantenfaehige Buchhaltungs-Automation fuer Deutschland.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])

