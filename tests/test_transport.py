"""Offline tests for sanitized, single-attempt provider transport."""
import json
import socket
import ssl
import unittest
from unittest import mock
import urllib.error
import urllib.request

from lib import transport


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        self.read_size = size
        return self.body


class ProviderTransportTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://provider.example/v1/transcribe?private=query"
        self.key = "never-print-this-key"

    def open_with(self, result):
        opener = mock.Mock()
        opener.open.return_value = result
        return opener

    def assert_sanitized(self, error):
        self.assertNotIn(self.key, str(error))
        self.assertNotIn(self.url, str(error))

    def test_success_posts_json_and_decodes_response_with_legacy_signature(self):
        response = Response(b'{"text":"hello"}')
        opener = self.open_with(response)
        with mock.patch.object(transport.urllib.request, "build_opener", return_value=opener) as build:
            result = transport.request_json(self.url, self.key, b'{"audio":"x"}', "application/json", 7, False)
        self.assertEqual(result, {"text": "hello"})
        build.assert_called_once()
        args, kwargs = opener.open.call_args
        request = args[0]
        self.assertIsInstance(request, urllib.request.Request)
        self.assertEqual(request.get_header("Authorization"), self.key)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.data, b'{"audio":"x"}')
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(response.read_size, transport.MAX_RESPONSE_BYTES + 1)

    def test_http_error_preserves_status_compatibility_without_details(self):
        error = urllib.error.HTTPError(self.url, 401, "private response text", {}, None)
        opener = self.open_with(None)
        opener.open.side_effect = error
        with mock.patch.object(transport.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(transport.ProviderTransportError) as caught:
                transport.request_json(self.url, self.key)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.category, "http")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertIn("Provider HTTP 401", str(caught.exception))
        self.assert_sanitized(caught.exception)
        self.assertNotIn("private response text", str(caught.exception))
        error.close()

    def test_connection_failures_are_categorized_without_leaking_details(self):
        certificate_error = ssl.SSLCertVerificationError("certificate leaked details")
        cases = [
            (socket.gaierror("DNS host leaked"), "dns", False),
            (urllib.error.URLError(socket.gaierror("DNS host leaked")), "dns", False),
            (certificate_error, "tls_verification", False),
            (urllib.error.URLError(certificate_error), "tls_verification", False),
            (ConnectionRefusedError("refused at provider url"), "connection_refused", False),
            (urllib.error.URLError(ConnectionRefusedError("refused")), "connection_refused", False),
            (ConnectionResetError("reset with response secret"), "connection_reset", True),
            (urllib.error.URLError(ConnectionResetError("reset")), "connection_reset", True),
            (TimeoutError("secret timed out"), "timeout", True),
            (urllib.error.URLError(TimeoutError("secret timed out")), "timeout", True),
            (urllib.error.URLError("timed out"), "timeout", True),
        ]
        for network_error, category, unknown in cases:
            with self.subTest(category=category, exception=type(network_error).__name__):
                opener = self.open_with(None)
                opener.open.side_effect = network_error
                with mock.patch.object(transport.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(transport.ProviderTransportError) as caught:
                        transport.request_json(self.url, self.key)
                self.assertEqual(caught.exception.category, category)
                self.assertEqual(caught.exception.outcome_unknown, unknown)
                self.assert_sanitized(caught.exception)
                opener.open.assert_called_once()  # no retries for potentially billed requests

    def test_redirect_handler_blocks_forwarding_credentials(self):
        request = urllib.request.Request(self.url, headers={"Authorization": self.key})
        with self.assertRaises(transport.ProviderTransportError) as caught:
            transport.NoRedirect().redirect_request(
                request, None, 307, "Temporary Redirect", {}, "https://other.example/secret"
            )
        self.assertEqual(caught.exception.category, "redirect")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assert_sanitized(caught.exception)
        self.assertNotIn("other.example", str(caught.exception))

    def test_oversized_response_is_rejected(self):
        opener = self.open_with(Response(b"x" * (transport.MAX_RESPONSE_BYTES + 1)))
        with mock.patch.object(transport.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(transport.ProviderTransportError) as caught:
                transport.request_json(self.url, self.key)
        self.assertEqual(caught.exception.category, "response_too_large")
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(str(caught.exception), "Provider response is too large")

    def test_invalid_json_and_invalid_utf8_are_sanitized(self):
        for body in (b"not json with private provider body", b"\xff\xfe"):
            with self.subTest(body=body):
                opener = self.open_with(Response(body))
                with mock.patch.object(transport.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(transport.ProviderTransportError) as caught:
                        transport.request_json(self.url, self.key)
                self.assertEqual(caught.exception.category, "invalid_json")
                self.assertFalse(caught.exception.outcome_unknown)
                self.assertNotIn("private provider body", str(caught.exception))
                self.assert_sanitized(caught.exception)


if __name__ == "__main__":
    unittest.main()
