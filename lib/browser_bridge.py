"""Private Unix-socket client for the Chrome native messaging bridge."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
import uuid

MAX_MESSAGE = 1_048_576
DEFAULT_TIMEOUT = 8.0


class BrowserBridgeError(RuntimeError):
    def __init__(self, message, *, category="protocol", safe_to_fallback=False, outcome_unknown=False):
        super().__init__(message)
        self.category = category
        self.safe_to_fallback = safe_to_fallback
        self.outcome_unknown = outcome_unknown


def _read_exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        data = sock.recv(size - len(chunks))
        if not data:
            raise BrowserBridgeError("Browser bridge closed the connection", category="connection", outcome_unknown=True)
        chunks.extend(data)
    return bytes(chunks)


def _send_json(sock, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_MESSAGE:
        raise BrowserBridgeError("Browser bridge message is too large", category="message_size")
    sock.sendall(struct.pack("<I", len(raw)) + raw)


def _recv_json(sock):
    size = struct.unpack("<I", _read_exact(sock, 4))[0]
    if not 0 < size <= MAX_MESSAGE:
        raise BrowserBridgeError("Invalid browser bridge message size", category="message_size")
    try:
        return json.loads(_read_exact(sock, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BrowserBridgeError("Invalid browser bridge response", category="protocol") from None


def socket_path():
    runtime = os.environ.get("STTANYWHERE_BROWSER_RUNTIME_DIR", f"/tmp/sttanywhere-{os.getuid()}")
    return Path(runtime) / "browser.sock"


def _check_socket_path(path, *, safe_to_fallback):
    if not path.is_absolute():
        raise BrowserBridgeError("Unsafe browser bridge runtime path", category="security")
    for component in (Path("/"), *reversed(path.parents)):
        try:
            component_info = component.lstat()
        except OSError:
            raise BrowserBridgeError("Unsafe browser bridge runtime path", category="security") from None
        if stat.S_ISLNK(component_info.st_mode):
            raise BrowserBridgeError("Unsafe browser bridge runtime path", category="security")
    parent = path.parent
    try:
        parent_info = parent.lstat()
        socket_info = path.lstat()
    except FileNotFoundError:
        raise BrowserBridgeError("Browser bridge is not installed or running", category="unavailable", safe_to_fallback=safe_to_fallback) from None
    if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid()
            or stat.S_ISLNK(parent_info.st_mode) or stat.S_IMODE(parent_info.st_mode) & 0o077):
        raise BrowserBridgeError("Unsafe browser bridge runtime directory", category="security")
    if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != os.getuid() or stat.S_IMODE(socket_info.st_mode) & 0o077:
        raise BrowserBridgeError("Unsafe browser bridge socket", category="security")


def request(op, **kwargs):
    """Make one non-retrying capture/replace request to the native host."""
    if op not in ("capture", "replace"):
        raise ValueError("Unsupported browser bridge operation")
    if op == "replace" and (not isinstance(kwargs.get("anchor"), dict) or not isinstance(kwargs.get("replacement"), str)):
        raise ValueError("replace requires an anchor and replacement text")
    payload = {"id": uuid.uuid4().hex, "op": op}
    for key in ("marker", "anchor", "replacement"):
        if key in kwargs:
            payload[key] = kwargs[key]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(DEFAULT_TIMEOUT)
    try:
        path = socket_path()
        _check_socket_path(path, safe_to_fallback=(op == "capture"))
        sock.connect(str(path))
        _send_json(sock, payload)
        reply = _recv_json(sock)
    except (TimeoutError, socket.timeout):
        raise BrowserBridgeError("Browser bridge timed out; operation outcome may be unknown", category="timeout", outcome_unknown=True) from None
    except FileNotFoundError:
        raise BrowserBridgeError("Browser bridge is not installed or running", category="unavailable", safe_to_fallback=(op == "capture")) from None
    except ConnectionRefusedError:
        raise BrowserBridgeError("Browser bridge is not running", category="unavailable", safe_to_fallback=(op == "capture")) from None
    except OSError:
        raise BrowserBridgeError("Browser bridge connection failed; outcome may be unknown", category="connection", outcome_unknown=True) from None
    finally:
        sock.close()
    if not isinstance(reply, dict) or reply.get("id") != payload["id"]:
        raise BrowserBridgeError("Mismatched browser bridge response", category="protocol", outcome_unknown=True)
    if "error" in reply:
        message = str(reply["error"])[:300]
        safe = op == "capture" and any(x in message.lower() for x in ("no focused editable field", "does not allow companion access", "no focused browser window", "no active browser tab"))
        raise BrowserBridgeError(message or "Browser request failed", category="unsupported" if safe else "remote", safe_to_fallback=safe)
    if "result" not in reply:
        raise BrowserBridgeError("Browser bridge returned no result", category="protocol", outcome_unknown=True)
    return reply["result"]
