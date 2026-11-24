"""Optional SMS sending through Twilio's official HTTPS API."""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core import confirm as confirm_gate, outcome

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _credentials() -> tuple[str, str, str]:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
    if not account_sid or not auth_token or not from_number:
        raise RuntimeError(
            "SMS is not connected. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER in the process environment."
        )
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account_sid):
        raise ValueError("TWILIO_ACCOUNT_SID does not have the expected account ID format.")
    if not _E164.fullmatch(from_number):
        raise ValueError("TWILIO_FROM_NUMBER must use E.164 format, e.g. +15551234567.")
    return account_sid, auth_token, from_number


def _send_confirmed(expected_sid: str, to: str, text: str) -> str:
    try:
        account_sid, auth_token, from_number = _credentials()
        if account_sid != expected_sid:
            return outcome.failed(
                "sms_send", "the Twilio account changed after confirmation; no SMS was sent",
            )
        data = urlencode({"To": to, "From": from_number, "Body": text}).encode("utf-8")
        token = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
        request = Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
            data=data,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
        message_sid = str(payload.get("sid") or "")
        if not message_sid:
            return outcome.unverified(
                "sms_send", "Twilio did not return a message reference; check the provider before retrying",
                to=to,
            )
        return outcome.done(
            "sms_send", accepted_by_provider=True, message_id=message_sid,
            to=to, delivery="not_claimed",
        )
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read(16 * 1024).decode("utf-8"))
        except (ValueError, OSError):
            payload = {}
        return outcome.failed(
            "sms_send",
            f"Twilio rejected the request (HTTP {exc.code}, code {payload.get('code', 'unknown')})",
            to=to,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return outcome.unverified(
            "sms_send",
            f"the provider response could not be verified ({type(exc).__name__}); "
            "check Twilio before retrying to avoid a duplicate",
            to=to,
        )


def _account_status(account_sid: str, auth_token: str, from_number: str) -> str:
    token = base64.b64encode(
        f"{account_sid}:{auth_token}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except HTTPError as exc:
        return outcome.failed(
            "sms_status",
            f"Twilio rejected the account check (HTTP {exc.code}); verify the credentials.",
        )
    except (URLError, TimeoutError, OSError) as exc:
        return outcome.unverified(
            "sms_status",
            f"Twilio connection could not be verified ({type(exc).__name__}).",
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return outcome.unverified(
            "sms_status", f"Twilio returned an invalid account response ({type(exc).__name__}).",
        )
    if not isinstance(payload, dict):
        return outcome.unverified(
            "sms_status", "Twilio returned an unexpected account response.",
        )
    if str(payload.get("sid") or "") != account_sid:
        return outcome.unverified(
            "sms_status", "Twilio returned a different account ID; connection is unverified.",
        )
    return outcome.done(
        "sms_status", provider="Twilio", connected=True,
        account_status=payload.get("status", "unknown"),
        from_number=from_number,
    )


def sms_control(parameters: dict | None = None, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    if action not in {"status", "send"}:
        return outcome.failed("sms_control", "action must be status or send")
    try:
        account_sid, _auth_token, from_number = _credentials()
    except (RuntimeError, ValueError) as exc:
        return outcome.failed("sms_control", str(exc))

    if action == "status":
        return _account_status(account_sid, _auth_token, from_number)

    to = str(params.get("to", "")).strip()
    text = str(params.get("text", ""))
    if not _E164.fullmatch(to):
        return outcome.failed(
            "sms_control", "provide the recipient's full E.164 number, e.g. +15551234567",
        )
    if not text.strip():
        return outcome.failed("sms_control", "provide the complete SMS text")
    if len(text) > 1600:
        return outcome.failed("sms_control", "SMS text exceeds the 1600-character limit")
    if confirm_gate.pending_title():
        return outcome.failed(
            "sms_control", "another action is awaiting confirmation; no SMS was sent",
        )
    return confirm_gate.request(
        key="sms_send",
        title="Send SMS?",
        detail=f"From: {from_number}\nTo: {to}\n\nMessage:\n{text}",
        run=lambda: _send_confirmed(account_sid, to, text),
        read_aloud=True,
    )


def run(parameters: dict, player=None, session_memory=None) -> str:
    return sms_control(parameters, player=player)


PLUGIN = {
    "name": "sms_control",
    "description": (
        "Check the Twilio SMS connection and send an SMS to a full E.164 phone "
        "number using the official HTTPS API. Sending always requires explicit "
        "voice or HUD confirmation showing sender, recipient and exact text. "
        "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER "
        "outside the chat and application config. This plugin sends outbound "
        "SMS only; inbound SMS needs a separately configured, public HTTPS "
        "Twilio webhook and is not claimed to be connected. A provider "
        "acceptance is not a delivery receipt."
    ),
    "tier": "core",
    "brief": "Send SMS through Twilio only after explicit voice or HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | send"},
            "to": {"type": "STRING", "description": "Recipient phone number in full E.164 format."},
            "text": {"type": "STRING", "description": "Complete SMS message text."},
        },
        "required": ["action"],
    },
}
