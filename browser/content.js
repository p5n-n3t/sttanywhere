(() => {
  'use strict';

  // This object exists for exactly one document/frame lifetime. A replacement
  // routed to a new document therefore cannot find the old capture session.
  const session = randomId();
  const captures = new Map();
  let lastBlurAt = -Infinity;

  window.addEventListener('blur', () => { lastBlurAt = Date.now(); }, true);

  function randomId() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  }

  function fail(message) {
    throw new Error(message);
  }

  function editableTarget(active) {
    if (!active) fail('No focused page field');
    const tag = active.tagName;
    if (tag === 'INPUT') {
      if (active.type.toLowerCase() === 'password') fail('Password fields are not supported');
      if (!['text', 'search', 'url', 'tel'].includes(active.type.toLowerCase())) {
        fail('Focused input is not a text field');
      }
      if (active.disabled || active.readOnly || !active.isConnected) fail('Focused field is unavailable');
      return { kind: 'input', element: active };
    }
    if (tag === 'TEXTAREA') {
      if (active.disabled || active.readOnly || !active.isConnected) fail('Focused field is unavailable');
      return { kind: 'input', element: active };
    }
    const editable = active.isContentEditable ? active : active.closest?.('[contenteditable="true"], [contenteditable="plaintext-only"]');
    if (editable && editable.isContentEditable && editable.isConnected) {
      return { kind: 'editable', element: editable };
    }
    fail('Focused page element is not an editable text field');
  }

  function visibleMarker(id) {
    // Encode the capture id only with zero-width characters so the visible
    // placeholder stays readable and does not expose internal identifiers.
    const bytes = id.match(/../g) || [];
    const hidden = bytes.map((hex) => parseInt(hex, 16).toString(2).padStart(8, '0')
      .replaceAll('0', '\u200b').replaceAll('1', '\u200c')).join('');
    return `(Recording....) \u2063${hidden}\u2063`;
  }

  function setValue(element, value) {
    const prototype = element.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (!setter) fail('Cannot update this field safely');
    setter.call(element, value);
    element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function replaceInputMarker(element, oldMarker, newText) {
    const value = element.value;
    const at = value.indexOf(oldMarker);
    if (at < 0 || countOccurrences(value, oldMarker) !== 1) fail('Recording marker changed or is ambiguous');
    const start = element.selectionStart;
    const end = element.selectionEnd;
    const nextValue = value.slice(0, at) + newText + value.slice(at + oldMarker.length);
    const mapPosition = (position) => {
      if (position == null || position <= at) return position;
      if (position >= at + oldMarker.length) return position + newText.length - oldMarker.length;
      return at + newText.length;
    };
    const mappedStart = mapPosition(start);
    const mappedEnd = mapPosition(end);
    const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (!setter) fail('Cannot update this field safely');
    setter.call(element, nextValue);
    if (mappedStart != null && mappedEnd != null) element.setSelectionRange(mappedStart, mappedEnd);
    element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: newText }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    if (!element.isConnected || countOccurrences(element.value, oldMarker) !== 0) fail('Field changed while replacing the marker');
  }

  function insertMarker(target, marker) {
    const element = target.element;
    if (target.kind === 'input') {
      const start = element.selectionStart;
      const end = element.selectionEnd;
      if (start == null || end == null) fail('Cannot read the field selection');
      setValue(element, element.value.slice(0, start) + marker + element.value.slice(end));
      const caret = start + marker.length;
      element.setSelectionRange(caret, caret);
      return null;
    }

    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) fail('Cannot read the editable selection');
    const range = selection.getRangeAt(0);
    if (!element.contains(range.commonAncestorContainer)) fail('Selection is outside the editable field');
    range.deleteContents();
    const node = document.createTextNode(marker);
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: marker }));
    return node;
  }

  async function capture() {
    const initialActiveElement = document.activeElement;
    const target = editableTarget(initialActiveElement);
    // Alt+X can briefly move focus while the desktop recorder starts. Wait a
    // bounded interval for the same page field to regain focus. Never reuse an
    // old field after focus moved to another page control, the omnibox, or app.
    if (!document.hasFocus()) {
      if (Date.now() - lastBlurAt > 300) fail('No focused page field');
      let focused = false;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 50));
        if (document.activeElement !== initialActiveElement) fail('Page focus moved away from the original field');
        if (document.hasFocus()) {
          focused = true;
          break;
        }
      }
      if (!focused) fail('No focused page field');
    }
    if (document.activeElement !== initialActiveElement) fail('Page focus moved away from the original field');
    editableTarget(initialActiveElement);
    const captureId = randomId();
    const marker = visibleMarker(captureId);
    const nonceSuffix = marker.slice('(Recording....) '.length);
    const markerNode = insertMarker(target, marker);
    if (!target.element.isConnected) fail('Focused field changed during capture');
    if (target.kind === 'input' && countOccurrences(target.element.value, marker) !== 1) fail('Field changed during marker insertion');
    if (target.kind === 'editable' && (!markerNode?.isConnected || !target.element.contains(markerNode) || countOccurrences(target.element.textContent || '', marker) !== 1)) {
      fail('Editable field changed during marker insertion');
    }
    captures.set(captureId, { ...target, marker, markerNode, nonceSuffix, session });
    return { session, captureId, marker: '(Recording....) ', kind: target.kind };
  }

  function countOccurrences(text, needle) {
    let count = 0;
    let from = 0;
    while ((from = text.indexOf(needle, from)) !== -1) {
      count += 1;
      from += needle.length;
    }
    return count;
  }

  function replace({ anchor, replacement, marker }) {
    if (!anchor || anchor.session !== session || typeof anchor.captureId !== 'string') {
      fail('Capture belongs to a different or expired page session');
    }
    const isStatusUpdate = marker === '(Transcribing....) ' || replacement === '(Transcribing....) ';
    if (isStatusUpdate && ((marker != null && marker !== '(Transcribing....) ') || (replacement != null && replacement !== '(Transcribing....) '))) fail('Invalid marker update');
    if (!isStatusUpdate && (marker != null || typeof replacement !== 'string' || replacement.length > 1_000_000)) fail('Invalid transcription text');
    const saved = captures.get(anchor.captureId);
    if (!saved || saved.session !== session || !saved.element.isConnected) fail('Captured field was closed or navigated away');
    const statusText = '(Transcribing....) ';
    const statusMarker = statusText + saved.nonceSuffix;
    const newText = isStatusUpdate ? statusText : replacement;
    const element = saved.element;
    if (saved.kind === 'input') {
      if ((element.tagName === 'INPUT' && element.type.toLowerCase() === 'password') || element.disabled || element.readOnly) {
        fail('Captured field is no longer available');
      }
      replaceInputMarker(element, saved.marker, isStatusUpdate ? statusMarker : newText);
    } else {
      if (!element.isContentEditable || !saved.markerNode || !element.contains(saved.markerNode)) {
        fail('Captured editable field changed');
      }
      if (countOccurrences(element.textContent || '', saved.marker) !== 1 || countOccurrences(saved.markerNode.data, saved.marker) !== 1) {
        fail('Recording marker changed or is ambiguous');
      }
      const at = saved.markerNode.data.indexOf(saved.marker);
      const nextMarker = isStatusUpdate ? statusMarker : newText;
      saved.markerNode.data = saved.markerNode.data.slice(0, at) + nextMarker + saved.markerNode.data.slice(at + saved.marker.length);
      element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: nextMarker }));
      if (!element.isConnected || !saved.markerNode.isConnected || !element.contains(saved.markerNode) || saved.markerNode.data.includes(saved.marker)) {
        fail('Editable field changed while replacing the marker');
      }
    }
    if (isStatusUpdate) saved.marker = statusMarker;
    else captures.delete(anchor.captureId);
    return { inserted: !isStatusUpdate, state: isStatusUpdate ? 'transcribing' : undefined, ...(isStatusUpdate ? { anchor } : {}) };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.channel !== 'sttanywhere-native') return false;
    try {
      if (message.op === 'capture') {
        capture().then((result) => sendResponse({ result }), (error) => sendResponse({ error: error instanceof Error ? error.message : 'Page capture failed' }));
        return true;
      } else if (message.op === 'replace') sendResponse({ result: replace(message) });
      else sendResponse({ error: 'Unsupported operation' });
    } catch (error) {
      sendResponse({ error: error instanceof Error ? error.message : 'Page operation failed' });
    }
    return false;
  });

})();
