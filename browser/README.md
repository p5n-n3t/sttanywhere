# STT Anywhere Chrome companion

This unpacked Chrome/Chromium Manifest V3 extension lets the native STT Anywhere host place a recording marker into the focused webpage field and replace it later in the same document. It uses the native messaging host name `org.sttanywhere.bridge`.

## Install

1. Open `chrome://extensions` (or `chrome://extensions` in Chromium) and enable **Developer mode**.
2. Choose **Load unpacked** and select this `browser/` directory.
3. Confirm Chrome assigns extension ID `ochfgaejnengehgclcffigbnidpgnjhe`.
4. From the repository checkout, run `./bin/install-browser-bridge` and restart Chrome/Chromium.

The extension has no build step. Keep the repository at the same path after registering the host because the native messaging manifest points to the checkout's host executable.

The native host owns one per-user Unix socket, so use the companion from one Chrome or Chromium browser instance at a time.

## Native message contract

Native requests and responses are JSON objects over Chrome's native messaging port framing. Each response echoes the request's `id` and contains either `result` or `error`.

```json
{"id":1,"op":"capture"}
```

Successful capture returns `result` with a full `anchor` (`tabId`, `frameId`, `session`, and `captureId`), the readable marker text, and the target kind. Send the full anchor back unchanged for both updates:

```json
{"id":2,"op":"replace","anchor":{"tabId":3,"frameId":0,"session":"…","captureId":"…"},"replacement":"(Transcribing....) "}
{"id":3,"op":"replace","anchor":{"tabId":3,"frameId":0,"session":"…","captureId":"…"},"replacement":"recognized words"}
```

The transcribing update keeps the anchor and returns `{ "inserted": false, "state": "transcribing", "anchor": ... }`. Final text returns `{ "inserted": true }` and consumes the anchor. A final replacement is accepted once. Native errors include a short reason such as an expired anchor, changed marker, unsupported field, or lost focus.

## Supported fields and safety

- Text inputs of type `text`, `search`, `url`, and `tel`; `textarea`; and ordinary `contenteditable` fields.
- Capture is limited to the focused Chrome window, its active tab, and a document whose `hasFocus()` is true. A brief Alt+X focus transition is allowed only while the same window and original field regain focus within 300 ms.
- Password and unsupported inputs, browser UI/restricted pages, missing or duplicate markers, disconnected fields, and navigated documents are rejected.
- Final insertion dispatches normal `input` and `change` events in the captured element. It never calls `focus()`; text input selection offsets are adjusted around the replaced marker without focusing the field.
- Rich editors that rewrite or split their editable DOM may reject capture or replacement. Canvas editors, browser address bars, and Firefox are not supported by this extension.

## Local checks

Run the build-free content-script tests with:

```sh
node --test browser/tests/content.test.js
```
