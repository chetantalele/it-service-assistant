import logging, sys, uuid, os
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Request, Security, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from pythonjsonlogger import jsonlogger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"))
logger.addHandler(handler)

app = FastAPI(
    title="IT Service Assistant",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(CORSMiddleware,
    allow_origins=["https://your-workspace.retool.com"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"])

class Payload(BaseModel):
    user_message: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[dict] = {}

@app.get("/health")
async def health():
    return {"status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/api/v1/service-request")
async def receive(payload: Payload, request: Request):
    rid = str(uuid.uuid4())
    logger.info("SERVICE_REQUEST_RECEIVED", extra={
        "request_id": rid,
        "user_message": payload.user_message,
        "user_id": payload.user_id,
        "session_id": payload.session_id,
        "metadata": payload.metadata,
        "source_ip": request.client.host if request.client else "unknown"
    })
    return {
       "request_id": rid,
        "status": "received",
        "message": f"Request received. ID: {rid}",
        "server_timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "phase_1"
    }

@app.exception_handler(422)
async def val_err(request: Request, exc):
    return JSONResponse(status_code=422,
        content={"error": "user_message field is required"})
