import os
import sys
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pythonjsonlogger import jsonlogger

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
))
logger.addHandler(handler)

app = FastAPI(
    title="IT Service Assistant",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://garage.dev.retool.colpal.cloud"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"]
)

class Payload(BaseModel):
    user_message: str = Field(..., min_length=1, max_length=5000)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[dict] = {}
    # Agent fills these inside metadata automatically:
    # metadata.get("category") → "Hardware", "Software", "Network" etc
    # metadata.get("urgency")  → "Low", "Medium", "High", "Critical"
    # metadata.get("device")   → "MacBook Pro", "Windows laptop" etc
    # metadata.get("source")   → "retool_agent"

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/v1/service-request")
async def receive(payload: Payload, request: Request):
    rid = str(uuid.uuid4())

    urgency_map = {
        "Low": 1,
        "Medium": 2,
        "High": 3,
        "Critical": 4
    }
    priority = urgency_map.get(
        payload.metadata.get("urgency", "Medium"), 2
    )

    logger.info("AGENT_REQUEST_RECEIVED", extra={
        "request_id": rid,
        "user_message": payload.user_message,
        "user_id": payload.user_id,
        "session_id": payload.session_id,
        "category": payload.metadata.get("category"),
        "urgency": payload.metadata.get("urgency"),
        "device": payload.metadata.get("device"),
        "source": payload.metadata.get("source"),
        "source_ip": request.client.host if request.client else "unknown"
    })

    return {
        "request_id": rid,
        "status": "received",
        "message": f"Ticket will be created. ID: {rid}",
        "priority_mapped": priority,
        "server_timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "phase_1"
    }

@app.exception_handler(422)
async def val_err(request: Request, exc):
    return JSONResponse(
        status_code=422,
        content={"error": "user_message field is required"}
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
