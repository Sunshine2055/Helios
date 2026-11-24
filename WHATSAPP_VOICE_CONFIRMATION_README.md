# HELIOS WhatsApp voice-confirmation patch (adapter core)

## What is included
- `plugins/whatsapp_voice_confirmation.py`: thread-safe state machine, exact recipient/message fingerprint, confidence-gated Yes/No parsing, timeout, single active session, duplicate-send guard, and TTS-before-listen ordering.
- `tests/test_whatsapp_voice_confirmation.py`: mocked tests for affirmative, negative, unclear, low-confidence, microphone failure, exact message, and single-session behavior.

## Important integration status
This is an adapter-based core, not yet wired into the live PyQt6 window / Gemini Live audio loop. Your current `plugins/whatsapp_control.py` still uses `core.confirm`'s existing manual confirmation HUD. Do not treat this patch alone as the requested end-to-end feature. To finish integration, the app must provide:
1. `speak(text)` that blocks until existing TTS playback is fully complete.
2. `listen()` backed by the app's existing STT/audio capture, returning `(transcript, confidence)` and raising on microphone failure.
3. `show(recipient, message, status)` and `update(state, detail)` callbacks that marshal updates to the PyQt6 GUI thread.
4. `send(recipient, message)` using `plugins._whatsapp_core`'s verified transport and checking the active chat + composer text immediately before sending.

No real WhatsApp messages are sent by these tests. Existing WhatsApp sending has not been live-tested.

## Install
Copy `plugins/whatsapp_voice_confirmation.py` into your existing `Helios-Core/plugins/` folder. Copy `tests/test_whatsapp_voice_confirmation.py` into `Helios-Core/tests/`.

From the project root, run:
```bash
python -m unittest tests.test_whatsapp_voice_confirmation
```

The supplied existing `tests/test_whatsapp_core.py` has a separate pre-existing Unicode normalization test failure for Nepali combining marks in this environment; this patch does not modify that matching code.
