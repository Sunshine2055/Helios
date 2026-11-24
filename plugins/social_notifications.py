"""Collect currently visible unread social notifications for the dashboard."""
from __future__ import annotations

import json
from datetime import datetime

from core import outcome


def run(parameters: dict, player=None, session_memory=None) -> str:
    checked_at = datetime.now().astimezone().isoformat()
    items = []
    integrations = {}

    try:
        from plugins import _whatsapp_core as wa

        transport, reason = wa.get()
        if transport is None:
            integrations["WhatsApp"] = {"state": "unavailable", "detail": reason}
        else:
            result = transport.notifications(10)
            integrations["WhatsApp"] = {"state": result.get("state", "unknown")}
            for entry in result.get("notifications", []):
                sender, separator, preview = str(entry).partition(":")
                items.append({
                    "source": "WhatsApp",
                    "sender": sender.strip() or "WhatsApp",
                    "text": preview.strip() if separator else str(entry),
                    "timestamp": checked_at,
                    "timestamp_kind": "observed",
                    "unread": True,
                })
    except Exception as exc:
        integrations["WhatsApp"] = {
            "state": "error",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    try:
        from plugins import _facebook_core as facebook

        result = facebook.notifications(10)
        integrations["Facebook"] = {"state": result.get("state", "unknown")}
        items.extend(result.get("items", []))
    except Exception as exc:
        integrations["Facebook"] = {
            "state": "error",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    payload = {
        "checked_at": checked_at,
        "items": items,
        "integrations": integrations,
    }
    return outcome.untrusted("social_notifications", json.dumps(payload, ensure_ascii=False))


PLUGIN = {
    "name": "social_notifications",
    "description": (
        "Check currently visible unread WhatsApp chats and Facebook notifications "
        "in the shared signed-in browser, and publish their sender, preview, and "
        "available timestamp to the HELIOS dashboard. This is an on-demand check, "
        "not a background real-time feed."
    ),
    "tier": "core",
    "brief": "Check visible unread WhatsApp and Facebook notifications.",
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}
