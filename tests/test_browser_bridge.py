import importlib.util
import importlib.machinery
import json
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile
import unittest
from unittest import mock

from lib import browser_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_loader("bridge_installer", importlib.machinery.SourceFileLoader("bridge_installer", str(ROOT / "bin/install-browser-bridge")))
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class BrowserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.env = mock.patch.dict(os.environ, {"STTANYWHERE_BROWSER_RUNTIME_DIR": str(self.runtime)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rejects_symlink_runtime_and_insecure_socket(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(bridge.BrowserBridgeError):
            bridge._check_socket_path(link / "browser.sock", safe_to_fallback=True)
        path = self.runtime / "browser.sock"
        path.touch(mode=0o666)
        with self.assertRaises(bridge.BrowserBridgeError):
            bridge._check_socket_path(path, safe_to_fallback=True)

    def test_message_size_is_bounded(self):
        with self.assertRaisesRegex(bridge.BrowserBridgeError, "too large"):
            bridge._send_json(None, {"data": "x" * bridge.MAX_MESSAGE})
        with mock.patch.object(bridge, "_read_exact", return_value=struct.pack("<I", bridge.MAX_MESSAGE + 1)):
            with self.assertRaises(bridge.BrowserBridgeError):
                bridge._recv_json(None)

    def test_mismatched_response_id_is_rejected(self):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sockpath = self.runtime / "test.sock"
        server.bind(str(sockpath)); server.listen(1)
        server.settimeout(3)
        sockpath.chmod(0o600)
        def send_reply():
            try:
                conn, _ = server.accept()
                with conn:
                    packet = conn.recv(4096)
                    size = struct.unpack("<I", packet[:4])[0]
                    json.loads(packet[4:4 + size])
                    raw = json.dumps({"id": "wrong", "result": {}}).encode()
                    conn.sendall(struct.pack("<I", len(raw)) + raw)
            except (OSError, ValueError, json.JSONDecodeError):
                return
        import threading
        worker = threading.Thread(target=send_reply)
        worker.start()
        try:
            with mock.patch.object(bridge, "socket_path", return_value=sockpath):
                with self.assertRaisesRegex(bridge.BrowserBridgeError, "Mismatched"):
                    bridge.request("capture")
        finally:
            server.close()
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive(), "mock host thread did not terminate")

    def test_timeout_is_reported_unknown_and_never_retried(self):
        sock = mock.Mock()
        sock.connect.side_effect = TimeoutError()
        with mock.patch.object(bridge.socket, "socket", return_value=sock), mock.patch.object(bridge, "_check_socket_path"), mock.patch.object(bridge.socket, "timeout", TimeoutError, create=True):
            with self.assertRaises(bridge.BrowserBridgeError) as caught:
                bridge.request("capture")
        self.assertTrue(caught.exception.outcome_unknown)
        sock.connect.assert_called_once()

    def test_installer_registration_is_repeatable_and_limits_origin(self):
        cfg = Path(self.temp.name) / "config"
        with mock.patch.dict(os.environ, {"STTANYWHERE_BROWSER_CONFIG_ROOT": str(cfg)}), mock.patch.object(installer.os, "chmod"):
            installer.main()
            paths = [cfg / browser / "NativeMessagingHosts" / "org.sttanywhere.bridge.json" for browser in ("google-chrome", "chromium")]
            before = [p.read_text() for p in paths]
            installer.main()
        for path, original in zip(paths, before):
            registration = json.loads(path.read_text())
            self.assertEqual(json.dumps(registration), json.dumps(json.loads(original)))
            self.assertEqual(registration["allowed_origins"], [f"chrome-extension://{installer.extension_id(json.loads((ROOT / 'browser/manifest.json').read_text()))}/"])
            self.assertNotIn("credential", path.read_text().lower())


if __name__ == "__main__":
    unittest.main()
