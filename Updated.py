2 — api-spec
3 — Gateway
4 — Agent setup
5 — System prompt
6 — Tool schema
7 — Tool body
8 — Test
Part 1 — Updated main.py

1
GCP Console → Cloud Functions → click your function → click EDIT
2
Click the main.py tab in the inline editor
3
Select all → delete → paste this entire file:
import sys
import logging
import uuid
from datetime import datetime, timezone

import functions_framework
from flask import jsonify
from pythonjsonlogger import jsonlogger
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
))
logger.addHandler(handler)

# ── Hardcoded config ──────────────────────────────────────────────────
FS_API_KEY         = "YOUR_FRESHSERVICE_API_KEY"
FS_DOMAIN          = "YOUR_SUBDOMAIN"
FS_SERVICE_ITEM_ID = "YOUR_SERVICE_ITEM_ID"

# Hardcoded for testing — replace with lookup later
SELECT_USERS_HARDCODED = [30000353337]

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

# ── Freshservice call ─────────────────────────────────────────────────
def create_freshservice_ticket(
    requester_email: str,
    add_remove_access: str,
    select_user_type: str,
    environment: str,
    access_type: str,
    domain_division: str,
    sub_domain: str
) -> dict:

    url = (
        f"https://{FS_DOMAIN}.freshservice.com"
        f"/api/v2/service_catalog/items/{FS_SERVICE_ITEM_ID}/place_request"
    )

    custom_fields = {
        "add_remove_access": add_remove_access,
        "select_user_type": select_user_type,
        "environment": environment,
        "access_type": access_type,
        "domain_division": domain_division,
        "select_users": SELECT_USERS_HARDCODED,
        "justification": "null"
    }

    # Only include sub_domain when access_type is Domain
    if access_type == "Domain" and sub_domain:
        custom_fields["sub_domain"] = sub_domain

    payload = {
        "email": requester_email,
        "custom_fields": custom_fields
    }

    logger.info("FRESHSERVICE_SENDING", extra={
        "url": url,
        "requester_email": requester_email,
        "access_type": access_type,
        "domain_division": domain_division,
        "sub_domain": sub_domain if access_type == "Domain" else "N/A"
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

    if req.method == "OPTIONS":
        resp = jsonify({})
        for k, v in CORS_HEADERS.items():
            resp.headers[k] = v
        return resp, 204

    if req.method == "GET" and req.path in ("/health", "/"):
        return make_response({
            "status": "healthy",
            "freshservice_configured": bool(FS_API_KEY),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, 200)

    if req.method == "POST" and req.path == "/api/v1/service-request":

        body = req.get_json(silent=True)
        if not body:
            return make_response({"error": "JSON body required"}, 400)

        metadata         = body.get("metadata") or {}
        add_remove       = (metadata.get("add_remove_access") or "").strip()
        user_type        = (metadata.get("select_user_type") or "").strip()
        environment      = (metadata.get("environment") or "").strip()
        access_type      = (metadata.get("access_type") or "").strip()
        domain_division  = (metadata.get("domain_division") or "").strip()
        sub_domain       = (metadata.get("sub_domain") or "").strip()
        requester        = (body.get("user_id") or "").strip()

        # Validate required fields
        missing = [
            f for f, v in {
                "add_remove_access": add_remove,
                "select_user_type": user_type,
                "environment": environment,
                "access_type": access_type,
                "domain_division": domain_division
            }.items() if not v
        ]

        # sub_domain only required when access_type is Domain
        if access_type == "Domain" and not sub_domain:
            missing.append("sub_domain")

        if missing:
            logger.warning("MISSING_FIELDS", extra={"missing": missing})
            return make_response({
                "error": f"Missing fields: {', '.join(missing)}"
            }, 422)

        if not requester:
            return make_response(
                {"error": "user_id is required"}, 422
            )

        rid = str(uuid.uuid4())

        logger.info("TICKET_REQUEST_RECEIVED", extra={
            "request_id": rid,
            "requester": requester,
            "access_type": access_type,
            "domain_division": domain_division
        })

        try:
            fs_response = create_freshservice_ticket(
                requester_email=requester,
                add_remove_access=add_remove,
                select_user_type=user_type,
                environment=environment,
                access_type=access_type,
                domain_division=domain_division,
                sub_domain=sub_domain
            )

            ticket = fs_response.get("service_request", {})
            ticket_id = ticket.get("id", "N/A")

            logger.info("TICKET_CREATED", extra={
                "request_id": rid,
                "ticket_id": ticket_id
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
                    f"{add_remove} access ({access_type}) for "
                    f"{domain_division} has been submitted."
                ),
                "phase": "phase_2"
            }, 200)

        except RuntimeError as e:
            logger.error("FRESHSERVICE_FAILED", extra={
                "request_id": rid, "error": str(e)
            })
            return make_response({
                "error": "Failed to create Freshservice ticket",
                "request_id": rid
            }, 502)

        except Exception as e:
            logger.error("UNEXPECTED_ERROR", extra={
                "request_id": rid, "error": str(e)
            })
            return make_response(
                {"error": "Unexpected error", "request_id": rid}, 500
            )

    return make_response({"error": "Route not found"}, 404)
