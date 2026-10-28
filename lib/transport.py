"""Small, non-retrying HTTPS JSON transport for speech providers."""
import json
import socket
import ssl
import urllib.error
import urllib.request


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ProviderTransportError(ValueError):
    """Sanitized provider failure with an explicit retry-safety classification."""

    def __init__(self, message, *, category, outcome_unknown=False, status_code=None):
        super().__init__(message)
        self.category = category
        self.outcome_unknown = outcome_unknown
        self.status_code = status_code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so authorization headers never follow another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderTransportError(
            "Provider redirected request; refusing to forward credentials",
            category="redirect",
            outcome_unknown=False,
        )


def _reason(error):
    return error.reason if isinstance(error, urllib.error.URLError) else error


def _classify_connection_error(error):
    reason = _reason(error)
    if isinstance(reason, socket.gaierror):
        return ProviderTransportError(
            "Provider DNS lookup failed; check network connectivity and endpoint hostname",
            category="dns",
            outcome_unknown=False,
        )
    if isinstance(reason, ssl.SSLCertVerificationError):
        return ProviderTransportError(
            "Provider TLS certificate verification failed; check system certificates and endpoint",
            category="tls_verification",
            outcome_unknown=False,
        )
    if isinstance(reason, ssl.SSLError):
        return ProviderTransportError(
            "Provider TLS connection failed; check system certificates and endpoint",
            category="tls",
            outcome_unknown=False,
        )
    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
        return ProviderTransportError(
            "Provider request timed out; the outcome is unknown, so do not blindly retry a possibly billed request",
            category="timeout",
            outcome_unknown=True,
        )
    if isinstance(reason, ConnectionRefusedError):
        return ProviderTransportError(
            "Provider connection was refused; check endpoint availability and network policy",
            category="connection_refused",
            outcome_unknown=False,
        )
    if isinstance(reason, (ConnectionResetError, BrokenPipeError)):
        return ProviderTransportError(
            "Provider connection reset; the outcome is unknown, so do not blindly retry a possibly billed request",
            category="connection_reset",
            outcome_unknown=True,
        )
    return ProviderTransportError(
        "Provider connection failed; check network connectivity and endpoint",
        category="connection",
        outcome_unknown=True,
    )


def request_json(url, key, data=None, content_type=None, timeout=90, bearer=True):
    """Issue one HTTPS provider request and decode a bounded JSON response.

    The caller owns endpoint validation. This function never retries, follows
    redirects, or includes request data, credentials, response bodies, or URLs
    in its errors.
    """
    headers = {
        "Authorization": ("Bearer " if bearer else "") + key,
        "User-Agent": "STTAnywhere/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ProviderTransportError(
            f"Provider HTTP {error.code}; check credentials, endpoint, quota and audio format",
            category="http",
            outcome_unknown=False,
            status_code=error.code,
        ) from None
    except urllib.error.URLError as error:
        raise _classify_connection_error(error) from None
    except (OSError, TimeoutError) as error:
        raise _classify_connection_error(error) from None

    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderTransportError(
            "Provider response is too large",
            category="response_too_large",
            outcome_unknown=False,
        )
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderTransportError(
            "Provider returned invalid JSON",
            category="invalid_json",
            outcome_unknown=False,
        ) from None
