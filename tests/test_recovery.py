"""Offline tests for explicit recovery and provider error persistence."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from lib import sttanywhere as stt
from lib.transport import ProviderTransportError


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "runtime"
        self.base.mkdir(mode=0o700)
        self.job = self.base / "job-001"
        self.job.mkdir(mode=0o700)
        self.audio = self.job / "audio.wav"
        self.audio.write_bytes(b"retained original audio")
        self.state_path = self.job / "state.json"
        self.write_state({
            "status": "failed", "error": "first provider failure",
            "config": {}, "profile": {}, "window": "old-window",
        })

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def read_state(self):
        return json.loads(self.state_path.read_text())

    def test_recovery_rejects_paths_outside_runtime_and_non_job_directories(self):
        outside = Path(self.temp.name) / "job-outside"
        outside.mkdir()
        with mock.patch.object(stt, "runtime", return_value=self.base):
            with self.assertRaisesRegex(ValueError, "Choose a job directory"):
                stt.retry_job(str(outside))
            with self.assertRaisesRegex(ValueError, "Choose a job directory"):
                stt.retry_job("ordinary-dir")

    def test_recovery_rejects_nonfailed_status_or_missing_audio(self):
        state = self.read_state()
        state["status"] = "done"
        self.write_state(state)
        with mock.patch.object(stt, "runtime", return_value=self.base):
            with self.assertRaisesRegex(ValueError, "Only failed jobs"):
                stt.retry_job(str(self.job))
        state["status"] = "recovery_failed"
        self.write_state(state)
        self.audio.unlink()
        with mock.patch.object(stt, "runtime", return_value=self.base):
            with self.assertRaisesRegex(ValueError, "Only failed jobs"):
                stt.retry_job(str(self.job))

    def test_successful_recovery_transcribes_once_copies_clipboard_and_keeps_audio(self):
        with mock.patch.object(stt, "runtime", return_value=self.base), \
             mock.patch.object(stt, "transcribe", return_value="recovered words") as transcribe, \
             mock.patch.object(stt.subprocess, "run") as run, \
             mock.patch.object(stt, "xdo") as xdo, \
             mock.patch.object(stt, "replace_placeholder") as replace, \
             mock.patch("builtins.print"):
            stt.retry_job(str(self.job))
        transcribe.assert_called_once_with(self.audio, {}, {})
        run.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                    input=b"recovered words", check=True)
        xdo.assert_not_called()
        replace.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["status"], "recovered")
        self.assertEqual(state["delivery"], "clipboard")
        self.assertEqual(state["delivery_reason"], "Explicit recovery; old document left untouched")
        self.assertEqual(state["previous_error"], "first provider failure")
        self.assertNotIn("error", state)
        self.assertEqual(len(state["recovery_attempts"]), 1)
        attempt = state["recovery_attempts"][0]
        self.assertEqual(attempt["operation"], "explicit-recovery")
        self.assertEqual(attempt["status"], "success")
        self.assertIn("started", attempt)
        self.assertIn("finished", attempt)
        self.assertTrue(self.audio.exists())
        self.assertEqual((self.job / "transcript.txt").read_text(), "recovered words")
        self.assertEqual(stat.S_IMODE((self.job / "transcript.txt").stat().st_mode), 0o600)

    def test_existing_transcript_is_reused_without_provider_call(self):
        (self.job / "transcript.txt").write_text("already-transcribed words")
        with mock.patch.object(stt, "runtime", return_value=self.base), \
             mock.patch.object(stt, "transcribe") as transcribe, \
             mock.patch.object(stt, "request_json") as request_json, \
             mock.patch.object(stt.subprocess, "run") as run, \
             mock.patch.object(stt, "xdo") as xdo, \
             mock.patch.object(stt, "replace_placeholder") as replace, \
             mock.patch("builtins.print"):
            stt.retry_job(str(self.job))
        transcribe.assert_not_called()
        request_json.assert_not_called()
        run.assert_called_once_with(["xclip", "-selection", "clipboard"],
                                    input=b"already-transcribed words", check=True)
        xdo.assert_not_called()
        replace.assert_not_called()
        self.assertTrue(self.audio.exists())
        self.assertEqual((self.job / "transcript.txt").read_text(), "already-transcribed words")
        self.assertEqual(self.read_state()["status"], "recovered")

    def test_provider_failure_records_failed_attempt_category_and_unknown_outcome(self):
        failure = ProviderTransportError(
            "Provider request timed out; outcome unknown",
            category="timeout", outcome_unknown=True,
        )
        with mock.patch.object(stt, "runtime", return_value=self.base), \
             mock.patch.object(stt, "transcribe", side_effect=failure) as transcribe, \
             mock.patch.object(stt.subprocess, "run") as run:
            with self.assertRaises(ProviderTransportError):
                stt.retry_job(str(self.job))
        transcribe.assert_called_once_with(self.audio, {}, {})
        run.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["status"], "recovery_failed")
        self.assertEqual(state["error_category"], "timeout")
        self.assertTrue(state["outcome_unknown"])
        self.assertEqual(state["previous_error"], "first provider failure")
        self.assertEqual(state["recovery_attempts"][0]["status"], "failed")
        self.assertIn("Provider request timed out", state["error"])
        self.assertIn("finished", state["recovery_attempts"][0])
        self.assertTrue(self.audio.exists())
        self.assertFalse((self.job / "transcript.txt").exists())

    def test_worker_persists_transport_error_metadata(self):
        (self.base / "toggle.lock").touch()
        failure = ProviderTransportError(
            "Provider connection reset; outcome unknown",
            category="connection_reset", outcome_unknown=True,
        )
        with mock.patch.object(stt, "runtime", return_value=self.base), \
             mock.patch.object(stt, "transcribe", side_effect=failure), \
             mock.patch.object(stt, "notify"):
            stt.worker(str(self.job))
        state = self.read_state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error_category"], "connection_reset")
        self.assertTrue(state["outcome_unknown"])
        self.assertIn("Provider connection reset", state["error"])
        self.assertTrue(self.audio.exists())


if __name__ == "__main__":
    unittest.main()
