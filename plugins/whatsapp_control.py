"""Read and navigate WhatsApp Web using the shared browser session."""
from __future__ import annotations

import json
from datetime import datetime

from core import confirm as confirm_gate, outcome
from plugins import _whatsapp_core as wa


def _format_messages(chat: str, messages: list[dict]) -> str:
    if not messages:
        return "No visible messages were found in the open conversation."
    lines = [f"Visible messages in {chat or 'the open chat'}:"]
    for item in messages:
        prefix = f"{item['metadata']} " if item.get("metadata") else ""
        lines.append(f"{prefix}{item['text']}")
    return outcome.untrusted("whatsapp", "\n".join(lines))


def _announce_send(player, recipient: str, text: str) -> str:
    transport, reason = wa.get()
    if transport is None:
        result = outcome.failed("whatsapp_send", reason)
    else:
        sent, detail = transport.send_message_to(recipient, text)
        result = (
            outcome.done(
                "whatsapp_send",
                submitted_to=detail,
                verified=True,
                delivery="not_claimed",
            )
            if sent else outcome.failed("whatsapp_send", detail, to=recipient)
        )
    if player and hasattr(player, "request_say"):
        player.request_say(
            "Tell the user in their own language whether the confirmed "
            "WhatsApp message was submitted. Do not claim delivery or read "
            "status unless the interface showed it: " + result
        )
    return result


