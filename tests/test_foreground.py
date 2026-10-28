"""Offline tests for guarded typing and worker delivery fallback policy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib import sttanywhere as stt


class ForegroundDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.guard_path = self.root / "input-guard.json"
        self.guard = {"pid": 4321, "token": "guard-token", "path": str(self.guard_path)}

    def write_status(self, **values):
        status = {"ready": True, "dirty": False, "focus": "field-1"}
        status.update(values)
        self.guard_path.write_text(json.dumps(status))

    def test_unchanged_focused_terminal_ascii_types_without_activation(self):
        self.write_status()
        state = {"window": "window-1", "window_class": "kitty", "input_guard": self.guard}
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-1") as focus_id, \
             mock.patch.object(stt.subprocess, "run") as clipboard:
            delivered, reason = stt.foreground_deliver(state, "hello world")
        self.assertTrue(delivered)
        self.assertIsNone(reason)
        clipboard.assert_not_called()
        self.assertEqual(xdo.call_args_list, [
            mock.call("getactivewindow"),
            mock.call("type", "--clearmodifiers", "--delay", "5", "--", "hello world"),
        ])
        self.assertNotIn("windowactivate", [call.args[0] for call in xdo.call_args_list])
        focus_id.assert_called_once_with()

    def test_gui_ascii_uses_clipboard_paste_instead_of_native_typing(self):
        self.write_status()
        state = {"window": "window-1", "window_class": "firefox", "input_guard": self.guard}
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-1"), \
             mock.patch.object(stt.subprocess, "run") as clipboard:
            delivered, reason = stt.foreground_deliver(state, "hello world")
        self.assertTrue(delivered)
        self.assertIsNone(reason)
        self.assertEqual(state["foreground_method"], "clipboard-paste")
        clipboard.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                          input=b"hello world", check=True)
        self.assertEqual(xdo.call_args_list, [
            mock.call("getactivewindow"),
            mock.call("getactivewindow"),
            mock.call("key", "--clearmodifiers", "ctrl+v"),
        ])

    def test_gui_multiline_uses_single_clipboard_paste_without_return_or_typing(self):
        self.write_status()
        state = {"window": "window-1", "window_class": "firefox", "input_guard": self.guard}
        text = "first line\nsecond line\tcolumn"
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-1"), \
             mock.patch.object(stt.subprocess, "run") as clipboard:
            delivered, reason = stt.foreground_deliver(state, text)
        self.assertTrue(delivered)
        self.assertIsNone(reason)
        self.assertEqual(state["foreground_method"], "clipboard-paste")
        clipboard.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                          input=text.encode(), check=True)
        self.assertEqual(xdo.call_args_list, [
            mock.call("getactivewindow"),
            mock.call("getactivewindow"),
            mock.call("key", "--clearmodifiers", "ctrl+v"),
        ])

    def test_unicode_singleline_uses_clipboard_and_safe_paste_chord(self):
        self.write_status()
        state = {"window": "window-1", "window_class": "firefox", "input_guard": self.guard}
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-1"), \
             mock.patch.object(stt.subprocess, "run") as clipboard:
            delivered, reason = stt.foreground_deliver(state, "café 日本語")
        self.assertTrue(delivered)
        self.assertIsNone(reason)
        clipboard.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                          input="café 日本語".encode(), check=True)
        self.assertEqual(xdo.call_args_list, [
            mock.call("getactivewindow"),
            mock.call("getactivewindow"),
            mock.call("key", "--clearmodifiers", "ctrl+v"),
        ])

    def test_unicode_guard_change_after_clipboard_prevents_paste(self):
        self.write_status()
        clean = json.dumps({"ready": True, "dirty": False, "focus": "field-1"})
        dirty = json.dumps({"ready": True, "dirty": True, "focus": "field-1"})
        state = {"window": "window-1", "window_class": "firefox", "input_guard": self.guard}
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-1"), \
             mock.patch.object(Path, "read_text", side_effect=[clean, dirty]), \
             mock.patch.object(stt.subprocess, "run") as clipboard:
            delivered, reason = stt.foreground_deliver(state, "café 日本語")
        self.assertFalse(delivered)
        self.assertIn("changed before Unicode paste", reason)
        clipboard.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                          input="café 日本語".encode(), check=True)
        self.assertEqual(xdo.call_args_list, [mock.call("getactivewindow")])

    def test_missing_guard_rejects_delivery_without_desktop_calls(self):
        with mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "focus_id") as focus_id:
            delivered, reason = stt.foreground_deliver({"window": "window-1"}, "hello")
        self.assertFalse(delivered)
        self.assertIn("could not be monitored", reason)
        xdo.assert_not_called()
        focus_id.assert_not_called()

    def test_dirty_guard_rejects_delivery(self):
        self.write_status(dirty=True)
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "focus_id") as focus_id:
            delivered, reason = stt.foreground_deliver({"window": "window-1", "input_guard": self.guard}, "hello")
        self.assertFalse(delivered)
        self.assertIn("result kept on clipboard", reason)
        xdo.assert_not_called()
        focus_id.assert_not_called()

    def test_dead_or_not_ready_guard_rejects_delivery(self):
        self.write_status()
        with mock.patch.object(stt, "alive", return_value=False), \
             mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "focus_id") as focus_id:
            delivered, reason = stt.foreground_deliver({"window": "window-1", "input_guard": self.guard}, "hello")
        self.assertFalse(delivered)
        self.assertIn("monitor stopped", reason)
        xdo.assert_not_called()
        focus_id.assert_not_called()

        self.write_status(ready=False)
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo") as xdo:
            delivered, _ = stt.foreground_deliver({"window": "window-1", "input_guard": self.guard}, "hello")
        self.assertFalse(delivered)
        xdo.assert_not_called()

    def test_changed_active_window_or_focus_rejects_delivery(self):
        self.write_status()
        state = {"window": "window-1", "input_guard": self.guard}
        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-2") as xdo, \
             mock.patch.object(stt, "focus_id") as focus_id:
            delivered, reason = stt.foreground_deliver(state, "hello")
        self.assertFalse(delivered)
        self.assertIn("no longer focused", reason)
        xdo.assert_called_once_with("getactivewindow")
        focus_id.assert_not_called()

        with mock.patch.object(stt, "alive", return_value=True), \
             mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
             mock.patch.object(stt, "focus_id", return_value="field-2"):
            delivered, reason = stt.foreground_deliver(state, "hello")
        self.assertFalse(delivered)
        self.assertIn("no longer focused", reason)
        self.assertEqual(xdo.call_count, 1)

    def test_multiline_transcript_is_not_typed(self):
        self.write_status()
        state = {"window": "window-1", "window_class": "kitty", "input_guard": self.guard}
        for text in ("line one\nline two", "line one\rline two", "column\tvalue"):
            with self.subTest(text=repr(text)), \
                 mock.patch.object(stt, "alive", return_value=True), \
                 mock.patch.object(stt, "xdo", return_value="window-1") as xdo, \
                 mock.patch.object(stt, "focus_id", return_value="field-1"):
                delivered, reason = stt.foreground_deliver(state, text)
            self.assertFalse(delivered)
            self.assertIn("Multiline text", reason)
            self.assertEqual(xdo.call_count, 1)  # active-window check only
            self.assertEqual(xdo.call_args.args, ("getactivewindow",))

    def _make_worker_job(self, state):
        job = self.root / ("job-" + str(len(list(self.root.glob("job-*")))))
        job.mkdir()
        (job / "audio.wav").write_bytes(b"audio")
        (job / "state.json").write_text(json.dumps(state))
        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir(mode=0o700, exist_ok=True)
        return job, runtime_dir

    def _run_worker(self, state, *, delivery_result=True, accessible_side_effect=None):
        job, runtime_dir = self._make_worker_job(state)
        with mock.patch.object(stt, "transcribe", return_value="worker transcript"), \
             mock.patch.object(stt.subprocess, "run"), \
             mock.patch.object(stt, "foreground_deliver", return_value=(delivery_result, "guard says clipboard")) as deliver, \
             mock.patch.object(stt, "accessible", side_effect=accessible_side_effect) as accessible, \
             mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "stop_input_guard") as stop_guard, \
             mock.patch.object(stt, "notify"), mock.patch.object(stt, "runtime", return_value=runtime_dir):
            stt.worker(str(job))
        final = json.loads((job / "state.json").read_text())
        return job, final, deliver, accessible, xdo, stop_guard

    def test_worker_uses_foreground_delivery_when_anchor_unavailable(self):
        state = {"status": "transcribing", "config": {"auto_paste": True}, "profile": {},
                 "window": "window-1", "anchor_error": "AT-SPI capture unavailable", "input_guard": self.guard}
        job, final, deliver, accessible, xdo, stop_guard = self._run_worker(state)
        self.assertEqual(final["status"], "done")
        self.assertEqual(final["delivery"], "foreground-typing")
        self.assertNotIn("delivery_reason", final)
        self.assertEqual((job / "transcript.txt").read_text(), "worker transcript")
        deliver.assert_called_once_with(mock.ANY, "worker transcript")
        accessible.assert_not_called()
        xdo.assert_not_called()
        stop_guard.assert_called_once_with(self.guard)

    def test_worker_disabled_foreground_fallback_stays_on_clipboard(self):
        state = {"status": "transcribing", "config": {"auto_paste": True, "foreground_fallback": False},
                 "profile": {}, "window": "window-1", "anchor_error": "AT-SPI capture unavailable",
                 "input_guard": self.guard}
        job, final, deliver, accessible, xdo, _ = self._run_worker(state)
        self.assertEqual(final["status"], "clipboard")
        self.assertEqual(final["delivery_reason"], "AT-SPI capture unavailable")
        self.assertEqual((job / "transcript.txt").read_text(), "worker transcript")
        deliver.assert_not_called()
        accessible.assert_not_called()
        xdo.assert_not_called()

    def test_invalid_accessible_anchor_does_not_fall_back_to_foreground_typing(self):
        anchor = {"pid": 100, "process_token": "app-token", "path": "0/1/0",
                  "marker": stt.RECORDING + " "}
        state = {"status": "transcribing", "config": {"auto_paste": True}, "profile": {},
                 "window": "window-1", "anchor": anchor, "input_guard": self.guard}
        job, final, deliver, accessible, xdo, _ = self._run_worker(
            state, accessible_side_effect=ValueError("Original marker moved")
        )
        self.assertEqual(final["status"], "clipboard")
        self.assertEqual(final["delivery_reason"], "Original marker moved")
        self.assertEqual((job / "transcript.txt").read_text(), "worker transcript")
        accessible.assert_called_once_with("replace", {**anchor, "replacement": "worker transcript"})
        deliver.assert_not_called()
        xdo.assert_not_called()

    def test_failed_foreground_check_falls_back_to_clipboard_with_reason(self):
        state = {"status": "transcribing", "config": {"auto_paste": True}, "profile": {},
                 "window": "window-1", "anchor_error": "capture unavailable", "input_guard": self.guard}
        job, final, deliver, accessible, xdo, _ = self._run_worker(state, delivery_result=False)
        self.assertEqual(final["status"], "clipboard")
        self.assertEqual(final["delivery_reason"], "guard says clipboard")
        self.assertEqual((job / "transcript.txt").read_text(), "worker transcript")
        deliver.assert_called_once()
        accessible.assert_not_called()
        xdo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
