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
        "405": _response("Method not allowed", "ErrorResponse"),
        "413": _response("Request body exceeds 64 KiB", "ErrorResponse"),
        "500": _response("Internal server error", "ErrorResponse"),
    }
    profile_id = {
        "name": "profile_id",
        "in": "path",
        "required": True,
        "description": "Profile UUID",
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
                "An API key is generated automatically. Lifecycle endpoints wait for completion."
            ),
        },
        "servers": [{"url": server_url, "description": "Local profile manager"}],
        "tags": [
            {"name": "Health"},
            {"name": "Status"},
            {"name": "Profiles"},
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
            "/api/v1/diagnostics": {
                "get": operation("Get wrapper, binary and runtime diagnostics", "Status", {"200": _response("Diagnostics", "DiagnosticsResponse")})
            },
            "/api/v1/profiles/{profile_id}/open": {
                "post": operation(
                    "Open profile and wait until CDP is ready",
                    "Profiles",
                    {"200": _response("Profile is running", "OpenResponse"), "408": _response("Launch timed out", "ErrorResponse"), "503": _response("Browser worker unavailable", "ErrorResponse")},
                    parameters=[profile_id],
                    requestBody={
                        "required": False,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/OpenOptions"}}},
                    },
                )
            },
            "/api/v1/profiles/{profile_id}/close": {
                "post": operation(
                    "Close profile and wait until stopped",
                    "Profiles",
                    {"200": _response("Profile is stopped", "CloseResponse"), "408": _response("Close timed out", "ErrorResponse"), "503": _response("Browser worker unavailable", "ErrorResponse")},
                    parameters=[profile_id],
                )
            },
            "/api/v1/profiles/{profile_id}/status": {
                "get": operation(
                    "Read cached profile runtime status",
                    "Profiles",
                    {"200": _response("Runtime status", "ProfileStatusResponse"), "503": _response("Browser worker unavailable", "ErrorResponse")},
                    parameters=[profile_id],
                )
            },
            "/api/v1/profiles/close-all": {
                "post": operation(
                    "Close all active profiles without draining the service",
                    "Profiles",
                    {"200": _response("Close results", "CloseAllResponse"), "408": _response("Close timed out", "ErrorResponse"), "503": _response("Browser worker unavailable", "ErrorResponse")},
                )
            },
            "/api/v1/profiles/{profile_id}/preflight": {
                "post": operation(
                    "Validate proxy and identity alignment",
                    "Profiles",
                    {
                        "200": _response("Preflight succeeded", "PreflightResponse"),
                        "502": _response("Proxy or identity resolution failed", "PreflightResponse"),
                    },
                    parameters=[profile_id],
                )
            },
            "/api/v1/profiles": {
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
            "/api/v1/profiles/{profile_id}": {
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
                    "required": ["id", "name", "proxy", "data_dir", "created_at", "updated_at", "status", "cdp_url", "geoip", "timezone", "locale", "release_channel", "browser_version", "humanize", "human_preset"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "name": {"type": "string", "maxLength": 80},
                        "proxy": {"type": ["string", "null"]},
                        "data_dir": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                        "status": {"$ref": "#/components/schemas/RuntimeState"},
                        "cdp_url": {"type": ["string", "null"], "format": "uri"},
                        "geoip": {"type": "boolean"},
                        "timezone": {"type": ["string", "null"], "maxLength": 128},
                        "locale": {"type": ["string", "null"], "maxLength": 35},
                        "release_channel": {"type": "string", "enum": ["stable", "preview"]},
                        "browser_version": {"type": ["string", "null"], "maxLength": 64},
                        "humanize": {"type": "boolean"},
                        "human_preset": {"type": "string", "enum": ["default", "careful"]},
                    },
                },
                "ProfileCreate": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80}, "proxy": {"type": ["string", "null"]}, "geoip": {"type": "boolean", "default": True}, "timezone": {"type": ["string", "null"], "maxLength": 128}, "locale": {"type": ["string", "null"], "maxLength": 35}, "release_channel": {"type": "string", "enum": ["stable", "preview"], "default": "stable"}, "browser_version": {"type": ["string", "null"], "maxLength": 64}, "humanize": {"type": "boolean", "default": False}, "human_preset": {"type": "string", "enum": ["default", "careful"], "default": "default"}},
                },
                "ProfileUpdate": {
                    "type": "object",
                    "additionalProperties": False,
                    "minProperties": 1,
                    "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 80}, "proxy": {"type": ["string", "null"]}, "geoip": {"type": "boolean"}, "timezone": {"type": ["string", "null"], "maxLength": 128}, "locale": {"type": ["string", "null"], "maxLength": 35}, "release_channel": {"type": "string", "enum": ["stable", "preview"]}, "browser_version": {"type": ["string", "null"], "maxLength": 64}, "humanize": {"type": "boolean"}, "human_preset": {"type": "string", "enum": ["default", "careful"]}},
                },
                "OpenOptions": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "Runtime-only native window geometry and native Chromium page zoom in percent. When start_url is supplied, Chromium opens it in app mode without tabs, address bar, or toolbar. Position and size values must be supplied in pairs. Browser viewport emulation is not used.",
                    "properties": {
                        "pos_x": {"type": "integer", "minimum": -100000, "maximum": 100000, "examples": [8]},
                        "pos_y": {"type": "integer", "minimum": -100000, "maximum": 100000, "examples": [8]},
                        "width": {"type": "integer", "minimum": 100, "maximum": 10000, "examples": [470]},
                        "height": {"type": "integer", "minimum": 100, "maximum": 10000, "examples": [349]},
                        "page_zoom": {"type": "number", "minimum": 25, "maximum": 100, "examples": [75]},
                        "start_url": {"type": "string", "format": "uri", "maxLength": 2048, "pattern": "^https?://", "examples": ["https://www.facebook.com"]},
                    },
                },
                "ProfileList": {"type": "object", "required": ["profiles"], "properties": {"profiles": {"type": "array", "items": {"$ref": "#/components/schemas/Profile"}}}},
                "OpenResponse": {"type": "object", "required": ["profileId", "status", "ws", "http", "pid"], "properties": {"profileId": {"type": "string", "format": "uuid"}, "status": {"const": "running"}, "ws": {"type": "string", "format": "uri"}, "http": {"type": "string", "format": "uri"}, "pid": {"type": ["integer", "null"]}}},
                "CloseResponse": {"type": "object", "required": ["profileId", "status"], "properties": {"profileId": {"type": "string", "format": "uuid"}, "status": {"const": "stopped"}}},
                "ProfileStatusResponse": {"type": "object", "required": ["profileId", "status", "http"], "properties": {"profileId": {"type": "string", "format": "uuid"}, "status": {"type": "string", "enum": ["stopped", "starting", "running", "stopping", "error"]}, "http": {"type": ["string", "null"], "format": "uri"}}},
                "CloseAllResponse": {"type": "object", "required": ["closed", "failed"], "properties": {"closed": {"type": "array", "items": {"type": "string", "format": "uuid"}}, "failed": {"type": "array", "items": {"type": "object", "required": ["id", "error"], "properties": {"id": {"type": "string", "format": "uuid"}, "error": {"type": "string"}}}}}},
                "StatusResponse": {"type": "object", "properties": {"data": {"type": "object", "required": ["running", "starting", "worker_alive", "draining"], "properties": {"running": {"type": "integer"}, "starting": {"type": "integer"}, "worker_alive": {"type": "boolean"}, "draining": {"type": "boolean"}}}}},
                "DiagnosticsResponse": {"type": "object", "properties": {"data": {"type": "object", "additionalProperties": True}}},
                "PreflightResponse": {"type": "object", "properties": {"data": {"type": "object", "additionalProperties": True}}},
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
