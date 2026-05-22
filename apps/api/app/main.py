from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware import AuthMiddleware
from app.routes import auth, documents, health, masterdata, users
from app.services.auth import bootstrap_initial_admin
from app.services.database import init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    bootstrap_initial_admin()
    yield


app = FastAPI(
    title="buchhaltung-ai API",
    description="Mandantenfähige Buchhaltungs-Automation für Deutschland.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(masterdata.router, prefix="/api/masterdata", tags=["masterdata"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])

