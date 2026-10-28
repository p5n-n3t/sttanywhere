#!/usr/bin/python3
"""Bounded AT-SPI editable-text operations; invoked with the system Python."""
import json
import os
from pathlib import Path
import sys
import gi

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

MARKERS = ('(Recording....) ', '(Transcribing....) ')


def token(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def walk(root, limit=1500):
    queue = [root]
    seen = 0
    while queue and seen < limit:
        node = queue.pop(0)
        seen += 1
        yield node
        try:
            queue.extend(node.get_child_at_index(i) for i in range(min(node.get_child_count(), 200)))
        except Exception:
            continue


def locate(data, capture=False):
    pid = int(data['pid'])
    if not capture and token(pid) != data['process_token']:
        raise ValueError('Original application process changed')
    desktop = Atspi.get_desktop(0)
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if app.get_process_id() != pid:
            continue
        for node in walk(app):
            if node is None:
                continue
            if capture:
                states = node.get_state_set()
                if states.contains(Atspi.StateType.FOCUSED) and node.get_role() == Atspi.Role.PASSWORD_TEXT:
                    raise ValueError('Protected text fields do not support automatic insertion')
                if states.contains(Atspi.StateType.FOCUSED) and states.contains(Atspi.StateType.EDITABLE) and node.get_role() != Atspi.Role.PASSWORD_TEXT and node.get_editable_text_iface() and node.get_text_iface():
                    return node
            elif str(node.path) == data['path']:
                if not node.get_state_set().contains(Atspi.StateType.EDITABLE):
                    raise ValueError('Original text field is no longer editable')
                return node
    raise ValueError('No accessible editable target; clipboard fallback required')


def text_of(node):
    iface = node.get_text_iface()
    if iface.get_character_count() > 2_000_000:
        raise ValueError('Text field exceeds accessibility safety limit')
    return iface, Atspi.Text.get_text(iface, 0, -1)


def main():
    Atspi.set_timeout(1500, 3000)
    command = sys.argv[1]
    data = json.load(sys.stdin)
    node = locate(data, capture=command in ('capture', 'probe'))
    if command == 'probe':
        print(json.dumps({'supported': True, 'role': node.get_role_name()}))
        return
    text, before = text_of(node)
    edit = node.get_editable_text_iface()
    if command == 'capture':
        if any(marker in before for marker in MARKERS):
            raise ValueError('An existing dictation marker makes this field ambiguous')
        if text.get_n_selections() > 1:
            raise ValueError('Multiple selected ranges are ambiguous')
        offset = text.get_caret_offset()
        marker = data['marker']
        removed = ''
        if text.get_n_selections() == 1:
            selected = Atspi.Text.get_selection(text,0)
            start, end = selected.start_offset, selected.end_offset
            if 0 <= start < end <= len(before):
                offset = start
                removed = before[start:end]
                if not edit.delete_text(start,end):
                    raise ValueError('Application rejected selected text replacement')
        if not 0 <= offset <= len(before):
            raise ValueError('Application did not expose a valid caret')
        if not edit.insert_text(offset, marker, len(marker.encode())):
            if removed:
                edit.insert_text(offset,removed,len(removed.encode()))
            raise ValueError('Application rejected marker insertion')
        if Atspi.Text.get_text(text, offset, offset+len(marker)) != marker:
            raise ValueError('Marker insertion could not be verified')
        text.set_caret_offset(offset+len(marker))
        result = {'pid': int(data['pid']), 'process_token': token(data['pid']), 'path': str(node.path), 'marker': marker}
    else:
        old, new = data['marker'], data['replacement']
        if before.count(old) != 1:
            raise ValueError('Original marker was changed, removed or duplicated; text left untouched')
        start = before.index(old)
        end = start + len(old)
        if not edit.delete_text(start, end):
            raise ValueError('Application rejected marker deletion')
        if not edit.insert_text(start, new, len(new.encode())):
            # Best effort restoration rather than losing the user's marker.
            edit.insert_text(start, old, len(old.encode()))
            raise ValueError('Application rejected transcription insertion')
        actual = Atspi.Text.get_text(text, 0, -1)
        expected = before[:start] + new + before[end:]
        if actual != expected:
            raise ValueError('Concurrent document edit detected; result saved for manual review')
        # Let the editor's own buffer marks track the caret and selections.
        # AT-SPI SetCaretOffset/SetSelection can grab GTK focus, even when
        # editing a background document. Never invoke them on completion.
        result = dict(data)
        result['marker'] = new
        result.pop('replacement', None)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)
