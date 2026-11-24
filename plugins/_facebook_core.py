"""Facebook/Messenger automation through HELIOS's shared signed-in browser."""
from __future__ import annotations

import json
import re
from datetime import datetime

from core import confirm as confirm_gate, outcome

_FACEBOOK_URL = "https://www.facebook.com/"
_MESSENGER_URL = "https://www.facebook.com/messages/"
_NOTIFICATIONS_URL = "https://www.facebook.com/notifications"


def _page_for(context, domain: str):
    return next(
        (
            candidate for candidate in context.pages
            if domain in str(candidate.url or "").casefold()
        ),
        None,
    )


async def _ensure_page(page, url: str):
    domain = "facebook.com"
    target = _page_for(page.context, url)
    if target is None:
        target = next(
            (
                candidate for candidate in page.context.pages
                if domain in str(candidate.url or "").casefold()
                and "/login" in str(candidate.url or "").casefold()
            ),
            None,
        )
    if target is None:
        active = str(page.url or "")
        target = page if active in {"", "about:blank"} else await page.context.new_page()
    target_url = str(target.url or "")
    if not target_url.startswith(url):
        await target.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await target.wait_for_timeout(500)
    return target


async def _login_state(page) -> str:
    current_url = str(page.url or "").casefold()
    password = page.locator('input[name="pass"]')
    if "/login" in current_url or (
        await password.count() and await password.first.is_visible()
    ):
        return "login_required"
    return "ready"


async def _visible_exact_text(page, name: str):
    locator = page.get_by_text(name, exact=True)
    candidates = []
    for index in range(min(await locator.count(), 20)):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                candidates.append(item)
        except Exception:
            continue
    return candidates


async def _find_message_box(page):
    selectors = (
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][aria-label*="Message"]',
        'textarea[placeholder*="Message"]',
    )
    boxes = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(await locator.count(), 10)):
            item = locator.nth(index)
            try:
                if await item.is_visible():
                    boxes.append(item)
            except Exception:
                continue
        if boxes:
            break
    return boxes[0] if len(boxes) == 1 else None


async def _message_box_value(box) -> str:
    if await box.evaluate("(el) => 'value' in el"):
        return await box.input_value()
    return await box.inner_text()


async def _search_box(page):
    selectors = (
        'input[placeholder*="Search"][placeholder*="Messenger"]',
        'input[aria-label*="Search Messenger"]',
        'input[type="search"]',
    )
    matches = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(await locator.count(), 10)):
            item = locator.nth(index)
            try:
                if await item.is_visible():
                    matches.append(item)
            except Exception:
                continue
        if matches:
            break
    return matches[0] if len(matches) == 1 else None


async def _open_conversation(page, contact: str) -> dict:
    state = await _login_state(page)
    if state != "ready":
        return {"state": state}

    heading = page.get_by_role("heading", name=contact, exact=True)
    if await heading.count() and await heading.first.is_visible():
        return {"state": "opened", "name": contact}

    search = await _search_box(page)
    if search is None:
        return {
            "state": "search_unavailable",
            "reason": "Messenger did not expose one unambiguous visible conversation search field.",
        }
    await search.fill(contact)
    await page.wait_for_timeout(800)
    matches = await _visible_exact_text(page, contact)
    if len(matches) != 1:
        return {
            "state": "ambiguous" if matches else "not_found",
            "matches": len(matches),
            "reason": (
                "More than one exact visible contact matched; no conversation was opened."
                if matches else
                "No exact visible contact matched the search."
            ),
        }

    await matches[0].click()
    await page.wait_for_timeout(500)
    heading = page.get_by_role("heading", name=contact, exact=True)
    if not await heading.count() or not await heading.first.is_visible():
        return {
            "state": "not_verified",
            "reason": "The selected Messenger conversation did not show the exact contact heading.",
        }
    return {"state": "opened", "name": contact}


async def _active_contact(page) -> str:
    main = page.locator('[role="main"]')
    if not await main.count():
        return ""
    headings = main.first.get_by_role("heading")
    visible = []
    for index in range(min(await headings.count(), 10)):
        item = headings.nth(index)
        try:
            text = " ".join((await item.inner_text()).split())
            if text and await item.is_visible():
                visible.append(text)
        except Exception:
            continue
    return visible[0] if len(visible) == 1 else ""


def status() -> dict:
    from actions.browser_control import run_browser_page

    async def _status(page):
        target = _page_for(page.context, "facebook.com")
        if target is None:
            return {"state": "not_open"}
        state = await _login_state(target)
        return {
            "state": state,
            "url": str(target.url or ""),
            "messenger_open": "/messages" in str(target.url or "").casefold(),
        }

    return run_browser_page(_status)


