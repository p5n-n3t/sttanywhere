'use strict';

const NATIVE_HOST = 'org.sttanywhere.bridge';
const anchors = new Map();
const inFlight = new Set();
let port = null;
let reconnectTimer = null;
let reconnectDelay = 250;

function sendNative(message) {
  if (!port) return false;
  try {
    port.postMessage(message);
    return true;
  } catch (_error) {
    return false;
  }
}

function reply(id, result, error) {
  const message = { id };
  if (error) message.error = String(error);
  else message.result = result;
  sendNative(message);
}

function invalidate(tabId, frameId) {
  for (const [captureId, anchor] of anchors) {
    if (anchor.tabId === tabId && (frameId == null || anchor.frameId === frameId)) anchors.delete(captureId);
  }
}

async function capture(id) {
  const originalWindow = await chrome.windows.getLastFocused();
  if (!originalWindow.id) throw new Error('No focused browser window');
  let focusedWindow = originalWindow;
  for (let attempt = 0; !focusedWindow.focused && attempt < 6; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    focusedWindow = await chrome.windows.getLastFocused();
    if (focusedWindow.id !== originalWindow.id) throw new Error('Browser focus moved to a different window');
  }
  if (!focusedWindow.focused) throw new Error('No focused browser window');
  const [tab] = await chrome.tabs.query({ active: true, windowId: focusedWindow.id });
  if (!tab || !tab.id || tab.active !== true) throw new Error('No active browser tab');
  if (!tab.url || /^(chrome|edge|about|chrome-extension):/i.test(tab.url)) throw new Error('Active tab does not allow companion access');
  const frames = await chrome.webNavigation.getAllFrames({ tabId: tab.id });
  let lastError = 'No focused editable field in the active tab';
  const responses = await Promise.all((frames || []).map(async (frame) => {
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { channel: 'sttanywhere-native', op: 'capture' }, { frameId: frame.frameId });
      return { frame, response };
    } catch (error) {
      return { frame, error };
    }
  }));
  let fatalError = null;
  for (const { frame, response, error } of responses) {
    if (error) {
      const message = String(error?.message || error);
      // These errors indicate a frame with no injected receiver or a browser
      // restriction. Other transport failures might follow a field mutation.
      if (!/Receiving end does not exist|Cannot access contents|Frame was removed|No tab with id/i.test(message)) fatalError ||= error;
      continue;
    }
    if (!response || response.error) {
      lastError = response?.error || lastError;
      continue;
    }
    const { session, captureId, marker, kind } = response.result || {};
    if (!session || !captureId) {
      lastError = 'Page returned an invalid capture anchor';
      continue;
    }
    const anchor = { tabId: tab.id, frameId: frame.frameId, session, captureId };
    anchors.set(captureId, anchor);
    reply(id, { anchor, marker, kind });
    return;
  }
  if (fatalError) throw fatalError;
  throw new Error(lastError);
}

async function replace(id, request) {
  const supplied = request.anchor;
  if (!supplied || typeof supplied.captureId !== 'string') throw new Error('Missing capture anchor');
  const known = anchors.get(supplied.captureId);
  if (!known || known.tabId !== supplied.tabId || known.frameId !== supplied.frameId || known.session !== supplied.session) {
    throw new Error('Capture anchor expired or does not match');
  }
  if (inFlight.has(supplied.captureId)) throw new Error('A replacement is already in progress for this capture');
  inFlight.add(supplied.captureId);
  try {
    const response = await chrome.tabs.sendMessage(known.tabId, {
      channel: 'sttanywhere-native',
      op: 'replace',
      anchor: known,
      marker: request.marker,
      replacement: request.replacement
    }, { frameId: known.frameId });
    if (!response || response.error) throw new Error(response?.error || 'Captured page did not respond');
    if (response.result?.inserted) anchors.delete(supplied.captureId);
    reply(id, response.result);
  } finally {
    inFlight.delete(supplied.captureId);
  }
}

async function handleNative(request) {
  const id = request && request.id;
  if (id == null) return;
  try {
    if (request.op === 'capture') await capture(id);
    else if (request.op === 'replace') await replace(id, request);
    else throw new Error('Unsupported operation');
  } catch (error) {
    reply(id, null, error instanceof Error ? error.message : 'Browser request failed');
  }
}

function connectNative() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (error) {
    console.warn('STT Anywhere native host connection failed:', error instanceof Error ? error.message : String(error));
    scheduleReconnect();
    return;
  }
  port.onMessage.addListener((request) => { void handleNative(request); });
  port.onDisconnect.addListener(() => {
    // Chrome exposes the host launch/registration failure only during this
    // callback. Read lastError here and avoid logging requests or transcripts.
    const reason = chrome.runtime.lastError?.message || 'unknown native host disconnect';
    console.warn('STT Anywhere native host disconnected:', reason);
    port = null;
    scheduleReconnect();
  });
  reconnectDelay = 250;
}

function scheduleReconnect() {
  if (reconnectTimer != null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNative();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, 10_000);
}

chrome.tabs.onRemoved.addListener((tabId) => invalidate(tabId));
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading' || changeInfo.url) invalidate(tabId);
});
chrome.webNavigation.onCommitted.addListener(({ tabId, frameId }) => invalidate(tabId, frameId));
chrome.webNavigation.onHistoryStateUpdated.addListener(({ tabId, frameId }) => invalidate(tabId, frameId));
chrome.webNavigation.onReferenceFragmentUpdated.addListener(({ tabId, frameId }) => invalidate(tabId, frameId));

connectNative();
