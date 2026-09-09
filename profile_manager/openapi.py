"""OpenAPI contract and Swagger UI for the local profile manager API."""

from __future__ import annotations

from typing import Any

from . import __version__


def _response(description: str, schema: str | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"description": description}
    if schema:
        response["content"] = {
            "application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}
        }
    return response


def build_openapi(server_url: str) -> dict[str, Any]:
    """Return the complete OpenAPI 3.1 contract for implemented routes."""
    error_responses = {
        "400": _response("Invalid request", "ErrorResponse"),
        "401": _response("Missing or invalid API key", "ErrorResponse"),
        "404": _response("Resource not found", "ErrorResponse"),
        "413": _response("Request body exceeds 64 KiB", "ErrorResponse"),
        "429": _response("Request rate limit exceeded", "ErrorResponse"),
        "500": _response("Internal server error", "ErrorResponse"),
    }
    profile_id = {
        "name": "profile_id",
        "in": "path",
        "required": True,
        "description": "Profile UUID",
        "schema": {"type": "string", "format": "uuid"},
    }
    operation_id = {
        "name": "operation_id",
        "in": "path",
        "required": True,
        "description": "Lifecycle operation UUID",
        "schema": {"type": "string", "format": "uuid"},
    }

    def operation(summary: str, tag: str, responses: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "summary": summary,
            "tags": [tag],
            "security": [{"bearerAuth": []}, {"apiKeyAuth": []}],
            "responses": {**responses, **error_responses},
            **extra,
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "CloakBrowser Profile Manager API",
            "version": __version__,
            "description": (
                "Localhost API for persistent profile CRUD, browser lifecycle, and CDP automation. "
                "Authentication is disabled when no API key is configured. Prefer asynchronous v1 lifecycle endpoints."
            ),
        },
        "servers": [{"url": server_url, "description": "Local profile manager"}],
        "tags": [
            {"name": "Health"},
            {"name": "Status"},
            {"name": "Profiles"},
            {"name": "Operations"},
        ],
        "paths": {
            "/health": {
                "get": operation("Compatibility health check", "Health", {"200": _response("Healthy", "HealthOk")})
            },
            "/health/live": {
                "get": operation("Liveness check", "Health", {"200": _response("HTTP server is alive", "HealthAlive")})
            },
            "/health/ready": {
                "get": operation(
                    "Readiness check",
                    "Health",
                    {
                        "200": _response("Service is ready", "HealthReady"),
                        "503": _response("Store, worker, or browser supervisor is not ready", "HealthNotReady"),
                    },
                )
            },
            "/api/v1/status": {
                "get": operation("Get service capacity and runtime status", "Status", {"200": _response("Current status", "StatusResponse")})
            },
            "/api/v1/operations/{operation_id}": {
                "get": operation(
                    "Get lifecycle operation",
                    "Operations",
                    {"200": _response("Operation state", "OperationResponse")},
                    parameters=[operation_id],
                )
            },
            "/api/v1/profiles/{profile_id}/operations/open": {
                "post": operation(
                    "Open profile asynchronously",
                    "Operations",
                    {"202": _response("Operation accepted", "OperationResponse")},
                    parameters=[profile_id],
                    description="Returns Location and Retry-After headers. Poll the operation until succeeded or failed.",
                    requestBody={
                        "required": False,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/OpenOptions"}}},
                    },
                )
            },
            "/api/v1/profiles/{profile_id}/operations/close": {
                "post": operation(
                    "Close profile asynchronously",
                    "Operations",
                    {"202": _response("Operation accepted", "OperationResponse")},
                    parameters=[profile_id],
                )
            },
            "/api/profiles": {
                "get": operation("List profiles", "Profiles", {"200": _response("Profile list", "ProfileList")}),
                "post": operation(
                    "Create profile",
                    "Profiles",
                    {"201": _response("Created profile", "Profile")},
                    requestBody={
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProfileCreate"}}},
                    },
                ),
            },
            "/api/profiles/{profile_id}": {
                "get": operation("Get profile", "Profiles", {"200": _response("Profile", "Profile")}, parameters=[profile_id]),
                "patch": operation(
                    "Update profile name or proxy",
                    "Profiles",
                    {"200": _response("Updated profile", "Profile")},
                    parameters=[profile_id],
                    requestBody={
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProfileUpdate"}}},
                    },
                ),
                "delete": operation(
                    "Delete stopped profile and its data",
                    "Profiles",
                    {"200": _response("Profile deleted", "DeleteResponse")},
                    parameters=[profile_id],
                ),
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "description": "API key as Bearer token"},
                "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            },
            "schemas": {
                "RuntimeState": {"type": "string", "enum": ["Stopped", "Starting", "Running", "Stopping", "Error"]},
                "Profile": {
                    "type": "object",
                    "required": ["id", "name", "proxy", "data_dir", "created_at", "updated_at", "status", "cdp_url"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "name": {"type": "string", "maxLength": 80},
                        "proxy": {"type": ["string", "null"]},
                        "data_dir": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                        "status": {"$ref": "#/components/schemas/RuntimeState"},
                        "cdp_url": {"type": ["string", "null"], "format": "uri"},
                    },
                },
                "ProfileCreate": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80}, "proxy": {"type": ["string", "null"]}},
                },
                "ProfileUpdate": {
                    "type": "object",
                    "minProperties": 1,
                    "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80}, "proxy": {"type": ["string", "null"]}},
                },
                "OpenOptions": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Runtime-only native window geometry and native Chromium page zoom in percent. Position and size values must be supplied in pairs. Browser viewport emulation is not used.",
                    "properties": {
                        "pos_x": {"type": "integer", "minimum": -100000, "maximum": 100000, "examples": [8]},
                        "pos_y": {"type": "integer", "minimum": -100000, "maximum": 100000, "examples": [8]},
                        "width": {"type": "integer", "minimum": 100, "maximum": 10000, "examples": [470]},
                        "height": {"type": "integer", "minimum": 100, "maximum": 10000, "examples": [349]},
                        "page_zoom": {"type": "number", "minimum": 25, "maximum": 100, "examples": [75]},
                    },
                },
                "ProfileList": {"type": "object", "required": ["profiles"], "properties": {"profiles": {"type": "array", "items": {"$ref": "#/components/schemas/Profile"}}}},
                "Operation": {
                    "type": "object",
                    "required": ["id", "profile_id", "kind", "status", "created_at"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "profile_id": {"type": "string", "format": "uuid"},
                        "kind": {"type": "string", "enum": ["open", "close"]},
                        "status": {"type": "string", "enum": ["queued", "running", "succeeded", "failed"]},
                        "created_at": {"type": "string", "format": "date-time"},
                        "started_at": {"type": ["string", "null"], "format": "date-time"},
                        "completed_at": {"type": ["string", "null"], "format": "date-time"},
                        "result": {"type": ["object", "null"], "additionalProperties": True},
                        "error": {"type": ["object", "null"], "additionalProperties": True},
                    },
                },
                "OperationResponse": {"type": "object", "required": ["data"], "properties": {"data": {"$ref": "#/components/schemas/Operation"}}},
                "StatusResponse": {"type": "object", "properties": {"data": {"type": "object", "required": ["running", "starting", "active_operations", "worker_alive", "draining"], "properties": {"running": {"type": "integer"}, "starting": {"type": "integer"}, "active_operations": {"type": "integer"}, "worker_alive": {"type": "boolean"}, "draining": {"type": "boolean"}}}}},
                "HealthOk": {"type": "object", "properties": {"status": {"const": "ok"}}},
                "HealthAlive": {"type": "object", "properties": {"status": {"const": "alive"}}},
                "HealthReady": {"type": "object", "properties": {"status": {"const": "ready"}}},
                "HealthNotReady": {"type": "object", "properties": {"status": {"const": "not_ready"}}},
                "DeleteResponse": {"type": "object", "properties": {"deleted": {"const": True}}},
                "ErrorResponse": {"type": "object", "properties": {"error": {"type": "object", "required": ["code", "message", "request_id"], "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "request_id": {"type": "string", "format": "uuid"}}}}},
            },
        },
    }


SWAGGER_UI_HTML = """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>CloakBrowser Profile Manager API</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\">
<style>body{margin:0;background:#fafafa}</style></head>
<body><div id=\"swagger-ui\"></div>
<script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
<script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui',deepLinking:true,persistAuthorization:true,displayRequestDuration:true});</script>
</body></html>"""