def notifications(limit: int = 10) -> dict:
    from actions.browser_control import run_browser_page

    async def _read(page):
        target = await _ensure_page(page, _NOTIFICATIONS_URL)
        if await _login_state(target) != "ready":
            return {"state": "login_required", "items": []}
        checked_at = datetime.now().astimezone().isoformat()
        root = target.locator('[role="main"]')
        root = root.first if await root.count() else target.locator("body")
        articles = root.locator('[role="article"]')
        items = []
        for index in range(min(await articles.count(), max(1, min(int(limit), 20)))):
            article = articles.nth(index)
            try:
                if not await article.is_visible():
                    continue
                text = " ".join((await article.inner_text()).split())
                if not text:
                    continue
                times = article.locator("time")
                timestamp = ""
                if await times.count():
                    timestamp = str(
                        await times.first.get_attribute("datetime")
                        or await times.first.inner_text()
                        or ""
                    ).strip()
                unread_markers = article.locator(
                    '[aria-label*="Mark as read"], [data-testid*="unread"]'
                )
                items.append({
                    "source": "Facebook",
                    "sender": text.split(" ", 1)[0][:100],
                    "text": text[:600],
                    "timestamp": timestamp or checked_at,
                    "timestamp_kind": "service" if timestamp else "observed",
                    "unread": await unread_markers.count() > 0,
                })
            except Exception:
                continue
        return {"state": "ready", "items": items}

    return run_browser_page(_read, timeout=45)


def prepare_message(contact: str, text: str) -> dict:
    from actions.browser_control import run_browser_page

    async def _prepare(page):
        target = await _ensure_page(page, _MESSENGER_URL)
        opened = await _open_conversation(target, contact)
        if opened["state"] != "opened":
            return opened
        box = await _find_message_box(target)
        if box is None:
            return {
                "state": "composer_unavailable",
                "reason": "Messenger did not expose one visible message composer.",
            }
        await box.fill(text)
        value = await _message_box_value(box)
        if value != text:
            return {
                "state": "draft_unverified",
                "reason": "The exact draft could not be verified in Messenger's composer.",
            }
        return {"state": "prepared", "name": contact, "text": text}

    return run_browser_page(_prepare, timeout=45)


def send_prepared(contact: str, text: str) -> str:
    from actions.browser_control import run_browser_page

    async def _send(page):
        target = _page_for(page.context, "facebook.com")
        if target is None:
            return outcome.failed(
                "facebook_send", "the prepared Facebook conversation is no longer open",
            )
        opened = await _open_conversation(target, contact)
        if opened["state"] != "opened":
            return outcome.failed("facebook_send", opened.get("reason", opened["state"]))
        box = await _find_message_box(target)
        if box is None:
            return outcome.failed(
                "facebook_send", "the Facebook message composer is unavailable",
            )
        await box.fill(text)
        value = await _message_box_value(box)
        if value != text:
            return outcome.failed(
                "facebook_send", "the exact confirmed text could not be restored",
            )
        send_button = target.get_by_role(
            "button",
            name=re.compile(r"^(send|press enter to send)$", re.IGNORECASE),
        )
        buttons = []
        for index in range(min(await send_button.count(), 10)):
            item = send_button.nth(index)
            try:
                if await item.is_visible() and await item.is_enabled():
                    buttons.append(item)
            except Exception:
                continue
        if len(buttons) != 1:
            return outcome.failed(
                "facebook_send", "Messenger did not expose one unambiguous Send button",
            )
        await buttons[0].click()
        await target.wait_for_timeout(700)
        remaining = await _find_message_box(target)
        if remaining is not None:
            value = await _message_box_value(remaining)
            if value:
                return outcome.unverified(
                    "facebook_send",
                    "the send was requested but the composer still contains text; "
                    "do not retry without checking the conversation",
                    to=contact,
                )
        messages = target.locator('[role="main"] [dir="auto"]')
        visible_messages = []
        for index in range(min(await messages.count(), 100)):
            item = messages.nth(index)
            try:
                if await item.is_visible():
                    visible_messages.append((await item.inner_text()).strip())
            except Exception:
                continue
        if text not in visible_messages:
            return outcome.unverified(
                "facebook_send",
                "Messenger cleared the composer but the exact outgoing message "
                "was not visible for verification",
                to=contact,
            )
        return outcome.done(
            "facebook_send", submitted=True, verified=True, to=contact,
            delivery="not_claimed",
        )

    return run_browser_page(_send, timeout=60)


