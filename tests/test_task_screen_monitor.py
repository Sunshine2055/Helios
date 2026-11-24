import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import HeliosLive


class FakeUI:
    def __init__(self):
        self.screen_share_states = []

    def set_screen_share_state(self, enabled, message=""):
        self.screen_share_states.append((enabled, message))


def make_helios():
    helios = HeliosLive.__new__(HeliosLive)
    helios._engine_caps = None
    helios._screen_share_enabled = threading.Event()
    helios._screen_share_manual = False
    helios._screen_share_task_active = False
    helios._screen_share_task_suppressed = False
    helios._engine_mode = lambda: "live"
    helios.ui = FakeUI()
    return helios


class TaskScreenMonitorTests(unittest.TestCase):
    def setUp(self):
        self.capture_available = patch(
            "core.platform_support.detect",
            return_value=SimpleNamespace(can_capture_screen=True),
        )
        self.capture_available.start()
        self.addCleanup(self.capture_available.stop)

    def test_monitor_spans_repeated_actions_and_stops_when_task_ends(self):
        helios = make_helios()

        helios._begin_task_screen_monitor()
        helios._begin_task_screen_monitor()
        self.assertTrue(helios._screen_share_enabled.is_set())
        self.assertEqual(len(helios.ui.screen_share_states), 1)

        helios._end_task_screen_monitor()
        self.assertFalse(helios._screen_share_enabled.is_set())
        self.assertFalse(helios._screen_share_task_active)

    def test_manual_share_remains_active_after_task_ends(self):
        helios = make_helios()

        self.assertTrue(helios._set_local_screen_share(True))
        helios._begin_task_screen_monitor()
        helios._end_task_screen_monitor()

        self.assertTrue(helios._screen_share_manual)
        self.assertTrue(helios._screen_share_enabled.is_set())

    def test_user_can_stop_task_monitor_until_task_completion(self):
        helios = make_helios()

        helios._begin_task_screen_monitor()
        self.assertTrue(helios._set_local_screen_share(False))
        self.assertFalse(helios._screen_share_enabled.is_set())
        helios._begin_task_screen_monitor()
        self.assertFalse(helios._screen_share_task_active)

        helios._end_task_screen_monitor()
        self.assertFalse(helios._screen_share_task_suppressed)
        helios._begin_task_screen_monitor()
        self.assertTrue(helios._screen_share_task_active)


if __name__ == "__main__":
    unittest.main()
