"""Offline tests for setup planning and installer preflight boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import subprocess

from lib import install, setup_wizard as setup


ROOT = Path(__file__).resolve().parents[1]


class SetupWizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.config_home = self.root / "config"
        self.home.mkdir()
        self.config_home.mkdir()

    def write_config(self, cfg):
        dest = self.config_home / "sttanywhere"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "config.json"
        path.write_text(json.dumps(cfg))
        return path

    def base_config(self):
        return json.loads((ROOT / "config/config.example.json").read_text())

    def make_plan(self, args, *, env=None):
        patch = mock.patch.dict(os.environ, env or {}, clear=False)
        with patch:
            return setup.plan(ROOT, args, config_home=self.config_home, home=self.home)

    def test_plan_preserves_existing_unrelated_config_fields(self):
        cfg = self.base_config()
        cfg["user_extension"] = {"keep": [1, "two"]}
        cfg["providers"]["groq"]["vendor_option"] = {"flag": True}
        self.write_config(cfg)
        args = setup.parser().parse_args(["--non-interactive", "--shortcut", "<Control><Shift>space"])
        plan = self.make_plan(args)
        self.assertEqual(plan["config"]["user_extension"], cfg["user_extension"])
        self.assertEqual(plan["config"]["providers"]["groq"]["vendor_option"], {"flag": True})
        self.assertEqual(plan["config"]["shortcut"], "<Control><Shift>space")

    def test_private_credential_precedes_environment_and_legacy(self):
        cfg = self.base_config()
        self.write_config(cfg)
        dest = self.config_home / "sttanywhere"
        (dest / "credentials.env").write_text("GROQ_API_KEY=private-value\nOTHER=value\n")
        (self.home / ".env").write_text("GROQ_API_KEY=legacy-value\n")
        plan = self.make_plan(setup.parser().parse_args(["--non-interactive"]),
                              env={"GROQ_API_KEY": "environment-value"})
        self.assertEqual(setup.assignments(plan["credentials"])["GROQ_API_KEY"], "private-value")
        self.assertIn("OTHER=value", plan["credentials"])

    def test_environment_credential_precedes_legacy_import(self):
        self.write_config(self.base_config())
        (self.home / ".env").write_text("GROQ_API_KEY=legacy-value\n")
        plan = self.make_plan(setup.parser().parse_args(["--non-interactive"]),
                              env={"GROQ_API_KEY": "environment-value"})
        self.assertEqual(setup.assignments(plan["credentials"])["GROQ_API_KEY"], "environment-value")

    def test_legacy_credential_shell_syntax_is_parsed_as_data_without_execution(self):
        self.write_config(self.base_config())
        marker = self.root / "must-not-exist"
        shell_expression = f'$(touch {marker})'
        (self.home / ".env").write_text(f'GROQ_API_KEY="{shell_expression}"\n')
        plan = self.make_plan(setup.parser().parse_args(["--non-interactive"]), env={"GROQ_API_KEY": ""})
        self.assertFalse(marker.exists())
        self.assertEqual(setup.assignments(plan["credentials"])["GROQ_API_KEY"], shell_expression)

    def test_preview_never_displays_secret_value(self):
        self.write_config(self.base_config())
        secret = "private-secret-value"
        (self.config_home / "sttanywhere" / "credentials.env").write_text(f"GROQ_API_KEY={secret}\n")
        plan = self.make_plan(setup.parser().parse_args(["--non-interactive", "--no-bind"]))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            setup.preview(plan)
        self.assertIn("available (hidden)", output.getvalue())
        self.assertNotIn(secret, output.getvalue())

    def test_dry_run_with_deps_creates_no_files_or_runs_installer(self):
        env = {"XDG_CONFIG_HOME": str(self.config_home)}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(setup.Path, "home", return_value=self.home), \
             mock.patch.object(install, "preflight") as preflight, \
             mock.patch.object(install, "apply") as apply, \
             mock.patch.object(install.subprocess, "run") as run:
            with mock.patch("sys.argv", ["install", "--dry-run", "--deps"]):
                install.main()
        self.assertFalse((self.config_home / "sttanywhere").exists())
        preflight.assert_not_called()
        apply.assert_not_called()
        run.assert_not_called()

    def test_no_bind_preflight_needs_no_desktop_or_systemd(self):
        plan = {"home": self.home, "no_bind": True, "config": {"shortcut": "<Alt>x"}}
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(install, "call") as call, mock.patch.object(install.shutil, "which") as which:
            self.assertEqual(install.preflight(plan), ("", ""))
        call.assert_not_called()
        which.assert_not_called()

    def test_shortcut_conflict_fails_in_preflight_before_any_write(self):
        self.write_config(self.base_config())
        env = {"XDG_CONFIG_HOME": str(self.config_home), "DISPLAY": ":test"}
        conflict = subprocess.CompletedProcess([], 0, stdout="/commands/custom/<Alt>x unrelated-command\n", stderr="")
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(setup.Path, "home", return_value=self.home), \
             mock.patch.object(install.shutil, "which", return_value="/mock/bin/tool"), \
             mock.patch.object(install, "call", return_value=conflict) as call, \
             mock.patch.object(install, "apply") as apply:
            with mock.patch("sys.argv", ["install", "--non-interactive"]):
                with self.assertRaisesRegex(ValueError, "belongs to another command"):
                    install.main()
        apply.assert_not_called()
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.config_home / "sttanywhere" / "credentials.env").exists())
        self.assertEqual(call.call_count, 1)

    def test_invalid_endpoints_shortcuts_and_custom_placeholders_are_rejected(self):
        for invalid in (
            ("endpoint", "http://api.example/v1"),
            ("endpoint", "https://user:pass@api.example/v1"),
            ("shortcut", "Ctrl+Alt+x"),
        ):
            cfg = self.base_config()
            field, value = invalid
            if field == "endpoint":
                cfg["providers"]["groq"]["endpoint"] = value
            else:
                cfg[field] = value
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                setup.validate(cfg)
        cfg = self.base_config()
        cfg["provider"] = "custom"
        with self.assertRaisesRegex(ValueError, "placeholders"):
            setup.validate(cfg)

    def test_masked_key_replacement_updates_selected_key_only(self):
        self.write_config(self.base_config())
        creds = self.config_home / "sttanywhere" / "credentials.env"
        creds.write_text("# keep comment\nGROQ_API_KEY=old-value\nOTHER_KEY=keep-me\nGROQ_API_KEY=duplicate\n")
        choices = iter(["groq", "skip", "anchored", "replace", "skip"])
        def ask(label, default):
            return default
        env = {"XDG_CONFIG_HOME": str(self.config_home)}
        args = setup.parser().parse_args(["--interactive", "--no-bind"])
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(setup.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(setup.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(setup, "choose", side_effect=lambda *a, **k: next(choices)), \
             mock.patch.object(setup, "ask", side_effect=ask), \
             mock.patch.object(setup, "microphone_sources", return_value=[]), \
             mock.patch.object(setup, "getpass") as getpass:
            getpass.getpass.return_value = "replacement-secret"
            plan = setup.plan(ROOT, args, config_home=self.config_home, home=self.home)
        assignments = setup.assignments(plan["credentials"])
        self.assertEqual(assignments["GROQ_API_KEY"], "replacement-secret")
        self.assertEqual(assignments["OTHER_KEY"], "keep-me")
        self.assertIn("# keep comment", plan["credentials"])
        self.assertEqual(plan["credentials"].count("GROQ_API_KEY="), 1)
        getpass.getpass.assert_called_once()

    def test_interactive_cancel_and_final_decline_leave_files_unchanged(self):
        self.write_config(self.base_config())
        args = setup.parser().parse_args(["--interactive", "--no-bind"])
        with mock.patch.object(setup.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(setup.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(setup, "choose", side_effect=setup.Cancelled), \
             mock.patch.object(setup, "microphone_sources", return_value=[]):
            with self.assertRaises(setup.Cancelled):
                setup.plan(ROOT, args, config_home=self.config_home, home=self.home)
        self.assertFalse((self.config_home / "sttanywhere" / "credentials.env").exists())

        choices = iter(["groq", "skip", "anchored", "later", "skip"])
        def ask(label, default):
            return "no" if label.startswith("Apply this plan?") else default
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}, clear=False), \
             mock.patch.object(setup.Path, "home", return_value=self.home), \
             mock.patch.object(setup.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(setup.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(setup, "choose", side_effect=lambda *a, **k: next(choices)), \
             mock.patch.object(setup, "ask", side_effect=ask), \
             mock.patch.object(setup, "microphone_sources", return_value=[]), \
             mock.patch.object(install, "preflight", return_value=("", "")) as preflight, \
             mock.patch.object(install, "apply") as apply:
            with mock.patch("sys.argv", ["install", "--interactive", "--no-bind"]):
                with self.assertRaises(setup.Cancelled):
                    install.main()
        preflight.assert_called_once()
        apply.assert_not_called()
        self.assertFalse((self.config_home / "sttanywhere" / "credentials.env").exists())

    def test_interactive_requires_tty_without_mutating_configuration(self):
        self.write_config(self.base_config())
        args = setup.parser().parse_args(["--interactive"])
        with mock.patch.object(setup.sys.stdin, "isatty", return_value=False), \
             mock.patch.object(setup.sys.stdout, "isatty", return_value=False):
            with self.assertRaisesRegex(ValueError, "requires a terminal"):
                setup.plan(ROOT, args, config_home=self.config_home, home=self.home)
        self.assertFalse((self.config_home / "sttanywhere" / "credentials.env").exists())


if __name__ == "__main__":
    unittest.main()