def whatsapp_control(parameters: dict, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    contact = str(params.get("contact", "")).strip()
    query = str(params.get("query", "")).strip()
    text = str(params.get("text", ""))

    if action not in {
        "open", "status", "chats", "search_contacts", "open_chat",
        "search_messages", "read_latest", "notifications", "scroll", "draft", "send",
    }:
        return outcome.failed(
            "whatsapp_control",
            "action must be open, status, chats, search_contacts, open_chat, "
            "search_messages, read_latest, notifications, scroll, draft, or send",
        )
    if action in {"search_contacts", "search_messages"} and not query:
        return outcome.failed("whatsapp_control", "provide a search query")
    if action in {"open_chat", "read_latest", "draft", "send"} and not contact:
        return outcome.failed("whatsapp_control", "provide an exact contact or group name")
    if action in {"draft", "send"} and not text.strip():
        return outcome.failed("whatsapp_control", "provide the complete message text")

    transport, reason = wa.get()
    if transport is None:
        return outcome.failed("whatsapp_control", reason)
    try:
        if action == "open":
            return wa.describe_state(transport.open())
        if action == "status":
            return wa.describe_state(transport.status())
        if action == "chats":
            result = transport.chats(params.get("limit", 20))
            if result["state"] != "ready":
                return wa.describe_state(result)
            chats = result["chats"]
            lines = ["Visible chats:", *chats]
            if result.get("unread"):
                lines.extend(["Unread chats:", *result["unread"]])
            return (
                outcome.untrusted("whatsapp", "\n".join(lines))
                if chats else "No visible WhatsApp chats were found."
            )
        if action == "notifications":
            result = transport.notifications(params.get("limit", 10))
            if result["state"] != "ready":
                return wa.describe_state(result)
            checked_at = datetime.now().astimezone().isoformat()
            items = []
            for entry in result["notifications"]:
                sender, separator, preview = str(entry).partition(":")
                items.append({
                    "source": "WhatsApp",
                    "sender": sender.strip() or "WhatsApp",
                    "text": preview.strip() if separator else str(entry),
                    "timestamp": checked_at,
                    "timestamp_kind": "observed",
                    "unread": True,
                })
            return outcome.untrusted(
                "whatsapp_notifications",
                json.dumps({
                    "checked_at": checked_at,
                    "items": items,
                    "integrations": {"WhatsApp": {"state": "ready"}},
                }, ensure_ascii=False),
            )
        if action == "search_contacts":
            result = transport.search_chats(query)
            if result["state"] != "ready":
                return wa.describe_state(result)
            matches = result["matches"]
            if not matches:
                return "No matching visible WhatsApp chats were found."
            return outcome.untrusted(
                "whatsapp", "Matching chats (not opened):\n" + "\n".join(matches)
            )
        if action == "open_chat":
            result = transport.open_chat(contact)
            if result["state"] != "opened":
                return wa.outcome_for_match(result, "whatsapp_open_chat")
            return (
                outcome.done("whatsapp_open_chat", verified=True)
                + "\n"
                + outcome.untrusted("whatsapp", "Opened chat name: " + result["name"])
            )
        if action == "read_latest":
            opened = transport.open_chat(contact)
            if opened["state"] != "opened":
                return wa.outcome_for_match(opened, "whatsapp_read")
            result = transport.read_latest(params.get("limit", 10))
            if result["state"] != "ready":
                return wa.describe_state(result)
            return _format_messages(result.get("chat", contact), result["messages"])
        if action == "search_messages":
            result = transport.search_visible_messages(query)
            if result["state"] != "ready":
                return wa.describe_state(result)
            return _format_messages(
                result.get("chat", ""), result["matches"],
            )
        if action == "scroll":
            result = transport.scroll(
                str(params.get("direction", "down")).lower(),
                params.get("amount", 500),
            )
            if result["state"] == "scrolled":
                return outcome.done("whatsapp_scroll", verified=True)
            return outcome.failed(
                "whatsapp_scroll",
                "the conversation did not visibly scroll" if result["state"] == "no_movement"
                else f"scroll could not be performed ({result['state']})",
            )
        if action == "draft":
            result = transport.draft_message(contact, text)
            if result["state"] != "drafted":
                return wa.outcome_for_match(result, "whatsapp_draft")
            return outcome.done(
                "whatsapp_draft",
                draft_verified=True,
                sent=False,
            )

        prepared = transport.prepare_message(contact)
        if prepared["state"] != "opened":
            return wa.outcome_for_match(prepared, "whatsapp_send")
        if confirm_gate.pending_title():
            return outcome.failed(
                "whatsapp_send",
                "another action is awaiting confirmation; no message was sent",
            )
        return confirm_gate.request(
            key="whatsapp_send",
            title="Send WhatsApp message?",
            detail=f"To: {prepared['name']}\n\nMessage:\n{text}",
            run=lambda: _announce_send(player, contact, text),
            read_aloud=True,
        )
    except Exception as exc:
        return outcome.failed(
            "whatsapp_control",
            f"the action failed: {type(exc).__name__}: {exc}",
        )


def run(parameters: dict, player=None, session_memory=None) -> str:
    return whatsapp_control(parameters, player=player)


PLUGIN = {
    "name": "whatsapp_control",
    "description": (
        "Open WhatsApp Web and inspect or navigate its visible chats and "
        "messages using HELIOS's shared persistent browser. Use exact contact "
        "or group names; never choose an ambiguous match. Read operations are "
        "limited to currently visible/loaded interface content. Drafting never "
        "sends. Sending requires the exact recipient and full message to be "
        "reviewed and explicitly confirmed by voice or on the HUD. Never bypass QR pairing, MFA, "
        "encryption, or account protections; ask the user to complete login "
        "challenges themselves. Do not claim a message was delivered or read."
    ),
    "tier": "core",
    "brief": "Read WhatsApp chats and unread previews, draft and send after voice or HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "open | status | chats | search_contacts | open_chat | "
                    "search_messages | read_latest | notifications | scroll | draft | send"
                ),
            },
            "contact": {
                "type": "STRING",
                "description": "Exact visible person or group name when an individual chat is required.",
            },
            "query": {
                "type": "STRING",
                "description": "Contact search text or a phrase to find in currently loaded messages.",
            },
            "text": {
                "type": "STRING",
                "description": "Full message text for draft or send; Unicode and line breaks are preserved.",
            },
            "limit": {
                "type": "INTEGER",
                "description": "Maximum visible chats or messages to return (capped at 50).",
            },
            "direction": {
                "type": "STRING",
                "description": "Scroll direction: up or down.",
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount in pixels, bounded to 100-1500.",
            },
        },
        "required": ["action"],
    },
}
