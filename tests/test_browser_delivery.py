"""Browser anchored delivery must stay on its original document target."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from lib import sttanywhere as stt


class BrowserDeliveryTests(unittest.TestCase):
    def test_browser_detection_is_limited_to_chrome_and_chromium(self):
        for window_class in ('"Google-chrome" "google-chrome"', '"chromium" "Chromium"', '"chromium-browser"'):
            with self.subTest(window_class=window_class):
                self.assertTrue(stt.is_chrome_or_chromium({'window_class': window_class}))
        for window_class in ('"firefox" "Firefox"', '"brave-browser" "Brave"', '"microsoft-edge" "Edge"'):
            with self.subTest(window_class=window_class):
                self.assertFalse(stt.is_chrome_or_chromium({'window_class': window_class}))

    def test_chrome_capture_precedes_atspi_and_ambiguous_timeout_is_not_retried(self):
        context = {'window_class': '"Google-chrome" "google-chrome"', 'window_pid': 91, 'window': '42'}
        browser_anchor = {'kind': 'browser', 'anchor': {'tabId': 3}, 'marker': stt.RECORDING + ' '}
        with mock.patch.object(stt, 'capture_browser', return_value=browser_anchor) as browser, \
             mock.patch.object(stt, 'accessible') as atspi:
            self.assertEqual(stt.capture_anchor(context, stt.RECORDING + ' '), browser_anchor)
        browser.assert_called_once_with(context, stt.RECORDING + ' ')
        atspi.assert_not_called()

        with mock.patch.object(stt, 'capture_browser', side_effect=TimeoutError('ambiguous timeout')), \
             mock.patch.object(stt, 'accessible') as atspi:
            with self.assertRaisesRegex(TimeoutError, 'ambiguous timeout'):
                stt.capture_anchor(context, stt.RECORDING + ' ')
        atspi.assert_not_called()

        unavailable = RuntimeError('no focused editable field')
        unavailable.safe_to_fallback = True
        with mock.patch.object(stt, 'capture_browser', side_effect=unavailable), \
             mock.patch.object(stt, 'accessible', return_value={'backend': 'atspi'}) as atspi:
            self.assertEqual(stt.capture_anchor(context, stt.RECORDING + ' '), {'backend': 'atspi'})
        atspi.assert_called_once_with('capture', {'pid': 91, 'marker': stt.RECORDING + ' '})

    def test_browser_transition_and_completion_keep_captured_anchor_after_focus_switch(self):
        captured = {'backend': 'browser', 'browser_anchor': {'kind': 'browser',
                    'anchor': {'tabId': 8, 'frameId': 0, 'target': 'original'},
                    'marker': stt.RECORDING + ' '}, 'marker': stt.RECORDING + ' '}
        calls = []
        def request(op, **kwargs):
            calls.append((op, kwargs))
            return {'inserted': kwargs['replacement'] == 'finished words', 'anchor': kwargs['anchor']}
        bridge = types.SimpleNamespace(request=request)
        with mock.patch.object(stt, 'browser_bridge', bridge):
            transition = stt.accessible('replace', {**captured, 'replacement': stt.TRANSCRIBING + ' '})
            complete = stt.accessible('replace', {**transition, 'replacement': 'finished words'})
        self.assertEqual([op for op, _ in calls], ['replace', 'replace'])
        self.assertEqual(calls[0][1]['anchor']['target'], 'original')
        self.assertEqual(calls[1][1]['anchor']['target'], 'original')
        self.assertEqual(calls[1][1]['replacement'], 'finished words')
        self.assertEqual(complete['marker'], 'finished words')
        self.assertEqual(complete['browser_anchor']['anchor']['target'], 'original')

    def test_failed_browser_replacement_leaves_transcript_on_clipboard(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            (job / 'audio.wav').write_bytes(b'audio')
            anchor = {'backend': 'browser', 'browser_anchor': {'kind': 'browser', 'anchor': {'tabId': 8}},
                      'marker': stt.RECORDING + ' '}
            (job / 'state.json').write_text(json.dumps({
                'status': 'transcribing', 'config': {'auto_paste': True}, 'profile': {},
                'window': '42', 'window_class': '"Google-chrome"', 'anchor': anchor,
            }))
            runtime_dir = job / 'runtime'
            runtime_dir.mkdir(mode=0o700)
            bridge = types.SimpleNamespace(request=mock.Mock(side_effect=TimeoutError('browser replacement timed out')))
            with mock.patch.object(stt, 'browser_bridge', bridge), \
                 mock.patch.object(stt, 'transcribe', return_value='recoverable words'), \
                 mock.patch.object(stt.subprocess, 'run') as clipboard, \
                 mock.patch.object(stt, 'notify'), \
                 mock.patch.object(stt, 'runtime', return_value=runtime_dir):
                stt.worker(str(job))
            state = json.loads((job / 'state.json').read_text())
            transcript = (job / 'transcript.txt').read_text()
        self.assertEqual(state['status'], 'clipboard')
        self.assertIn('timed out', state['delivery_reason'])
        self.assertEqual(transcript, 'recoverable words')
        clipboard.assert_called_once_with(['xclip', '-selection', 'clipboard'], input=b'recoverable words', check=True)
