"""WhatsApp Web driver built on HELIOS's shared persistent browser session."""
from __future__ import annotations

import re
import unicodedata

from core import outcome

_WEB_URL = "https://web.whatsapp.com/"
_CHAT_ROW_SELECTORS = (
    "#pane-side [data-testid='cell-frame-container']",
    "#pane-side [role='listitem']",
)
_SEARCH_SELECTORS = (
    "[data-testid='chat-list-search']",
    "div[contenteditable='true'][data-tab='3']",
    "input[placeholder*='Search']",
    "[aria-label*='Search input']",
)
_MESSAGE_SELECTORS = (
    "#main [data-testid='msg-container']",
    "#main .message-in",
    "#main .message-out",
)


def fold(text: str) -> str:
    """Normalize visible names without discarding letters from other scripts."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    unmarked = []
    previous_script = ""
    for char in normalized:
        if unicodedata.category(char).startswith("M"):
            if previous_script != "LATIN":
                unmarked.append(char)
            continue
        unmarked.append(char)
        name = unicodedata.name(char, "")
        previous_script = "LATIN" if "LATIN" in name else "OTHER"
    return "".join(
        char for char in unmarked
        if char.isalnum() or unicodedata.category(char).startswith("M")
    ).casefold()


def unique_match(query: str, candidates: list[str]) -> tuple[str | None, str]:
    """Return one exact visible-name match, otherwise explain why not."""
    wanted = fold(query)
    if not wanted:
        return None, "A contact or group name is required."
    matches = [name for name in candidates if fold(name) == wanted]
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, "More than one chat has that exact name; no chat was opened."
    return None, "No exact chat name matched. Search results were not opened."


class WhatsAppWeb:
    """Small synchronous facade over the project's shared browser session."""

    def __init__(self, browser: str | None = None):
        self.browser = browser

    def _run(self, operation, timeout: int = 60):
        from actions.browser_control import run_browser_page
        return run_browser_page(operation, self.browser, timeout)

    async def _page_state(self, page) -> dict:
        url = str(page.url or "")
        if "web.whatsapp.com" not in url:
            return {"state": "not_open", "url": url}

        body = ""
        try:
            body = (await page.locator("body").inner_text(timeout=3_000)).casefold()
        except Exception:
            pass

        login_text = (
            "scan this qr code",
            "link with phone number",
            "use whatsapp on your computer",
        )
        if any(phrase in body for phrase in login_text):
            return {"state": "login_required", "url": url}

        for selector in ("#pane-side", "[data-testid='chat-list']"):
            try:
                loc = page.locator(selector)
                if await loc.count() and await loc.first.is_visible():
                    return {"state": "ready", "url": url}
            except Exception:
                continue
        try:
            if await page.locator("[data-testid='qrcode']").count():
                return {"state": "login_required", "url": url}
        except Exception:
            pass
        if "whatsapp" in body and "qr" in body:
            return {"state": "login_required", "url": url}
        return {"state": "loading", "url": url}

    async def _ensure_ready(self, page) -> dict:
        if "web.whatsapp.com" not in str(page.url or ""):
            await page.goto(_WEB_URL, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_timeout(500)
        except Exception:
            pass
        state = await self._page_state(page)
        if state["state"] == "loading":
            try:
                await page.wait_for_selector(
                    "#pane-side, [data-testid='chat-list'], "
                    "[data-testid='qrcode'], canvas",
                    timeout=8_000,
                )
            except Exception:
                pass
            state = await self._page_state(page)
        return state

    def open(self) -> dict:
        async def _open(page):
            return await self._ensure_ready(page)
        return self._run(_open)

    def status(self) -> dict:
        async def _status(page):
            return await self._page_state(page)
        return self._run(_status)

    async def _visible_chat_rows(self, page) -> list[tuple[str, object]]:
        rows = []
        for selector in _CHAT_ROW_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            for index in range(min(count, 100)):
                row = locator.nth(index)
                try:
                    if not await row.is_visible():
                        continue
                    name = ""
                    titled = row.locator("span[title]")
                    if await titled.count():
                        name = str(await titled.first.get_attribute("title") or "").strip()
                    if not name:
                        text = str(await row.inner_text()).strip()
                        name = next(
                            (line.strip() for line in text.splitlines() if line.strip()),
                            "",
                        )
                    if name:
                        rows.append((name, row))
                except Exception:
                    continue
            if rows:
                break
        return rows

    async def _search_box(self, page):
        for selector in _SEARCH_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            visible = []
            for index in range(min(count, 5)):
                item = locator.nth(index)
                try:
                    if await item.is_visible():
                        visible.append(item)
                except Exception:
                    continue
            if len(visible) == 1:
                return visible[0]
            if len(visible) > 1:
                return None
        search_buttons = page.locator(
            "button[aria-label*='Search'], [role='button'][aria-label*='Search']"
        )
        try:
            count = await search_buttons.count()
            visible = []
            for index in range(min(count, 5)):
                item = search_buttons.nth(index)
                if await item.is_visible():
                    visible.append(item)
            if len(visible) == 1:
                await visible[0].click(timeout=3_000)
                await page.wait_for_timeout(150)
                for selector in _SEARCH_SELECTORS:
                    locator = page.locator(selector)
                    if await locator.count() == 1 and await locator.first.is_visible():
                        return locator.first
        except Exception:
            pass
        return None

    async def _search(self, page, query: str) -> tuple[dict, list[tuple[str, object]]]:
        state = await self._ensure_ready(page)
        if state["state"] != "ready":
            return state, []
        search = await self._search_box(page)
        if search is None:
            return {"state": "search_unavailable"}, []
        try:
            await search.fill(query)
            await page.wait_for_timeout(450)
        except Exception:
            return {"state": "search_failed"}, []
        return {"state": "ready"}, await self._visible_chat_rows(page)

    def chats(self, limit: int = 20) -> dict:
        async def _chats(page):
            state = await self._ensure_ready(page)
            if state["state"] != "ready":
                return {"state": state["state"], "chats": []}
            rows = await self._visible_chat_rows(page)
            unread = []
            for name, row in rows:
                try:
                    label = str(await row.get_attribute("aria-label") or "")
                    indicators = row.locator(
                        "[data-testid='icon-unread-count'], "
                        "[aria-label*='unread'], [title*='unread']"
                    )
                    if re.search(r"\bunread\b", label, re.IGNORECASE) or await indicators.count():
                        unread.append(name)
                except Exception:
                    continue
            return {
                "state": "ready",
                "chats": [name for name, _ in rows[:max(1, min(int(limit), 50))]],
                "unread": unread,
            }
        return self._run(_chats)

    def notifications(self, limit: int = 10) -> dict:
        """Read unread chat rows and previews without opening chats or marking them read."""
        async def _notifications(active_page):
            page = next(
                (
                    candidate for candidate in active_page.context.pages
                    if "web.whatsapp.com" in str(candidate.url or "").casefold()
                ),
                None,
            )
            if page is None:
                page = await active_page.context.new_page()
            state = await self._ensure_ready(page)
            if state["state"] != "ready":
                return {"state": state["state"], "notifications": []}
            rows = await self._visible_chat_rows(page)
            items = []
            for name, row in rows:
                try:
                    label = str(await row.get_attribute("aria-label") or "")
                    indicators = row.locator(
                        "[data-testid='icon-unread-count'], "
                        "[aria-label*='unread'], [title*='unread']"
                    )
                    if not (
                        re.search(r"\bunread\b", label, re.IGNORECASE)
                        or await indicators.count()
                    ):
                        continue
                    content = str(await row.inner_text()).strip()
                    preview = [
                        line.strip() for line in content.splitlines()
                        if line.strip() and fold(line.strip()) != fold(name)
                    ]
                    detail = " | ".join(preview)
                    items.append(f"{name}: {detail[:240]}" if detail else name)
                    if len(items) >= max(1, min(int(limit), 20)):
                        break
                except Exception:
                    continue
            return {"state": "ready", "notifications": items}
        return self._run(_notifications)

    def search_chats(self, query: str) -> dict:
        async def _search_chats(page):
            state, rows = await self._search(page, query)
            return {
                "state": state["state"],
                "matches": [name for name, _ in rows[:20]],
            }
        return self._run(_search_chats)

    async def _open_chat(self, page, name: str) -> dict:
        state, rows = await self._search(page, name)
        if state["state"] != "ready":
            return {"state": state["state"], "reason": state["state"]}
        actual, reason = unique_match(name, [label for label, _ in rows])
        if not actual:
            return {
                "state": "ambiguous" if "More than one" in reason else "not_found",
                "reason": reason,
                "matches": [label for label, _ in rows[:10]],
            }
        row = next(row for label, row in rows if label == actual)
        try:
            await row.click(timeout=5_000)
            await page.wait_for_timeout(350)
        except Exception:
            return {"state": "open_failed", "reason": "The matching chat could not be opened."}
        header_name = await self._active_chat_name(page)
        if header_name and fold(header_name) != fold(actual):
            return {
                "state": "wrong_chat",
                "reason": "The opened conversation did not match the selected chat.",
            }
        return {"state": "opened", "name": header_name or actual}

    async def _active_chat_name(self, page) -> str:
        for selector in ("#main header span[title]", "#main header [dir='auto']"):
            locator = page.locator(selector)
            try:
                count = await locator.count()
                for index in range(min(count, 8)):
                    item = locator.nth(index)
                    if await item.is_visible():
                        text = str(
                            await item.get_attribute("title")
                            or await item.inner_text()
                            or ""
                        ).strip()
                        if text:
                            return text
            except Exception:
                continue
        return ""

    def open_chat(self, name: str) -> dict:
        async def _open_chat(page):
            return await self._open_chat(page, name)
        return self._run(_open_chat)

    async def _message_entries(self, page, limit: int = 20) -> list[dict]:
        messages = []
        seen = set()
        for selector in _MESSAGE_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            for index in range(max(0, count - 100), count):
                item = locator.nth(index)
                try:
                    if not await item.is_visible():
                        continue
                    body = item.locator(
                        "[data-testid='selectable-text'] span, span.selectable-text"
                    )
                    text = ""
                    if await body.count():
                        text = str(await body.first.inner_text()).strip()
                    if not text:
                        text = str(await item.inner_text()).strip()
                    if not text:
                        continue
                    marker = await item.get_attribute("data-pre-plain-text")
                    if not marker:
                        metadata = item.locator("[data-pre-plain-text]")
                        if await metadata.count():
                            marker = await metadata.first.get_attribute("data-pre-plain-text")
                    classes = str(await item.get_attribute("class") or "")
                    outgoing = "message-out" in classes
                    if not outgoing:
                        outgoing = bool(await item.locator(".message-out").count())
                    key = (text, marker or "", outgoing)
                    if key not in seen:
                        seen.add(key)
                        messages.append({
                            "text": text,
                            "metadata": marker or "",
                            "outgoing": outgoing,
                        })
                except Exception:
                    continue
            if messages:
                break
        return messages[-max(1, min(int(limit), 50)):]

    def read_latest(self, limit: int = 10) -> dict:
        async def _read(page):
            state = await self._page_state(page)
            if state["state"] != "ready":
                return {"state": state["state"], "messages": []}
            if not await page.locator("#main").count():
                return {"state": "no_chat_open", "messages": []}
            return {
                "state": "ready",
                "chat": await self._active_chat_name(page),
                "messages": await self._message_entries(page, limit),
            }
        return self._run(_read)

    def search_visible_messages(self, query: str) -> dict:
        async def _search_messages(page):
            state = await self._page_state(page)
            if state["state"] != "ready":
                return {"state": state["state"], "matches": []}
            if not await page.locator("#main").count():
                return {"state": "no_chat_open", "matches": []}
            wanted = fold(query)
            if not wanted:
                return {"state": "query_required", "matches": []}
            messages = await self._message_entries(page, 50)
            return {
                "state": "ready",
                "chat": await self._active_chat_name(page),
                "matches": [
                    item for item in messages
                    if wanted in fold(item["text"])
                ],
            }
        return self._run(_search_messages)

    def scroll(self, direction: str = "down", amount: int = 500) -> dict:
        if direction not in {"up", "down"}:
            return {"state": "invalid_direction"}
        delta = max(100, min(int(amount), 1500)) * (1 if direction == "down" else -1)

        async def _scroll(page):
            if not await page.locator("#main").count():
                return {"state": "no_chat_open"}
            moved = await page.locator("#main").evaluate(
                """(root, delta) => {
                    const panel = root.querySelector(
                        '[data-testid="conversation-panel-messages"]'
                    ) || root;
                    const before = panel.scrollTop;
                    panel.scrollTop = before + delta;
                    return panel.scrollTop !== before;
                }""",
                delta,
            )
            return {"state": "scrolled" if moved else "no_movement"}
        return self._run(_scroll)

    async def _message_box(self, page):
        candidates = page.locator(
            "footer [contenteditable='true'], "
            "#main [role='textbox'][contenteditable='true']"
        )
        visible = []
        try:
            count = await candidates.count()
            for index in range(min(count, 5)):
                item = candidates.nth(index)
                if await item.is_visible():
                    visible.append(item)
        except Exception:
            return None
        return visible[0] if len(visible) == 1 else None

    async def _draft(self, page, name: str, text: str) -> dict:
        if not text:
            return {"state": "empty_message"}
        opened = await self._open_chat(page, name)
        if opened["state"] != "opened":
            return opened
        box = await self._message_box(page)
        if box is None:
            return {"state": "input_unavailable"}
        try:
            await box.fill(text)
            current = str(await box.inner_text())
        except Exception:
            return {"state": "draft_failed"}
        if current != text:
            return {"state": "draft_unverified"}
        return {"state": "drafted", "name": opened["name"]}

    def draft_message(self, name: str, text: str) -> dict:
        async def _draft(page):
            return await self._draft(page, name, text)
        return self._run(_draft)

    def prepare_message(self, name: str) -> dict:
        """Resolve the recipient before the separate human confirmation gate."""
        async def _prepare(page):
            return await self._open_chat(page, name)
        return self._run(_prepare)

    def send_message_to(self, name: str, text: str) -> tuple[bool, str]:
        async def _send(page):
            drafted = await self._draft(page, name, text)
            if drafted["state"] != "drafted":
                return False, drafted.get("reason", drafted["state"])
            before = await self._message_entries(page, 50)
            button = page.locator(
                "button[aria-label='Send'], "
                "button[aria-label*='Send'], "
                "[data-testid='send']"
            )
            visible = []
            try:
                count = await button.count()
                for index in range(min(count, 5)):
                    item = button.nth(index)
                    if await item.is_visible() and await item.is_enabled():
                        visible.append(item)
            except Exception:
                visible = []
            if len(visible) != 1:
                return False, "A unique enabled send button was not identified; no message was sent."
            try:
                await visible[0].click(timeout=5_000)
                await page.wait_for_timeout(700)
            except Exception:
                return False, "The send action failed; the outcome could not be verified."
            after = await self._message_entries(page, 50)
            before_count = sum(
                item["outgoing"] and item["text"] == text for item in before
            )
            after_count = sum(
                item["outgoing"] and item["text"] == text for item in after
            )
            if after_count <= before_count:
                return False, "The exact message did not appear in the conversation after sending."
            box = await self._message_box(page)
            try:
                if box is not None and str(await box.inner_text()).strip():
                    return False, "The message remains in the input; sending was not confirmed."
            except Exception:
                return False, "The message appeared, but the input state could not be verified."
            return True, drafted["name"]
        return self._run(_send, timeout=90)


def get() -> tuple[WhatsAppWeb | None, str]:
    """Return the Web transport without creating a second browser controller."""
    try:
        from actions.browser_control import run_browser_page  # noqa: F401
    except Exception as exc:
        return None, f"The shared browser controller is unavailable: {type(exc).__name__}."
    return WhatsAppWeb(), ""


def describe_state(result: dict) -> str:
    state = result.get("state", "unknown")
    if state == "ready":
        return "WhatsApp Web is open and its chat list is visible."
    if state == "login_required":
        return (
            "WhatsApp Web needs account pairing. Complete the QR or other "
            "authentication step yourself; no authentication was bypassed."
        )
    if state == "not_open":
        return "WhatsApp Web is not open yet."
    return f"WhatsApp Web is not ready ({state}); no account action was taken."


def outcome_for_match(result: dict, action: str) -> str:
    state = result.get("state", "unknown")
    if state == "ambiguous":
        prompt = outcome.ask(
            action,
            "more than one matching chat exists; choose one exact chat name",
        )
        matches = result.get("matches", [])
        if matches:
            prompt += "\n" + outcome.untrusted(
                "whatsapp", "Matching visible chat names:\n" + "\n".join(matches)
            )
        return prompt
    if state == "login_required":
        return outcome.failed(
            action,
            "WhatsApp Web requires you to complete its normal login or pairing",
        )
    return outcome.failed(
        action,
        result.get("reason") or f"WhatsApp action could not be completed ({state})",
    )
