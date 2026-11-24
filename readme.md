# ⚙️ HELIOS CORE
### The Ultimate Cross-Platform Personal AI Assistant — By [PS official](https://www.youtube.com/@psvlog3936)

> 📺 **[Watch the full setup video on YouTube](https://www.youtube.com/@psvlog3936)**

A real-time voice AI that can hear, see, speak, and control your computer — on any OS. Supports Windows, macOS, and Linux. Built on the Gemini Live API for native audio streaming, delivering zero subscriptions and total digital autonomy.

---

## ✨ Overview

The assistant already had a screen. **Helios Core lets you choose what runs it.**

Until now this was a Gemini assistant, and only that. If you had no quota left, no
connection, or a rule that says your microphone does not leave the building, you
had no assistant. Helios Core adds a second way to hold the conversation — speech
recognition, a language model and a voice, assembled from parts you pick in
⚙ → **ENGINE & PROVIDERS** — and a way to point the assistant's own background
requests at a different model without touching the voice at all.

The local model can be on your machine (Ollama, LM Studio, llama.cpp, vLLM) or
somebody else's API (OpenAI, Groq, DeepSeek, Mistral, xAI, OpenRouter, Together).
Both are the same setting, because all of them speak the same protocol.

**None of it costs anything if you do not use it.** On a default install the
`providers/` folder is never imported — not at startup, not on a tool call, not
when the settings drawer opens. Measured: the decision takes **0.16 ms** and
loads nothing. The folder can be deleted, and deleting it changes nothing.

Everything the assistant already does carries over untouched. A local engine
inherits the avatar, the lip-sync, the self-echo guard, push-to-talk, the wake
word, memory, undo, the confirmation gate and every action and plugin — because
it enters through the same door the Live session always did.

Helios Core also changes what the assistant is allowed to CLAIM. Every tool that
drives an application now answers with what it observed rather than with what it
attempted: `done` means it was checked, `unverified` means the request went out
and could not be confirmed — and the assistant says exactly that instead of
rounding it off to "done". opening an app watches the process table for it.Closing one asks the application politely, then checks whether it went.

It's not just an assistant — it's an extension of your digital life.

---

## 🚀 Capabilities

### Core Features
| Feature | Description |
|---|---|
| 🧑‍🎤 Holographic Avatar | An animated human head in the HUD — real facial geometry, lit and drawn in software, no GPU or extra packages |
| 👄 Real Lip-Sync | ~50 mouth shapes a second from the audio's formants **and** the transcript — closures, spreads and rounds, not a volume meter |
| 🌍 Language-Free Mouth | Articulation is derived by Unicode reduction, so Latin, Cyrillic and Greek scripts all work from one rule set — and scripts that hide pronunciation fall back cleanly |
| 🙂 Facial Acting | Brows track the phrase, gaze saccades between fixations, natural blinking, a small nod on stressed syllables |
| 😐 Face as Status | Looks away while thinking, meets your eyes while listening, lids fall while asleep, glances down at new content |
| 🎚️ Push-to-Talk | Hold **Ctrl+Space** and the mic opens — closed the rest of the time. Truly global on Windows, window-scoped elsewhere |
| 🔇 Self-Echo Guard | Never answers its own last sentence: the tail of its own voice is recognised and dropped without muting you |
| 🪪 Runtime Self-Knowledge | Name, OS, abilities **and limits** are generated from the live system each session — rename it or add a plugin and it knows |
| 🎙️ Wake Word | Offline **"Hello"** detection — sleeps until called, greets you with “Hello, Sir”, auto-sleeps after 2 min of silence, and never streams sleeping audio |
| ⚡ Instant Acknowledgment | Speaks a short, context-aware reply in **your language** the instant a longer task starts — no more silent waiting |
| 🚀 Faster Live Engine | Runs on **Gemini 3.1 Flash Live** — roughly 2× faster than standard flash, built for 0.4s response. |
| 🧠 Long-Term Memory | Call `save_memory` / `recall_memory`. Context-aware facts are saved to user_memory.json. Not shared with providers. |
| 🔄 System Undo | Call `undo`. Every side effect (file, volume, brightness, clipboard) is reversible. |
| 💻 Computer Control | Control your machine through the `computer_settings` and `computer_control` plugins.|
| 📸 Vision | Assistant can capture and analyze screen or webcam.|

### 📦 Third-Party Tools
| Tool | Description|
|---|---|
| WhatsApp | Message contacts using `whatsapp_control`.|
| Social notifications | Check for WhatsApp chats and Facebook notifications.|

---

## 🔧 Installation & Setup

1. **Get the Helios Core source files** from the project's repository.
2. **Install Dependencies:**
   Run the included setup script:
   ```bash
   python setup.py
   ```
3. **Configure API Keys:**
   Add your Gemini API key to `config/api_keys.json`:
   ```json
   {
       "gemini_api_key": "YOUR_API_KEY_HERE"
   }
   ```

---

## 🤝 Contribution

Contributions are welcome! Please feel free to open a Pull Request.

---

## 📜 License

This project is licensed under the MIT License — see the LICENSE file for details.
