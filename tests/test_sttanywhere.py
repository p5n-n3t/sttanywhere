"""Offline tests for the STT Anywhere controller's provider and desktop boundaries."""
import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import urllib.error

from lib import sttanywhere as stt


def profile(adapter="openai", **overrides):
    value = {
        "adapter": adapter,
        "api_key_env": "STT_TEST_KEY",
        "endpoint": "https://provider.example/v1/audio",
        "model": "test-model",
        "options": {"language": "en"},
        "response_path": "text",
    }
    value.update(overrides)
    return value


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"STT_TEST_KEY": "secret-test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audio = Path(self.temp.name) / "sample.wav"
        self.audio.write_bytes(b"WAVE" + b"a" * 80)
        self.cfg = {"max_audio_bytes": 1000, "request_timeout": 9, "job_timeout": 20}

    def test_openai_provider_sends_multipart_model_options_and_audio(self):
        p = profile()
        with mock.patch.object(stt, "request_json", return_value={"text": "  hello  "}) as request:
            self.assertEqual(stt.transcribe(self.audio, self.cfg, p), "hello")
        args, kwargs = request.call_args
        self.assertEqual(args[0], "https://provider.example/v1/audio")
        self.assertEqual(args[1], "secret-test-key")
        self.assertIn(b'name="model"\r\n\r\ntest-model', args[2])
        self.assertIn(b'name="language"\r\n\r\nen', args[2])
        self.assertIn(b'name="file"; filename="audio.wav"', args[2])
        self.assertIn(b"WAVE", args[2])
        self.assertTrue(args[3].startswith("multipart/form-data; boundary=sttanywhere-"))
        self.assertEqual(args[4], 9)

    def test_raw_provider_sends_audio_bytes_without_multipart(self):
        with mock.patch.object(stt, "request_json", return_value={"text": "raw text"}) as request:
            self.assertEqual(stt.transcribe(self.audio, self.cfg, profile("raw")), "raw text")
        args = request.call_args.args
        self.assertEqual(args[2], self.audio.read_bytes())
        self.assertEqual(args[3], "application/octet-stream")
        self.assertEqual(len(args), 5)  # bearer defaults to True

    def test_json_base64_provider_serializes_audio_and_extracts_nested_text(self):
        p = profile("json_base64", response_path="result.text",
                    endpoint="https://api.cloudflare.example/whisper",
                    options={"task": "transcribe", "language": "en"})
        with mock.patch.object(stt, "request_json", return_value={"result": {"text": "  cloudflare words  "}}) as request:
            self.assertEqual(stt.transcribe(self.audio, self.cfg, p), "cloudflare words")
        args = request.call_args.args
        self.assertEqual(args[0], "https://api.cloudflare.example/whisper")
        self.assertEqual(args[1], "secret-test-key")
        payload = json.loads(args[2])
        self.assertEqual(payload["task"], "transcribe")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(base64.b64decode(payload["audio"]), self.audio.read_bytes())
        self.assertEqual(args[3], "application/json")

    def test_assemblyai_upload_poll_and_success(self):
        p = profile("assemblyai", endpoint="https://api.assemblyai.com/v2", response_path="text")
        responses = [
            {"upload_url": "https://upload.example/audio"},
            {"id": "job 1", "status": "queued"},
            {"id": "job 1", "status": "completed", "text": " done "},
        ]
        with mock.patch.object(stt, "request_json", side_effect=responses) as request, \
             mock.patch.object(stt.time, "sleep") as sleep:
            self.assertEqual(stt.transcribe(self.audio, self.cfg, p), "done")
        calls = request.call_args_list
        self.assertEqual([c.args[0] for c in calls], [
            "https://api.assemblyai.com/v2/upload",
            "https://api.assemblyai.com/v2/transcript",
            "https://api.assemblyai.com/v2/transcript/job%201",
        ])
        self.assertEqual(calls[0].args[2], self.audio.read_bytes())
        self.assertFalse(calls[0].args[5])
        payload = json.loads(calls[1].args[2])
        self.assertEqual(payload["audio_url"], "https://upload.example/audio")
        self.assertEqual(payload["speech_models"], ["test-model"])
        self.assertEqual(calls[2].kwargs["timeout"], 9)
        self.assertFalse(calls[2].kwargs["bearer"])
        sleep.assert_called_once_with(2)

    def test_assemblyai_error_status_fails_without_extracting_text(self):
        p = profile("assemblyai", endpoint="https://api.assemblyai.com/v2")
        with mock.patch.object(stt, "request_json", side_effect=[
            {"upload_url": "https://upload.example/audio"},
            {"id": "job", "status": "error"},
        ]):
            with self.assertRaisesRegex(ValueError, "AssemblyAI transcription failed"):
                stt.transcribe(self.audio, self.cfg, p)

    def test_missing_key_fails_before_upload(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(stt, "request_json") as request:
            with self.assertRaisesRegex(ValueError, "Missing STT_TEST_KEY"):
                stt.transcribe(self.audio, self.cfg, profile("raw"))
        request.assert_not_called()

    def test_malformed_or_blank_provider_text_is_rejected(self):
        for response in ({"text": "  "}, {"unexpected": "value"}, {"text": None}):
            with self.subTest(response=response), mock.patch.object(stt, "request_json", return_value=response):
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    stt.transcribe(self.audio, self.cfg, profile("raw"))

    def test_audio_size_limits_are_checked_before_request(self):
        self.audio.write_bytes(b"x" * 44)
        with mock.patch.object(stt, "request_json") as request:
            with self.assertRaisesRegex(ValueError, "empty or exceeds"):
                stt.transcribe(self.audio, self.cfg, profile("raw"))
        request.assert_not_called()

    def test_endpoint_requires_complete_https_without_credentials_or_unexpanded_vars(self):
        for value in (
            "http://provider.example/api",
            "https:///missing-host",
            "https://user:pass@provider.example/api",
            "https://provider.example/${missing}/api",
        ):
            with self.subTest(endpoint=value), self.assertRaises(ValueError):
                stt.endpoint(profile(endpoint=value))
        self.assertEqual(stt.endpoint(profile(endpoint="https://provider.example/${model}")),
                         "https://provider.example/test-model")

    def test_redirect_handler_refuses_to_forward_authorization(self):
        req = __import__("urllib.request", fromlist=["Request"]).Request("https://provider.example")
        handler = stt.NoRedirect()
        with self.assertRaisesRegex(ValueError, "redirected request"):
            handler.redirect_request(req, None, 302, "Found", {}, "https://other.example")

    def test_request_json_maps_http_errors_without_exposing_redirect_target(self):
        error = urllib.error.HTTPError("https://provider.example", 401, "Unauthorized", {}, None)
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(stt.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "Provider HTTP 401") as caught:
                stt.request_json("https://provider.example", "secret")
        self.assertNotIn("secret", str(caught.exception))
        error.close()


class RuntimeAndDesktopTests(unittest.TestCase):
    def test_runtime_creates_private_owned_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "runtime"
            with mock.patch.object(stt, "RUNTIME", target):
                self.assertEqual(stt.runtime(), target)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(target.stat().st_uid, os.getuid())

    def test_runtime_rejects_wrong_mode_and_non_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "runtime"
            target.mkdir(mode=0o755)
            target.chmod(0o755)
            with mock.patch.object(stt, "RUNTIME", target), self.assertRaisesRegex(ValueError, "Unsafe runtime"):
                stt.runtime()
            target.rmdir()
            target.write_text("not a directory")
            with mock.patch.object(stt, "RUNTIME", target), self.assertRaisesRegex(ValueError, "Unsafe runtime"):
                stt.runtime()

    def test_pid_identity_requires_matching_proc_start_token(self):
        def proc_stat(state, token):
            # /proc/<pid>/stat starts with state; field 22 (starttime) is index 19.
            return ") " + " ".join([state] + ["x"] * 18 + [token])

        with mock.patch.object(Path, "read_text", side_effect=[
            proc_stat("R", "current"), proc_stat("R", "current")
        ]):
            self.assertTrue(stt.alive(123, "current"))
        with mock.patch.object(Path, "read_text", side_effect=[
            proc_stat("Z", "current"), proc_stat("Z", "current")
        ]):
            self.assertFalse(stt.alive(123, "current"))
        with mock.patch.object(Path, "read_text", return_value=proc_stat("S", "different")):
            self.assertFalse(stt.alive(123, "old"))
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertFalse(stt.alive(123, "missing"))
        self.assertFalse(stt.alive(123, None))

    def test_replace_placeholder_uses_exact_requested_backspace_count(self):
        with mock.patch.object(stt, "activate") as activate, mock.patch.object(stt, "xdo") as xdo, \
             mock.patch.object(stt, "type_text") as type_text:
            stt.replace_placeholder(42, 16, stt.TRANSCRIBING + " ")
        activate.assert_called_once_with(42)
        self.assertEqual(xdo.call_args.args, ("key", "--clearmodifiers", "--repeat", 16,
                                             "--repeat-delay", "1", "BackSpace"))
        type_text.assert_called_once_with(stt.TRANSCRIBING + " ")

    def test_placeholder_lengths_match_backspace_counts_with_one_padding_space(self):
        self.assertEqual(len(stt.RECORDING + " "), 16)
        self.assertEqual(len(stt.TRANSCRIBING + " "), 19)

    def _run_worker_and_get_chord(self, window_class, mode="auto"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        job = Path(temp.name)
        (job / "audio.wav").write_bytes(b"audio")
        state = {"status": "transcribing", "config": {"auto_paste": True, "paste_mode": mode},
                 "profile": {}, "window": "123", "window_class": window_class}
        (job / "state.json").write_text(json.dumps(state))
        runtime_dir = job / "runtime"
        runtime_dir.mkdir(mode=0o700)
        with mock.patch.object(stt, "transcribe", return_value="transcribed words"), \
             mock.patch.object(stt.subprocess, "run"), mock.patch.object(stt, "replace_placeholder") as replace, \
             mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "notify"), \
             mock.patch.object(stt, "runtime", return_value=runtime_dir):
            stt.worker(str(job))
        self.assertEqual(replace.call_args.args, ("123", 19, ""))
        self.assertEqual(json.loads((job / "state.json").read_text())["status"], "done")
        return xdo.call_args.args

    def test_worker_uses_terminal_paste_chord_for_terminal(self):
        self.assertEqual(self._run_worker_and_get_chord("kitty"),
                         ("key", "--clearmodifiers", "ctrl+shift+v"))

    def test_worker_uses_browser_paste_chord_for_browser(self):
        self.assertEqual(self._run_worker_and_get_chord("firefox"),
                         ("key", "--clearmodifiers", "ctrl+v"))

    def test_worker_honors_explicit_terminal_mode_for_browser(self):
        self.assertEqual(self._run_worker_and_get_chord("firefox", "terminal"),
                         ("key", "--clearmodifiers", "ctrl+shift+v"))

    def test_worker_paste_failure_retains_transcript_and_records_error(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            (job / "audio.wav").write_bytes(b"audio")
            (job / "state.json").write_text(json.dumps({
                "status": "transcribing", "config": {"auto_paste": True}, "profile": {},
                "window": "123", "window_class": "firefox",
            }))
            runtime_dir = job / "runtime"
            runtime_dir.mkdir(mode=0o700)
            with mock.patch.object(stt, "transcribe", return_value="recovered words"), \
                 mock.patch.object(stt.subprocess, "run"), \
                 mock.patch.object(stt, "replace_placeholder", side_effect=RuntimeError("paste failed")), \
                 mock.patch.object(stt, "notify"), \
                 mock.patch.object(stt, "runtime", return_value=runtime_dir):
                stt.worker(str(job))
            state = json.loads((job / "state.json").read_text())
            self.assertEqual(state["status"], "failed")
            self.assertIn("paste failed", state["error"])
            self.assertEqual((job / "transcript.txt").read_text(), "recovered words")
            self.assertTrue((job / "audio.wav").exists())

    def test_worker_clipboard_only_mode_keeps_transcript_without_desktop_paste(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            (job / "audio.wav").write_bytes(b"audio")
            (job / "state.json").write_text(json.dumps({
                "status": "transcribing", "config": {"auto_paste": False}, "profile": {},
                "window": "123", "window_class": "firefox",
            }))
            runtime_dir = job / "runtime"
            runtime_dir.mkdir(mode=0o700)
            with mock.patch.object(stt, "transcribe", return_value="clipboard words"), \
                 mock.patch.object(stt.subprocess, "run") as clipboard, \
                 mock.patch.object(stt, "replace_placeholder") as replace, \
                 mock.patch.object(stt, "xdo") as xdo, mock.patch.object(stt, "notify"), \
                 mock.patch.object(stt, "runtime", return_value=runtime_dir):
                stt.worker(str(job))
            state = json.loads((job / "state.json").read_text())
            self.assertEqual(state["status"], "clipboard")
            self.assertEqual((job / "transcript.txt").read_text(), "clipboard words")
            self.assertFalse((job / "audio.wav").exists())
            clipboard.assert_called_once()
            replace.assert_not_called()
            xdo.assert_not_called()

    def test_config_requires_one_space_padding_for_16_19_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.json"
            data = {"provider": "p", "providers": {"p": profile()}, "placeholder_padding": "  "}
            config_path.write_text(json.dumps(data))
            with mock.patch.object(stt, "CONFIG", config_path):
                with self.assertRaisesRegex(ValueError, "padding space"):
                    stt.load_config()
            data["placeholder_padding"] = " "
            config_path.write_text(json.dumps(data))
            with mock.patch.object(stt, "CONFIG", config_path):
                self.assertEqual(stt.load_config()[1]["adapter"], "openai")


if __name__ == "__main__":
    unittest.main()
