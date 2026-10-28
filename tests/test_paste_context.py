"""Focused, process-independent tests for paste chord policy."""
import unittest

from lib.paste_context import paste_chord


class PasteChordTests(unittest.TestCase):
    def test_codex_foreground_uses_regular_paste_even_in_terminal_window(self):
        cfg = {"paste_rules": [{"match": {"foreground_process": "codex|claude"}, "chord": "ctrl+v"}]}
        for process in ("codex", "claude", "claude-code"):
            with self.subTest(process=process):
                self.assertEqual(paste_chord(cfg, {
                    "foreground_process": process, "window_class": "kitty"
                }), "ctrl+v")

    def test_shell_foreground_uses_terminal_fallback_chord(self):
        cfg = {
            "paste_rules": [{"match": {"foreground_process": "codex|claude"}, "chord": "ctrl+v"}],
            "paste_mode": "auto",
            "terminal_pattern": "warp|kitty|xterm",
        }
        self.assertEqual(paste_chord(cfg, {
            "foreground_process": "bash", "window_class": "kitty"
        }), "ctrl+shift+v")

    def test_window_title_rule_handles_codex_or_claude_without_foreground_process(self):
        cfg = {
            "paste_rules": [{"match": {"window_name": "codex|claude"}, "chord": "ctrl+v"}],
            "paste_mode": "auto",
            "terminal_pattern": "warp|kitty|xterm",
        }
        for title in ("OpenAI Codex", "Claude Code"):
            with self.subTest(title=title):
                self.assertEqual(paste_chord(cfg, {
                    "window_name": title, "foreground_process": "", "window_class": "kitty"
                }), "ctrl+v")

    def test_first_matching_custom_rule_takes_priority(self):
        cfg = {
            "paste_rules": [
                {"match": {"window_class": "kitty", "foreground_process": "codex"},
                 "chord": "ctrl+alt+v"},
                {"match": {"foreground_process": "codex|claude"}, "chord": "ctrl+v"},
            ],
            "paste_mode": "terminal",
        }
        self.assertEqual(paste_chord(cfg, {
            "window_class": "kitty", "foreground_process": "codex"
        }), "ctrl+alt+v")


if __name__ == "__main__":
    unittest.main()
