import unittest
from types import SimpleNamespace
from unittest.mock import patch

from actions import computer_settings
from core import confirm


class DirectShutdownTests(unittest.TestCase):
    def test_shutdown_skips_confirmation_and_requests_immediate_windows_shutdown(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch.object(computer_settings, "_PYAUTOGUI", False),
            patch.object(computer_settings, "_OS", "Windows"),
            patch.object(computer_settings.subprocess, "run", return_value=completed) as run,
            patch.object(confirm, "request") as request,
        ):
            result = computer_settings.computer_settings({"action": "shutdown"})

        self.assertIn("status=done", result)
        self.assertIn("requested=true", result)
        self.assertEqual(run.call_args.args[0], ["shutdown", "/s", "/t", "0"])
        self.assertEqual(
            run.call_args.kwargs["creationflags"],
            computer_settings.subprocess.CREATE_NO_WINDOW,
        )
        request.assert_not_called()

    def test_shutdown_reports_os_rejection_without_confirmation(self):
        completed = SimpleNamespace(
            returncode=1, stdout="", stderr="Access is denied."
        )
        with (
            patch.object(computer_settings, "_PYAUTOGUI", False),
            patch.object(computer_settings, "_OS", "Windows"),
            patch.object(computer_settings.subprocess, "run", return_value=completed),
        ):
            result = computer_settings.computer_settings({"action": "shutdown"})

        self.assertIn("status=failed", result)
        self.assertIn("Access is denied", result)
        self.assertEqual(confirm.pending_title(), "")


if __name__ == "__main__":
    unittest.main()
