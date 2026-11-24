import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from main import HeliosLive
from ui import SpaceChordFilter


class SpaceChordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.target = QLabel(self.window)
        self.calls = []
        self.filter = SpaceChordFilter(
            self.window,
            lambda: self.calls.append("mic"),
            lambda: self.calls.append("share"),
            lambda: False,
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _key(self, event_type, key, repeat=False):
        event = QKeyEvent(
            event_type, key, Qt.KeyboardModifier.NoModifier, "", repeat,
        )
        return self.filter.eventFilter(self.target, event)

    def test_space_m_and_space_s_toggle_only_their_assigned_controls(self):
        self.assertTrue(self._key(QEvent.Type.KeyPress, Qt.Key.Key_Space))
        self.assertTrue(self._key(QEvent.Type.KeyPress, Qt.Key.Key_M))
        self.assertTrue(self._key(QEvent.Type.KeyRelease, Qt.Key.Key_Space))
        self.assertEqual(self.calls, ["mic"])

        self.assertTrue(self._key(QEvent.Type.KeyPress, Qt.Key.Key_Space))
        self.assertTrue(self._key(QEvent.Type.KeyPress, Qt.Key.Key_S))
        self.assertTrue(self._key(QEvent.Type.KeyRelease, Qt.Key.Key_Space))
        self.assertEqual(self.calls, ["mic", "share"])

    def test_repeated_key_events_do_not_toggle_twice(self):
        self._key(QEvent.Type.KeyPress, Qt.Key.Key_Space)
        self._key(QEvent.Type.KeyPress, Qt.Key.Key_M)
        self._key(QEvent.Type.KeyPress, Qt.Key.Key_M, repeat=True)

        self.assertEqual(self.calls, ["mic"])


class _FakeUI:
    def __init__(self):
        self.states = []
        self.announcements = []

    def set_screen_share_state(self, enabled, message=""):
        self.states.append((enabled, message))

    def request_say(self, message):
        self.announcements.append(message)

    def write_log(self, message):
        raise AssertionError(message)


class ScreenShareVoiceConfirmationTests(unittest.TestCase):
    def test_manual_start_and_stop_are_announced(self):
        helios = HeliosLive.__new__(HeliosLive)
        helios._engine_caps = None
        helios._engine_mode = lambda: "live"
        helios._screen_share_enabled = threading.Event()
        helios._screen_share_manual = False
        helios._screen_share_task_active = False
        helios._screen_share_task_suppressed = False
        helios.ui = _FakeUI()

        with patch("core.platform_support.detect"):
            self.assertTrue(helios._set_local_screen_share(True))
            self.assertTrue(helios._screen_share_enabled.is_set())
            self.assertTrue(helios._set_local_screen_share(False))

        self.assertFalse(helios._screen_share_enabled.is_set())
        self.assertEqual(len(helios.ui.announcements), 2)
        self.assertIn("screen is now being shared", helios.ui.announcements[0])
        self.assertIn("screen sharing has stopped", helios.ui.announcements[1])


if __name__ == "__main__":
    unittest.main()
