from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import dashboard, turma_report
from app.scheduler import start_scheduler
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield


app = FastAPI(title="Saldo+ API", lifespan=lifespan)

# Configuração de CORS liberando o Live Server (localhost e 127.0.0.1) e a origem das configurações
origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    settings.frontend_origin,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(origins)), # Remove duplicadas caso settings.frontend_origin seja igual
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(turma_report.router)


@app.get("/health")
def health():
    return {"status": "ok"}