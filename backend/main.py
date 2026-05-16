import time

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware

from app.v1.router.consultation import consultation_router
from app.errors.register import register_exception_handlers
from app.utils.logger import get_logger

load_dotenv()

_logger = get_logger("main")

app = FastAPI(title="Criminal Defense Consultation System MVP")


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to every response for performance monitoring."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time, 4))
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(consultation_router, prefix="/api/v1")

register_exception_handlers(app)


@app.on_event("startup")
async def startup_event():
    """Log application startup."""
    _logger.info("Application starting")


@app.get("/")
async def root():
    """Health-check endpoint."""
    _logger.debug("GET / health check")
    return {"message": "Criminal Defense Consultation System MVP - Running"}
