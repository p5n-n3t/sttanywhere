"""Fail-closed tests for managed terminal dictation anchors."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lib import terminal_bridge as bridge


class ManagedTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'runtime'
        self.base.mkdir(mode=0o700)
        self.base.chmod(0o700)
        self.patch_runtime = mock.patch.object(bridge, 'runtime_dir', return_value=self.base)
        self.patch_runtime.start()
        self.addCleanup(self.patch_runtime.stop)
        self.path = self.base / 'terminal-123.json'
        self.reg = {'uid': os.getuid(), 'owner_pid': 123, 'owner_token': 'owner-token',
                    'socket': 'sttanywhere-test', 'session': 'stt-test', 'pane': '%1',
                    'pane_pid': 321, 'pane_token': 'pane-token'}
        self.path.write_text(json.dumps(self.reg))
        self.path.chmod(0o600)

    def test_discover_requires_one_registered_owner_in_window_ancestry(self):
        with mock.patch.object(bridge, '_registrations', return_value=[(self.path, self.reg)]), \
             mock.patch.object(bridge, 'is_descendant', side_effect=[True]), \
             mock.patch.object(bridge, '_pane_meta', return_value={'id': '%1'}):
            self.assertEqual(bridge.discover(45, '88'), (self.path, self.reg))

    def test_capture_sends_literal_marker_to_exact_pane_without_enter(self):
        meta = {'id': '%1', 'tty': '/dev/pts/4', 'pid': 321, 'token': 'pane-token',
                'command': 'zsh', 'x': 4, 'y': 0, 'foreground_pid': 321,
                'foreground_token': 'shell-token'}
        with mock.patch.object(bridge, 'discover', return_value=(self.path, self.reg)), \
             mock.patch.object(bridge, '_snapshot', side_effect=[('before', meta, 'prompt'),
                                                                    ]), \
             mock.patch.object(bridge, '_wait_screen', return_value=('after', {**meta, 'x': 20}, 'prompt(Recording....) ')), \
             mock.patch.object(bridge, '_tmux') as tmux:
            anchor = bridge.capture({'window_pid': 42, 'window': '88'}, '(Recording....) ')
        self.assertEqual(anchor['snapshot'], 'after')
        self.assertEqual(anchor['pane'], '%1')
        self.assertEqual(tmux.call_args.args,
                         ('sttanywhere-test', 'send-keys', '-t', '%1', '-l', '--', '(Recording....) '))
        self.assertNotIn('Enter', tmux.call_args.args)

    def test_changed_screen_or_cursor_refuses_before_backspace(self):
        meta = {'id': '%1', 'tty': '/dev/pts/4', 'pid': 321, 'token': 'pane-token',
                'command': 'codex', 'x': 30, 'y': 2, 'foreground_pid': 455,
                'foreground_token': 'fg-token'}
        anchor = {'kind': 'tmux', 'registry': str(self.path), 'registry_token': 'owner-token',
                  'socket': self.reg['socket'], 'pane': '%1', 'pane_token': 'pane-token',
                  'marker': '(Recording....) ', 'snapshot': 'before',
                  'foreground_pid': 455, 'foreground_token': 'fg-token'}
        with mock.patch.object(bridge, 'alive', return_value=True), \
             mock.patch.object(bridge, '_snapshot', return_value=('changed', meta, 'changed prompt')), \
             mock.patch.object(bridge, '_tmux') as tmux:
            with self.assertRaisesRegex(ValueError, 'changed'):
                bridge.replace(anchor, 'transcript')
        tmux.assert_not_called()

    def test_control_or_multiline_result_is_kept_off_terminal(self):
        anchor = {'kind': 'tmux'}
        for text in ('line\nnext', 'tab\ttext', 'escape\x1b[31m'):
            with self.subTest(text=repr(text)), self.assertRaisesRegex(ValueError, 'unsupported'):
                bridge.replace(anchor, text)


if __name__ == '__main__':
    unittest.main()
