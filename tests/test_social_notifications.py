import json
import unittest
from unittest.mock import patch

from core import outcome
from plugins.social_notifications import run


class _Transport:
    def notifications(self, limit):
        self.limit = limit
        return {"state": "ready", "notifications": ["Asha: Are you free?"]}


class SocialNotificationsTests(unittest.TestCase):
    def test_combines_visible_sources_as_untrusted_content(self):
        transport = _Transport()
        with (
            patch(
                "plugins._facebook_core.notifications",
                return_value={
                    "state": "ready",
                    "items": [{
                        "source": "Facebook",
                        "sender": "Nima",
                        "text": "New Facebook alert",
                        "timestamp": "2025-01-02T03:04:05Z",
                        "unread": True,
                    }],
                },
            ),
            patch(
                "plugins._whatsapp_core.get",
                return_value=(transport, ""),
            ),
        ):
            result = run({})

        visible = outcome.unwrap(result)
        payload = json.loads(visible)
        self.assertEqual(
            [item["source"] for item in payload["items"]],
            ["WhatsApp", "Facebook"],
        )
        self.assertEqual(payload["items"][0]["sender"], "Asha")
        self.assertEqual(payload["items"][0]["text"], "Are you free?")
        self.assertEqual(payload["items"][1]["text"], "New Facebook alert")
        self.assertEqual(transport.limit, 10)
        self.assertIn("<<<UNTRUSTED", result)

    def test_source_failures_are_reported_with_connection_state(self):
        with (
            patch(
                "plugins._whatsapp_core.get",
                side_effect=RuntimeError("browser unavailable"),
            ),
            patch(
                "plugins._facebook_core.notifications",
                return_value={"state": "login_required", "items": []},
            ),
        ):
            payload = json.loads(outcome.unwrap(run({})))

        self.assertEqual(payload["integrations"]["WhatsApp"]["state"], "error")
        self.assertEqual(
            payload["integrations"]["Facebook"]["state"],
            "login_required",
        )
        self.assertEqual(payload["items"], [])


if __name__ == "__main__":
    unittest.main()
