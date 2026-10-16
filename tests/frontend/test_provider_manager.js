const assert = require("node:assert/strict");
const test = require("node:test");

global.window = global;
require("../../web/provider_manager.js");

async function fixture() {
  const nodes = new Map();
  const elements = new Proxy({}, { get(_, key) {
    if (!nodes.has(key)) nodes.set(key, {
      value: "", textContent: "", innerHTML: "", disabled: false, hidden: false, files: [], listeners: {},
      querySelectorAll: () => [], addEventListener(event, action) { (this.listeners[event] ||= []).push(action); },
    });
    return nodes.get(key);
  } });
  const source = { id: "test", kind: "image", provider: "openai", label: "Test", api_key: "masked...key",
    base_url: "https://fake.invalid/v1", models: [{ model: "old" }], active_model: "old", options: { watermark: "false", steps: "0" } };
  const state = { selectedProviderId: "test", providerConfig: { active: { image: "test" }, sources: [source] } };
  const controller = FicFrameProviderManager.createController({ state, elements, escapeHtml: String,
    setBusy() {}, checkHealth: async () => {}, api: async () => ({ config: state.providerConfig }),
  });
  controller.bindEvents();
  await controller.loadConfig();
  return { state, source, elements };
}

function row(model, active = false) {
  return { querySelector: (selector) => selector.includes("active") ? { checked: active }
    : { value: selector.includes("nickname") ? "" : model } };
}

test("an empty model row cannot shift the selected active model", async () => {
  const f = await fixture();
  f.elements.modelTable.querySelectorAll = () => [row(""), row("model-a", true), row("model-b")];
  f.elements.providerLabel.listeners.input[0]();
  assert.equal(f.source.active_model, "model-a");
  assert.deepEqual(f.source.models.map((item) => item.model), ["model-a", "model-b"]);
  assert.equal(f.source.api_key, "masked...key");
});

test("changing provider use clears the previous active binding and hides image options", async () => {
  const f = await fixture();
  f.elements.providerKind.value = "llm";
  f.elements.providerKind.listeners.change[0]();
  assert.equal(f.state.providerConfig.active.image, "");
  assert.equal(f.state.providerConfig.active.llm, "test");
  assert.equal(f.elements.imageOptions.hidden, true);
  assert.deepEqual(f.source.options, {});
});

test("zero-valued settings and an explicitly disabled watermark survive form synchronization", async () => {
  const f = await fixture();
  assert.equal(f.elements.imageSteps.value, "0");
  assert.equal(f.elements.imageWatermark.value, "false");
  f.elements.providerLabel.listeners.input[0]();
  assert.equal(f.source.options.steps, "0");
  assert.equal(f.source.options.watermark, "false");
});
