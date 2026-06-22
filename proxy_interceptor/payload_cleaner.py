"""Helpers for extracting JSON payloads from mitmproxy flows."""

from __future__ import annotations

import json
from typing import Any

from mitmproxy import http

JSON_PREFIXES = (")]}'", "while(1);", "for(;;);")


def is_json_response(flow: http.HTTPFlow) -> bool:
    """Return True when a flow response looks like JSON data."""

    if not flow.response:
        return False

    content_type = flow.response.headers.get("content-type", "").lower()
    if "json" in content_type:
        return True

    path = flow.request.path.lower()
    return path.endswith(".json") or "json" in path


def decode_json_body(flow: http.HTTPFlow) -> dict[str, Any] | list[Any] | None:
    """Decode a response body into JSON without raising parser errors."""

    if not flow.response:
        return None

    body = flow.response.get_text(strict=False)
    if not body:
        return None

    cleaned_body = _strip_known_prefixes(body.strip())
    if not cleaned_body:
        return None

    try:
        parsed = json.loads(cleaned_body)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict | list):
        return parsed
    return None


def _strip_known_prefixes(body: str) -> str:
    for prefix in JSON_PREFIXES:
        if body.startswith(prefix):
            return body[len(prefix) :].lstrip()
    return body

