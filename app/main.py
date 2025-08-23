from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging
logger = logging.getLogger(__name__)

# routers
from app.api.public import router as public_router
from app.api.recall import router as recall_router

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# todo : handle cors

# Configure root logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# Ensure root logger outputs DEBUG even if uvicorn initialized handlers earlier
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Ensure there is at least one handler on the root logger so app loggers emit
if not root_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root_logger.addHandler(_handler)

logging.captureWarnings(True)

# Make uvicorn loggers verbose too
logging.getLogger("uvicorn").setLevel(logging.DEBUG)
logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)
logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)

# Ensure our app.* loggers are DEBUG
logging.getLogger("app").setLevel(logging.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include all API routes
app.include_router(public_router)
app.include_router(recall_router)

@app.on_event("startup")
async def on_startup():
    logger.info("Application startup")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Application shutdown")


