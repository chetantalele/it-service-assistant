import os
import sys
import logging
import uuid
from datetime import datetime, timezone

import functions_framework
from flask import request, jsonify
from pythonjsonlogger import jsonlogger
import requests

# ── Logging ──────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
))
logger.addHandler(handler)

# ── Configuration — all values hardcoded ─────────────────────────────
# Replace each value below with your actual values
FS_API_KEY         = "your_freshservice_api_key_here"
FS_DOMAIN          = "yourcompany"          # just the subdomain, no .freshservice.com
FS_SERVICE_ITEM_ID = "42"                   # number from URL when editing your form

# ── CORS ──────────────────────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "https://garage.dev.retool.colpal.cloud",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "*"
}

def make_response(data, status_code):
    resp = jsonify(data)
    for k, v in CORS_HEADERS.items():
        resp.headers[k] = v
    return resp, status_code

# ── Freshservice API call ─────────────────────────────────────────────
def create_freshservice_ticket(
    requester_email: str,
    domain: str,
    database: str,
    role: str,
    user_email: str
) -> dict:

    url = (
        f"https://{FS_DOMAIN}.freshservice.com"
        f"/api/v2/service_catalog/items/{FS_SERVICE_ITEM_ID}/place_request"
    )

    payload = {
        "email": requester_email,
        "quantity": 1,
        "custom_fields": {
            "domain": domain,
            "database": database,
            "role": role,
            "user_email": user_email
        }
    }

    logger.info("FRESHSERVICE_SENDING", extra={
        "url": url,
        "requester_email": requester_email,
        "domain": domain,
        "database": database,
        "role": role,
        "user_email": user_email
    })

    response = requests.post(
        url,
        json=payload,
        auth=(FS_API_KEY, "X"),
        timeout=15
    )

    logger.info("FRESHSERVICE_RESPONSE", extra={
        "status_code": response.status_code,
        "body": response.text[:500]
    })

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Freshservice returned {response.status_code}: {response.text}"
        )

    return response.json()

# ── Entry point ───────────────────────────────────────────────────────
@functions_framework.http
def entry_point(req):

    # CORS preflight
    if req.method == "OPTIONS":
        resp = jsonify({})
        for k, v in CORS_HEADERS.items():
            resp.headers[k] = v
        return resp, 204

    # GET /health
    if req.method == "GET" and req.path in ("/health", "/"):
        return make_response({
            "status": "healthy",
            "freshservice_configured": bool(FS_API_KEY),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, 200)

    # POST /api/v1/service-request
    if req.method == "POST" and req.path == "/api/v1/service-request":

        body = req.get_json(silent=True)
        if not body:
            return make_response({"error": "JSON body required"}, 400)

        # Extract the 4 fields
        metadata   = body.get("metadata") or {}
        domain     = (metadata.get("domain") or "").strip()
        database   = (metadata.get("database") or "").strip()
        role       = (metadata.get("role") or "").strip()
        user_email = (metadata.get("user_email") or "").strip()
        requester  = (body.get("user_id") or "").strip()

        # Validate all 4 are present
        missing = [
            f for f, v in {
                "domain": domain,
                "database": database,
                "role": role,
                "user_email": user_email
            }.items() if not v
        ]

        if missing:
            logger.warning("MISSING_FIELDS", extra={"missing": missing})
            return make_response({
                "error": f"Missing fields: {', '.join(missing)}",
                "hint": "Agent must collect all 4 fields before calling this endpoint"
            }, 422)

        if not requester:
            return make_response(
                {"error": "user_id (requester email) is required"}, 422
            )

        rid = str(uuid.uuid4())

        logger.info("TICKET_REQUEST_RECEIVED", extra={
            "request_id": rid,
            "requester": requester,
            "domain": domain,
            "database": database,
            "role": role,
            "user_email": user_email
        })

        try:
            fs_response = create_freshservice_ticket(
                requester_email=requester,
                domain=domain,
                database=database,
                role=role,
                user_email=user_email
            )

            ticket = fs_response.get("service_request", {})
            ticket_id = ticket.get("id", "N/A")

            logger.info("TICKET_CREATED", extra={
                "request_id": rid,
                "ticket_id": ticket_id,
                "requester": requester
            })

            return make_response({
                "request_id": rid,
                "status": "ticket_created",
                "ticket_id": ticket_id,
                "ticket_url": (
                    f"https://{FS_DOMAIN}.freshservice.com"
                    f"/helpdesk/tickets/{ticket_id}"
                ),
                "message": (
                    f"Ticket #{ticket_id} raised successfully. "
                    f"{role} access to {database} on {domain} domain "
                    f"for {user_email} has been submitted. "
                    f"An email confirmation will be sent shortly."
                ),
                "phase": "phase_2"
            }, 200)

        except RuntimeError as e:
            logger.error("FRESHSERVICE_FAILED", extra={
                "request_id": rid,
                "error": str(e)
            })
            return make_response({
                "error": "Failed to create Freshservice ticket",
                "request_id": rid,
                "hint": "Check GCP logs for FRESHSERVICE_RESPONSE entry"
            }, 502)

        except Exception as e:
            logger.error("UNEXPECTED_ERROR", extra={
                "request_id": rid,
                "error": str(e)
            })
            return make_response(
                {"error": "Unexpected error", "request_id": rid}, 500
            )

    return make_response({"error": "Route not found"}, 404)
