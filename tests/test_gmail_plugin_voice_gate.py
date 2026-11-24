import base64
import json
import threading
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

from core import confirm, outcome
from plugins.gmail_control import gmail_control


class _Response:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _GmailService:
    def __init__(self):
        self.submissions = []
        self.sent_event = threading.Event()
        self.list_query = None

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults):
        self.list_query = q
        return _Response({"messages": [{"id": "unread-1"}]})

    def get(self, userId, id, format, metadataHeaders):
        return _Response({
            "id": id,
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "Please review the attached report.",
            "payload": {"headers": [
                {"name": "From", "value": "Asha <asha@example.com>"},
                {"name": "Subject", "value": "Monthly report"},
                {"name": "Date", "value": "Tue, 02 Jan 2025 03:04:05 +0000"},
            ]},
        })

    def send(self, userId, body):
        self.submissions.append(body)
        self.sent_event.set()
        return _Response({"id": "submitted-message"})


class _Player:
    def request_say(self, _message):
        pass


class GmailVoiceGateTests(unittest.TestCase):
    def setUp(self):
        confirm.bind(show=lambda *_args: None, hide=lambda: None, log=lambda _msg: None)

    def tearDown(self):
        if confirm.pending_title():
            confirm.resolve(False)

    def _compose(self):
        return gmail_control(
            {
                "action": "send",
                "to": "asha@example.com",
                "subject": "Meeting",
                "body": "I will call you.",
            },
            player=_Player(),
        )

    def test_exact_voice_yes_submits_the_reviewed_email(self):
        service = _GmailService()
        with patch(
            "plugins.gmail_control._gmail_service",
            return_value=(service, "me@example.com"),
        ):
            pending = self._compose()
            self.assertIn("CONFIRMATION_PENDING", pending)
            self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", pending)
            self.assertIn("To: asha@example.com", pending)
            self.assertIn("Subject: Meeting", pending)
            self.assertIn("I will call you.", pending)
            self.assertEqual(service.submissions, [])

            self.assertTrue(confirm.resolve_from_voice("send gara"))
            self.assertTrue(service.sent_event.wait(1))

        message = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(service.submissions[0]["raw"])
        )
        self.assertEqual(message["To"], "asha@example.com")
        self.assertEqual(message["Subject"], "Meeting")
        self.assertEqual(message.get_content().strip(), "I will call you.")

    def test_voice_no_never_submits_email(self):
        service = _GmailService()
        with patch(
            "plugins.gmail_control._gmail_service",
            return_value=(service, "me@example.com"),
        ):
            pending = self._compose()
            self.assertIn("CONFIRMATION_PENDING", pending)
            self.assertIn("[OUTBOUND_MESSAGE_REVIEW]", pending)
            self.assertTrue(confirm.resolve_from_voice("no"))

        self.assertEqual(service.submissions, [])

    def test_unread_notifications_return_sender_preview_and_service_timestamp(self):
        service = _GmailService()
        with patch(
            "plugins.gmail_control._gmail_service",
            return_value=(service, "me@example.com"),
        ):
            result = gmail_control({"action": "notifications", "limit": 4})

        payload = json.loads(outcome.unwrap(result))
        self.assertEqual(service.list_query, "in:inbox is:unread")
        self.assertEqual(payload["items"][0]["source"], "Gmail")
        self.assertEqual(payload["items"][0]["sender"], "Asha <asha@example.com>")
        self.assertIn("Please review", payload["items"][0]["text"])
        self.assertEqual(payload["items"][0]["timestamp_kind"], "service")


if __name__ == "__main__":
    unittest.main()
