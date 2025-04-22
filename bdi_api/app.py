import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from starlette import status
from starlette.responses import JSONResponse
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

import bdi_api
from bdi_api.examples import v0_router
from bdi_api.s1.exercise import s1
from bdi_api.s4.exercise import s4
from bdi_api.s7.exercise import s7
from bdi_api.s8.exercise import s8 as s8_router  # S8 router is already included
from bdi_api.settings import Settings

logger = logging.getLogger("uvicorn.error")

# Load environment variables from .env file
load_dotenv()
print(f"Loaded DATABASE_URL: {os.getenv('DATABASE_URL')}")

# FastAPI app setup
app = FastAPI(
    title="Big Data Infrastructure API",
    description="Big Data Infrastructure Course API.",
    version="0.0.1",
)

# Include routers
app.include_router(v0_router)
app.include_router(s1)
app.include_router(s4)
app.include_router(s7)
app.include_router(s8_router)

# Startup and shutdown event handlers
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    try:
        logger.info("Starting up...")

        # Test database connection
        engine = create_engine(os.getenv("DATABASE_URL"))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful")

        yield
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("Shutting down...")

# Assign the lifespan to the app
app.router.lifespan_context = lifespan

# Health check endpoint
@app.get("/health", response_class=JSONResponse)
async def health_check():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "healthy"},
    )
