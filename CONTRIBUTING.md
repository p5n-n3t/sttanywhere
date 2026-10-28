# Contributing to STT Anywhere

Start with the [README](README.md), [verification record](docs/VERIFICATION.md), [alternatives review](docs/ALTERNATIVES.md) and [roadmap](docs/ROADMAP.md).

## Local checks

```bash
bash -n bin/sttanywhere install.sh
python3 -m unittest discover -s tests -v
python3 -m py_compile lib/*.py tests/*.py
git diff --check
```

The offline tests do not use provider credits or type into your desktop. Opt-in integration tests are documented in the README; the legacy Groq integration test makes a potentially billable request.

## Change boundaries

Keep provider transport separate from desktop insertion behavior. Preserve users' private credentials, existing configuration, recovery files and unrelated keyboard shortcuts. Do not add automatic retries of ambiguous paid requests.

For insertion changes, test a moved caret, a different foreground window, and a deleted marker. An operation that cannot verify its target should retain the transcript without raising a window or sending destructive input elsewhere.

For a new provider, provide official API references and tests of request serialization, response parsing and error handling. Mark mocked-only integrations honestly. For a platform adapter, document tested operating-system versions and application limits; Linux tests do not establish Windows or macOS support.

## Reporting bugs and proposing features

Use the issue forms. Include a minimal reproduction and redacted diagnostics; never paste API keys, credentials files or private dictation text. A platform or provider suggestion is welcome even if you cannot implement it.
