const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function phone(legacy = false) {
  let resolveFetch;
  let removed = false;
  const timers = [];
  const controls = new Map();
  const context = vm.createContext({
    document: {
      querySelector(selector) {
        if (!controls.has(selector)) controls.set(selector, {});
        return controls.get(selector);
      },
      addEventListener() {},
      createElement() { return { getContext() { return {}; } }; },
    },
    window: { addEventListener() {} },
    location: { hash: "#secret", pathname: legacy ? "/legacy" : "/", host: "localhost:8765" },
    history: { replaceState() {} },
    sessionStorage: {
      getItem() { return null; },
      setItem() {},
      removeItem() { removed = true; },
    },
    phoneMirror: { disconnect() {} },
    fetch() {
      return new Promise((resolve) => { resolveFetch = resolve; });
    },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    clearInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/phone.js"), "utf8"), context);
  const evaluate = (code) => vm.runInContext(code, context);
  evaluate("active = true; epoch = 10; failures = 1;");
  return {
    evaluate, timers, controls,
    resolve(status) { resolveFetch({ status }); },
    pairingRemoved() { return removed; },
  };
}

for (const legacy of [false, true]) {
  for (const status of [204, 403]) {
    test(`${legacy ? "JPEG" : "WebRTC"} token response ${status} cannot affect a replacement session`, async () => {
      const state = phone(legacy);
      const pending = state.evaluate("retry(10)");
      state.evaluate("stopCamera(); active = true; epoch++;");
      state.resolve(status);
      await pending;
      assert.equal(state.evaluate("active"), true);
      assert.equal(state.pairingRemoved(), false);
      assert.equal(state.timers.length, 0);
    });
  }
}

test("a rejected pairing token stops its own session", async () => {
  const state = phone();
  const pending = state.evaluate("retry(10)");
  state.resolve(403);
  await pending;
  assert.equal(state.evaluate("active"), false);
  assert.equal(state.pairingRemoved(), true);
  assert.match(state.controls.get("#status").textContent, /Pairing code changed/);
});

test("a valid pairing token schedules reconnect for its own session", async () => {
  const state = phone();
  const pending = state.evaluate("retry(10)");
  state.resolve(204);
  await pending;
  assert.equal(state.evaluate("active"), true);
  assert.equal(state.timers.length, 1);
});
