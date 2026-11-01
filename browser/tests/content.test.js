const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

const source = fs.readFileSync(new URL('../content.js', `file://${__filename}`), 'utf8');

class FakeInput {
  constructor(type = 'text', value = 'hello world') {
    this.tagName = 'INPUT';
    this.type = type;
    this._value = value;
    this.selectionStart = 5;
    this.selectionEnd = 5;
    this.disabled = false;
    this.readOnly = false;
    this.isConnected = true;
    this.events = [];
    this.focusCalls = 0;
  }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  dispatchEvent(event) { this.events.push(event.type); return true; }
  focus() { this.focusCalls += 1; }
}
Object.defineProperty(FakeInput.prototype, 'value', {
  get() { return this._value; },
  set(value) { this._value = value; }
});

function harness({ input = new FakeInput(), hasFocus = () => true, activeElement = () => input } = {}) {
  const listeners = [];
  const windowListeners = {};
  const document = { get activeElement() { return activeElement(); }, hasFocus };
  const context = {
    document,
    window: { addEventListener(type, listener) { windowListeners[type] = listener; } },
    crypto: webcrypto,
    HTMLInputElement: FakeInput,
    HTMLTextAreaElement: FakeInput,
    InputEvent: class extends Event { constructor(type, init) { super(type, init); this.data = init.data; } },
    Event,
    setTimeout,
    chrome: { runtime: { onMessage: { addListener(listener) { listeners.push(listener); } } } }
  };
  vm.runInNewContext(source, context, { filename: 'content.js' });
  return { input, document, listener: listeners[0], blur() { windowListeners.blur?.(); } };
}

function request(listener, message) {
  return new Promise((resolve) => {
    const async = listener(message, {}, resolve);
    if (async !== true) resolve(undefined);
  });
}

test('captures a focused text field and replaces only its unique marker without focusing', async () => {
  const h = harness();
  const captured = await request(h.listener, { channel: 'sttanywhere-native', op: 'capture' });
  assert.equal(captured.result.marker, '(Recording....) ');
  const anchor = { tabId: 1, frameId: 0, session: captured.result.session, captureId: captured.result.captureId };
  assert.match(h.input.value, /^hello\(Recording\.\.\.\.\) /);
  assert.doesNotMatch(h.input.value, /[0-9a-f]{32}/);

  // Move the caret after capture to ensure replacement retains its relative
  // location after the marker grows or shrinks.
  h.input.setSelectionRange(h.input.value.length, h.input.value.length);
  const staged = await request(h.listener, {
    channel: 'sttanywhere-native', op: 'replace', anchor,
    replacement: '(Transcribing....) '
  });
  assert.equal(staged.result.state, 'transcribing');
  assert.equal(staged.result.anchor.captureId, anchor.captureId);
  assert.match(h.input.value, /\(Transcribing\.\.\.\.\) /);
  await request(h.listener, {
    channel: 'sttanywhere-native', op: 'replace', anchor, replacement: '(Transcribing....) '
  });
  assert.equal((h.input.value.match(/\(Transcribing\.\.\.\.\)/g) || []).length, 1);

  const result = await request(h.listener, {
    channel: 'sttanywhere-native', op: 'replace', anchor,
    replacement: 'there'
  });
  assert.equal(result.result.inserted, true);
  assert.match(h.input.value, /^hellothere world$/);
  assert.equal(h.input.selectionStart, h.input.value.length);
  assert.equal(h.input.selectionEnd, h.input.value.length);
  assert.equal(h.input.focusCalls, 0);
});

test('rejects password fields and never uses a stale active field after focus moves', async () => {
  const password = new FakeInput('password', 'secret');
  const first = harness({ input: password });
  const denied = await request(first.listener, { channel: 'sttanywhere-native', op: 'capture' });
  assert.match(denied.error, /Password/);
  assert.equal(password.value, 'secret');

  const input = new FakeInput();
  const other = {};
  let focused = false;
  let active = input;
  const h = harness({ input, hasFocus: () => focused, activeElement: () => active });
  h.blur();
  setTimeout(() => { active = other; }, 20);
  const deniedAfterMove = await request(h.listener, { channel: 'sttanywhere-native', op: 'capture' });
  assert.match(deniedAfterMove.error, /focus moved away/);
  assert.equal(input.value, 'hello world');
});

test('waits briefly for the same original field to regain focus', async () => {
  const input = new FakeInput();
  let focused = false;
  const h = harness({ input, hasFocus: () => focused });
  h.blur();
  setTimeout(() => { focused = true; }, 20);
  const captured = await request(h.listener, { channel: 'sttanywhere-native', op: 'capture' });
  assert.ok(captured.result.captureId);
  assert.match(input.value, /\(Recording\.\.\.\.\)/);
});

test('rejects stale anchors and changed or disconnected fields', async () => {
  const h = harness();
  const captured = await request(h.listener, { channel: 'sttanywhere-native', op: 'capture' });
  const anchor = { tabId: 1, frameId: 0, session: captured.result.session, captureId: captured.result.captureId };
  h.input.value = 'marker was removed';
  const changed = await request(h.listener, {
    channel: 'sttanywhere-native', op: 'replace', anchor, replacement: 'unsafe'
  });
  assert.match(changed.error, /marker changed/);

  const h2 = harness();
  const second = await request(h2.listener, { channel: 'sttanywhere-native', op: 'capture' });
  const secondAnchor = { tabId: 1, frameId: 0, session: second.result.session, captureId: second.result.captureId };
  h2.input.isConnected = false;
  const closed = await request(h2.listener, {
    channel: 'sttanywhere-native', op: 'replace', anchor: secondAnchor, replacement: 'unsafe'
  });
  assert.match(closed.error, /closed or navigated/);
});
