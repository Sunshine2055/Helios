"""Voice-confirmation state machine for WhatsApp sends.

This module is deliberately adapter-based: the application supplies its existing
TTS, STT and WhatsApp transport. It never opens a second browser or microphone.
No send is possible until TTS completion has been acknowledged and an
unambiguous affirmative transcript is received while WAITING_FOR_VOICE.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class ConfirmationState(str, Enum):
    IDLE = "IDLE"
    PREPARING_MESSAGE = "PREPARING_MESSAGE"
    SHOWING_CONFIRMATION = "SHOWING_CONFIRMATION"
    READING_RECIPIENT = "READING_RECIPIENT"
    READING_MESSAGE = "READING_MESSAGE"
    WAITING_FOR_VOICE = "WAITING_FOR_VOICE"
    PROCESSING_RESPONSE = "PROCESSING_RESPONSE"
    SENDING = "SENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


YES = {
    "yes", "yes send it", "send", "send now", "go ahead", "confirm",
    "affirmative", "okay send", "ok send it",
}
NO = {
    "no", "cancel", "dont send", "do not send", "stop", "abort",
    "no dont send", "no do not send",
}


def normalize_phrase(text: str) -> str:
    import re
    value = (text or "").casefold().replace("’", "'")
    value = value.replace("don't", "dont").replace("do not", "dont")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def classify_response(text: str, confidence: float = 1.0,
                      threshold: float = 0.78) -> str:
    """Return yes/no/unclear. Never infer approval from partial word matches."""
    if confidence < threshold:
        return "unclear"
    phrase = normalize_phrase(text)
    if phrase in YES:
        return "yes"
    if phrase in NO:
        return "no"
    return "unclear"


@dataclass(frozen=True)
class ConfirmationSnapshot:
    token: str
    recipient: str
    message: str
    fingerprint: str
    created_at: float


def fingerprint(recipient: str, message: str) -> str:
    raw = (recipient.strip() + "\0" + message).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class WhatsAppConfirmationManager:
    """Thread-safe, single-session state machine with exactly-once send guard.

    speak(text) must block until playback has completely finished. listen()
    returns (transcript, confidence); a microphone error raises. send(recipient,
    message) must use the existing verified WhatsApp transport and return
    (success, detail). UI callbacks must marshal their own updates to Qt's
    thread (e.g. signals).
    """
    def __init__(self, *, speak: Callable[[str], None],
                 listen: Callable[[], tuple[str, float]],
                 send: Callable[[str, str], tuple[bool, str]],
                 show: Callable[[str, str, str], None],
                 update: Callable[[str, str], None],
                 timeout_seconds: float = 90.0,
                 max_unclear: int = 3):
        self.speak, self.listen, self.send = speak, listen, send
        self.show, self.update = show, update
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self.max_unclear = max(1, int(max_unclear))
        self._lock = threading.RLock()
        self._snapshot: Optional[ConfirmationSnapshot] = None
        self._state = ConfirmationState.IDLE
        self._send_claimed = False

    @property
    def state(self) -> ConfirmationState:
        with self._lock:
            return self._state

    def _set(self, state: ConfirmationState, detail: str = "") -> None:
        with self._lock:
            self._state = state
        self.update(state.value, detail)

    def start(self, recipient: str, message: str) -> str:
        recipient, message = str(recipient or "").strip(), str(message or "")
        if not recipient or not message.strip():
            raise ValueError("Recipient and non-empty message are required.")
        with self._lock:
            if self._state not in {
                ConfirmationState.IDLE, ConfirmationState.SENT,
                ConfirmationState.CANCELLED, ConfirmationState.ERROR,
            }:
                raise RuntimeError("A WhatsApp confirmation is already active.")
            self._send_claimed = False
            self._state = ConfirmationState.PREPARING_MESSAGE
            snap = ConfirmationSnapshot(
                uuid.uuid4().hex, recipient, message,
                fingerprint(recipient, message), time.monotonic(),
            )
            self._snapshot = snap
        self.update(self._state.value, "Preparing WhatsApp confirmation")
        self._set(ConfirmationState.SHOWING_CONFIRMATION, "Awaiting Voice Confirmation")
        self.show(recipient, message, "Awaiting Voice Confirmation")
        return snap.token

    def _valid(self, token: str, recipient: str, message: str) -> bool:
        with self._lock:
            s = self._snapshot
            return bool(
                s and token == s.token
                and time.monotonic() - s.created_at <= self.timeout_seconds
                and fingerprint(recipient, message) == s.fingerprint
                and recipient.strip() == s.recipient
                and message == s.message
            )

    def run_voice_confirmation(self, token: str) -> tuple[bool, str]:
        """Speak the full details, then listen; safe to run on a worker thread."""
        with self._lock:
            snap = self._snapshot
            if not snap or snap.token != token:
                return False, "Confirmation token is no longer valid."
            if self._state != ConfirmationState.SHOWING_CONFIRMATION:
                return False, "Confirmation is not in the display phase."
        try:
            self._set(ConfirmationState.READING_RECIPIENT, snap.recipient)
            self.speak(f"Message prepared for {snap.recipient}.")
            self._set(ConfirmationState.READING_MESSAGE, snap.message)
            self.speak(f"The message is: {snap.message}")
            self.speak(
                f"You are about to send this WhatsApp message to {snap.recipient}. "
                f"The message says: {snap.message}. Should I send it?"
            )
            # This transition occurs only after the TTS adapter returns, i.e.
            # after playback completion. TTS audio cannot approve itself.
            if not self._valid(token, snap.recipient, snap.message):
                raise RuntimeError("Message or recipient changed before listening.")
            self._set(ConfirmationState.WAITING_FOR_VOICE, "Listening for Yes or No")
            unclear = 0
            while unclear < self.max_unclear:
                if time.monotonic() - snap.created_at > self.timeout_seconds:
                    self._set(ConfirmationState.CANCELLED, "Confirmation timed out")
                    return False, "Confirmation timed out; nothing was sent."
                try:
                    transcript, confidence = self.listen()
                except Exception as exc:
                    self._set(ConfirmationState.ERROR, f"Microphone/STT failure: {exc}")
                    return False, f"Voice confirmation unavailable: {exc}. Nothing was sent."
                self._set(ConfirmationState.PROCESSING_RESPONSE, transcript)
                decision = classify_response(transcript, confidence)
                if decision == "no":
                    self._set(ConfirmationState.CANCELLED, "Cancelled by voice")
                    self.speak("Okay. The message has been cancelled and was not sent.")
                    return False, "Cancelled; nothing was sent."
                if decision == "unclear":
                    unclear += 1
                    self.speak("I didn't understand. Please say Yes, send it, or No, cancel it.")
                    self._set(ConfirmationState.WAITING_FOR_VOICE, "Listening again")
                    continue
                return self._send_once(token, snap)
            self._set(ConfirmationState.CANCELLED, "Too many unclear responses")
            return False, "No clear confirmation; nothing was sent."
        except Exception as exc:
            self._set(ConfirmationState.ERROR, str(exc))
            return False, f"Confirmation failed: {exc}"

    def _send_once(self, token: str, snap: ConfirmationSnapshot) -> tuple[bool, str]:
        with self._lock:
            if self._send_claimed:
                return False, "Duplicate send event ignored."
            if not self._valid(token, snap.recipient, snap.message):
                self._state = ConfirmationState.ERROR
                return False, "Confirmation expired or message changed; nothing was sent."
            if self._state != ConfirmationState.PROCESSING_RESPONSE:
                return False, "Affirmative response arrived outside the permitted state."
            self._send_claimed = True
            self._state = ConfirmationState.SENDING
        self.update(ConfirmationState.SENDING.value, "Verifying contact and message")
        try:
            ok, detail = self.send(snap.recipient, snap.message)
        except Exception as exc:
            ok, detail = False, str(exc)
        if ok:
            self._set(ConfirmationState.SENT, detail)
            self.speak(f"Your WhatsApp message has been sent successfully to {snap.recipient}.")
            return True, detail
        self._set(ConfirmationState.ERROR, detail or "WhatsApp send verification failed")
        return False, detail or "WhatsApp send verification failed."

    def cancel(self, token: str) -> bool:
        with self._lock:
            if not self._snapshot or self._snapshot.token != token:
                return False
            if self._state in {ConfirmationState.SENDING, ConfirmationState.SENT}:
                return False
            self._state = ConfirmationState.CANCELLED
        self.update(ConfirmationState.CANCELLED.value, "Cancelled")
        return True