def read_latest(contact: str = "", limit: int = 10) -> dict:
    from actions.browser_control import run_browser_page

    async def _read(page):
        target = await _ensure_page(page, _MESSENGER_URL)
        if await _login_state(target) != "ready":
            return {"state": "login_required", "messages": []}
        if contact:
            opened = await _open_conversation(target, contact)
            if opened["state"] != "opened":
                return opened
        elif await _find_message_box(target) is None:
            return {"state": "no_conversation", "messages": []}
        active_contact = await _active_contact(target)
        main = target.locator('[role="main"]')
        if not await main.count():
            return {"state": "no_conversation", "messages": []}
        entries = main.first.locator('[dir="auto"]')
        messages = []
        for index in range(min(await entries.count(), 200)):
            item = entries.nth(index)
            try:
                if not await item.is_visible():
                    continue
                text = " ".join((await item.inner_text()).split())
                if text and text not in messages:
                    messages.append(text[:800])
            except Exception:
                continue
        return {
            "state": "ready",
            "contact": active_contact or contact,
            "messages": messages[-max(1, min(int(limit), 50)):],
            "checked_at": datetime.now().astimezone().isoformat(),
        }

    return run_browser_page(_read, timeout=45)


def describe_state(result: dict) -> str:
    state = result.get("state", "unknown")
    if state == "login_required":
        return "Facebook needs you to sign in in the browser; no login was attempted."
    if state == "not_open":
        return "Facebook is not connected in the shared browser."
    if state == "opened":
        return f"Opened the exact Facebook conversation: {result.get('name', '')}."
    if state == "ambiguous":
        return result.get("reason", "More than one contact matched; nothing was sent.")
    if state in {"not_found", "not_verified", "search_unavailable", "composer_unavailable", "draft_unverified"}:
        return result.get("reason", f"Facebook action could not be verified ({state}).")
    return f"Facebook is not ready ({state}); no message was sent."


def send_control(parameters: dict, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    contact = str(params.get("contact", "")).strip()
    message = str(params.get("text", ""))
    if action not in {"open", "status", "notifications", "read_latest", "reply", "send"}:
        return outcome.failed(
            "facebook_control",
            "action must be open, status, notifications, read_latest, reply, or send",
        )
    if action == "send" and not contact:
        return outcome.failed("facebook_control", "provide an exact Messenger contact name")
    if action in {"reply", "send"} and not message.strip():
        return outcome.failed("facebook_control", "provide the complete message text")

    try:
        if action == "status":
            result = status()
            return (
                "Facebook is signed in to the shared browser."
                if result["state"] == "ready"
                else describe_state(result)
            )
        if action == "open":
            from actions.browser_control import run_browser_page

            async def _open(page):
                target = await _ensure_page(page, _FACEBOOK_URL)
                return {"state": await _login_state(target)}

            opened = run_browser_page(_open)
            return (
                "Facebook is open in the shared browser."
                if opened["state"] == "ready" else describe_state(opened)
            )
        if action == "notifications":
            result = notifications(params.get("limit", 10))
            if result["state"] != "ready":
                return describe_state(result)
            return outcome.untrusted(
                "facebook_notifications",
                json.dumps({
                    "checked_at": datetime.now().astimezone().isoformat(),
                    "items": result["items"],
                    "integrations": {"Facebook": {"state": "ready"}},
                }, ensure_ascii=False),
            )
        if action == "read_latest":
            result = read_latest(contact, params.get("limit", 10))
            if result["state"] != "ready":
                return describe_state(result)
            return outcome.untrusted(
                "facebook_messages",
                "\n".join(result["messages"]) if result["messages"]
                else "No visible messages in that conversation.",
            )

        if action == "reply" and not contact:
            from actions.browser_control import run_browser_page

            async def _current_contact(page):
                target = _page_for(page.context, _MESSENGER_URL)
                return await _active_contact(target) if target else ""

            contact = run_browser_page(_current_contact)
            if not contact:
                return outcome.failed(
                    "facebook_control",
                    "No uniquely named Messenger conversation is open; specify the exact contact.",
                )
        prepared = prepare_message(contact, message)
        if prepared["state"] != "prepared":
            return describe_state(prepared)
        if confirm_gate.pending_title():
            return outcome.failed(
                "facebook_send", "another action is awaiting confirmation; no message was sent",
            )
        return confirm_gate.request(
            key="facebook_send",
            title="Send Facebook message?",
            detail=f"To: {prepared['name']}\n\nMessage:\n{message}",
            run=lambda: _report_send(player, contact, message),
        )
    except Exception as exc:
        return outcome.failed(
            "facebook_control",
            f"the action failed: {type(exc).__name__}: {exc}",
        )


def _report_send(player, contact: str, message: str) -> str:
    result = send_prepared(contact, message)
    if player and hasattr(player, "request_say"):
        player.request_say(
            "Tell the user in their own language whether Facebook visibly confirmed "
            "the message submission. Do not claim delivery or read status: " + result
        )
    return result
