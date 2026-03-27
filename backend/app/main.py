import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.config import get_settings
from app.config.database import Base, engine
from app.api.routes import router

settings = get_settings()

logging.basicConfig(level=settings.log_level)

# Create tables (will use Alembic migrations later)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Stock Research Engine",
    description="Valuation research engine for stock analysis",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
