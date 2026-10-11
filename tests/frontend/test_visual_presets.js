const assert = require("node:assert/strict");
const test = require("node:test");
global.window = global;
require("../../web/visual_presets.js");
require("../../web/task_monitor.js");

function fixture({ api = async () => ({ presets: [] }), taskMonitor, initial = {} } = {}) {
  const nodes = new Map();
  const elements = new Proxy({}, { get(_, key) {
    if (!nodes.has(key)) nodes.set(key, {
      value: "", textContent: "", innerHTML: "", disabled: false, files: [], open: false,
      listeners: {}, querySelectorAll: () => [],
      addEventListener(event, action) { this.listeners[event] = action; },
      showModal() { this.open = true; }, close() { this.open = false; this.listeners.close?.(); },
    });
    return nodes.get(key);
  } });
  const storage = new Map();
  const selected = { id: "shot", style_preset_mode: "inherit", composition_preset_mode: "inherit" };
  const state = { runId: "run", selected, shots: [selected], visualPresets: [], visualPresetDefaults: {}, ...initial };
  let persisted = 0;
  const controller = FicFrameVisualPresets.createController({ state, elements, api,
    taskMonitor: taskMonitor || { wait: async () => ({}) }, escapeHtml: String,
    setBusy: (button, busy) => { button.disabled = busy; },
    storage: { setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key), getItem: (key) => storage.get(key) },
    saveWorkspaceDraft() {}, persistStoryboard: async () => { persisted++; },
  });
  controller.bindEvents();
  return { controller, state, elements, storage, persisted: () => persisted };
}

test("analysis consumes task monitor result directly and requires explicit confirmation", async () => {
  const draft = { status: "analyzed", positive: "dry brush", negative: "glossy", structured: { linework: "ink" }, reference_paths: ["drafts/id/ref.png"] };
  const writes = [];
  const monitor = FicFrameTaskMonitor.createMonitor({ request: async () => ({ status: "succeeded", result: draft }) });
  const f = fixture({ taskMonitor: monitor, api: async (path, options) => {
    if (path.endsWith("analyze-task")) return { task_id: "task" };
    if (options?.method === "POST") writes.push(JSON.parse(options.body));
    return { presets: [] };
  } });
  f.elements.stylePresetImages.files = [new Blob(["reference"], { type: "image/png" })];
  await f.controller.analyze("style");
  assert.equal(f.elements.visualPresetPositive.value, "dry brush");
  assert.equal(f.elements.visualPresetNegative.value, "glossy");
  assert.deepEqual(JSON.parse(f.elements.visualPresetStructured.value), { linework: "ink" });
  assert.match(f.elements.visualPresetDraftImages.innerHTML, /reference\/drafts\/id\/ref.png/);
  assert.equal(writes.length, 0);
  f.elements.visualPresetName.value = "Ink";
  await f.elements.visualPresetForm.listeners.submit({ preventDefault() {} });
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0].reference_paths, draft.reference_paths);
  assert.equal(f.storage.size, 0);
});

test("invalid structured edits and manual no-VLM draft survive closing and resuming", async () => {
  const f = fixture();
  f.controller.openEditor(null, "composition", { status: "vlm_not_configured", reference_paths: ["drafts/id/ref.png"] });
  assert.match(f.elements.visualPresetDraftState.textContent, /未配置 VLM/);
  f.elements.visualPresetName.value = "Manual";
  f.elements.visualPresetPositive.value = "subject left";
  f.elements.visualPresetStructured.value = "{unfinished";
  f.elements.cancelVisualPresetBtn.listeners.click();
  assert.equal(f.elements.visualPresetDialog.open, false);
  await f.controller.resume();
  assert.equal(f.elements.visualPresetStructured.value, "{unfinished");
  assert.equal(f.elements.visualPresetPositive.value, "subject left");
});

test("run default updates are serialized and an early response does not overwrite a newer selection", async () => {
  let release;
  const requests = [];
  const f = fixture({ api: async (path, options) => {
    const body = JSON.parse(options.body);
    requests.push(body);
    if (requests.length === 1) await new Promise((resolve) => { release = resolve; });
    return { visual_presets: { style_id: body.style_id, composition_id: body.composition_id }, shots: [] };
  } });
  f.elements.runStylePreset.value = "style_first";
  f.elements.runStylePreset.listeners.change();
  await Promise.resolve(); await Promise.resolve();
  f.elements.runStylePreset.value = "style_second";
  f.elements.runStylePreset.listeners.change();
  release();
  await f.controller.flush();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].style_id, "style_second");
  assert.equal(f.state.visualPresetDefaults.style_id, "style_second");
});

test("deleted presets retain bound IDs and preset lists cannot alter workspace selection", async () => {
  const f = fixture({ initial: { visualPresetDefaults: { style_id: "style_deleted", style_snapshot: { name: "Saved", version: 1 } } } });
  f.state.selected.style_preset_mode = "preset";
  f.state.selected.style_preset_id = "style_deleted";
  f.controller.renderSelectors();
  assert.equal(f.elements.runStylePreset.value, "style_deleted");
  assert.equal(f.elements.shotStylePreset.value, "style_deleted");
  assert.match(f.elements.runStylePreset.innerHTML, /已删除/);
  await f.controller.refresh();
  assert.equal(f.state.selected.style_preset_id, "style_deleted");
  assert.equal(FicFrameVisualPresets.referenceUrl("../presets.json"), "");
});

test("shot selection is persisted independently of manually edited prompts", async () => {
  const requests = [];
  const f = fixture({ api: async (path, options) => {
    const body = JSON.parse(options.body);
    requests.push({ path, body });
    return { shot: { ...body.shot, style_preset_snapshot: { id: "style_1", version: 1 } } };
  } });
  f.state.selected.positive_prompt = "unsaved edit";
  f.elements.shotStylePreset.value = "style_1";
  f.elements.shotCompositionPreset.value = "none";
  f.elements.shotStylePreset.listeners.change();
  await f.controller.flush();
  assert.equal(requests[0].body.shot.style_preset_mode, "preset");
  assert.equal(requests[0].body.shot.composition_preset_mode, "none");
  assert.equal(f.state.selected.positive_prompt, "unsaved edit");
  assert.equal(f.state.selected.style_preset_snapshot.version, 1);
  assert.equal(f.persisted(), 0);
  await f.controller.prepareGeneration();
  assert.equal(f.persisted(), 1);
});

test("current-image snapshot is not replaced by a newer candidate's snapshot", () => {
  const f = fixture();
  const first = { style: { id: "style", name: "Ink", version: 1, positive: "ink" } };
  f.state.selected.image_url = "/one.png?v=1";
  f.state.selected.image_versions = [{ image_url: "/one.png", visual_preset_snapshot: first }, { image_url: "/two.png", visual_preset_snapshot: { style: { id: "style", version: 2 } } }];
  f.state.selected.last_generation_visual_snapshot = { style: { id: "style", version: 2 } };
  f.controller.renderSnapshot();
  assert.match(f.elements.visualPromptSnapshot.textContent, /Ink v1/);
  assert.doesNotMatch(f.elements.visualPromptSnapshot.textContent, /v2/);
});

test("ungenerated shots and empty old snapshots do not claim image constraints", () => {
  const f = fixture();
  f.state.selected.last_generation_visual_snapshot = {};
  f.controller.renderSnapshot();
  assert.match(f.elements.visualPromptSnapshot.textContent, /尚未生成/);
});

test("upload-only image mode does not need VLM and does not replace manual text", async () => {
  const paths = ["drafts/id/ref.png"];
  const writes = [];
  const f = fixture({ api: async (path, options) => {
    writes.push(path);
    if (path.endsWith("/upload")) return { reference_paths: paths };
    return { presets: [] };
  } });
  f.controller.openEditor(null, "style");
  f.elements.visualPresetPositive.value = "manual style";
  f.elements.visualPresetReferenceMode.value = "image";
  f.elements.visualPresetReferenceFiles.files = [new Blob(["reference"], { type: "image/png" })];
  await f.controller.editorReferences(false);
  assert.deepEqual(writes, ["/api/visual-presets/upload"]);
  assert.equal(f.elements.visualPresetPositive.value, "manual style");
  assert.equal(f.elements.visualPresetReferenceMode.value, "image");
  assert.match(f.elements.visualPresetDraftImages.innerHTML, /ref.png/);
});

test("preflight prevents generation without silently dropping unsupported image mode", async () => {
  const f = fixture({ api: async () => ({ reference_preflight: { ok: false, status: "unsupported", message: "多图不支持", total_count: 3 } }) });
  f.state.selected.style_reference_mode = "image";
  await assert.rejects(f.controller.prepareGeneration(["shot"]), /多图不支持/);
  assert.equal(f.state.selected.style_reference_mode, "image");
  assert.equal(f.elements.visualReferenceWarning.hidden, false);
  assert.equal(f.persisted(), 1);
});

test("live probe only runs after cost confirmation and uses maximum reference count", async () => {
  const requests = [];
  let consent = false;
  global.confirm = () => consent;
  const f = fixture({ taskMonitor: { wait: async () => ({ status: "supported", message: "accepted" }) }, api: async (path, options) => {
    if (path.includes("visual-preview")) return { reference_preflight: { total_count: 5, ok: false, message: "unverified" } };
    if (path.includes("capability")) return { provider: "openai", model: "test", status: "unknown", adapter_supported: true };
    requests.push(JSON.parse(options.body));
    return { task_id: "probe" };
  } });
  await f.controller.testReferences();
  assert.equal(requests.length, 0);
  consent = true;
  await f.controller.testReferences();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].reference_count, 5);
  assert.equal(requests[0].confirmed, true);
  delete global.confirm;
});

test("run and per-shot reference modes persist independently", async () => {
  const requests = [];
  const f = fixture({ api: async (path, options) => {
    const body = JSON.parse(options.body);
    requests.push(body);
    return { shot: body.shot, visual_presets: { style_reference_mode: body.style_reference_mode, composition_reference_mode: body.composition_reference_mode }, shots: [] };
  } });
  f.elements.runStyleReferenceMode.value = "image";
  f.elements.runStyleReferenceMode.listeners.change();
  await f.controller.flush();
  assert.equal(requests[0].style_reference_mode, "image");
  f.elements.shotStyleReferenceMode.value = "text";
  f.elements.shotCompositionReferenceMode.value = "image";
  f.elements.shotStyleReferenceMode.listeners.change();
  await f.controller.flush();
  assert.equal(requests[1].shot.style_reference_mode, "text");
  assert.equal(requests[1].shot.composition_reference_mode, "image");
});

test("concurrent test clicks create only one paid probe", async () => {
  const requests = [];
  global.confirm = () => true;
  const f = fixture({ taskMonitor: { wait: async () => ({ message: "accepted" }) }, api: async (path, options) => {
    if (path.includes("visual-preview")) return { reference_preflight: { total_count: 2, ok: true } };
    if (path.includes("capability")) return { provider: "openai", model: "test", adapter_supported: true };
    requests.push(path);
    return { task_id: "probe" };
  } });
  try {
    await Promise.all([f.controller.testReferences(), f.controller.testReferences()]);
    assert.deepEqual(requests, ["/api/image-reference-test-task"]);
  } finally { delete global.confirm; }
});

test("refresh resumes a saved probe without starting another paid task", async () => {
  const waited = [];
  const requests = [];
  const f = fixture({ taskMonitor: { wait: async (id) => { waited.push(id); return { message: "accepted" }; } }, api: async (path, options) => {
    requests.push(path);
    assert.ok(!path.endsWith("test-task"));
    if (path.includes("capability")) return { message: "accepted", status: "supported" };
    return { reference_preflight: { ok: true, message: "accepted" } };
  } });
  f.storage.set("ficframe.image-reference-test.v1", JSON.stringify({ task_id: "saved-probe" }));
  assert.equal(await f.controller.resumeProbe(), true);
  assert.deepEqual(waited, ["saved-probe"]);
  assert.equal(f.storage.has("ficframe.image-reference-test.v1"), false);
  assert.equal(f.elements.testImageReferencesBtn.disabled, false);
  assert.match(f.elements.health.textContent, /accepted/);
});

test("temporary probe monitoring failure retains the task ID for recovery", async () => {
  const f = fixture({ taskMonitor: { wait: async () => { throw new Error("offline"); } }, api: async () => ({ status: "running" }) });
  f.storage.set("ficframe.image-reference-test.v1", JSON.stringify({ task_id: "running-probe" }));
  await assert.rejects(f.controller.resumeProbe(), /offline/);
  assert.equal(f.storage.has("ficframe.image-reference-test.v1"), true);
  assert.equal(f.elements.testImageReferencesBtn.disabled, false);
  assert.match(f.elements.imageReferenceCapability.textContent, /恢复/);
});

test("older capability responses cannot replace the current size status", async () => {
  let release;
  let calls = 0;
  const f = fixture({ api: async () => {
    const number = ++calls;
    if (number === 1) await new Promise((resolve) => { release = resolve; });
    return { model: "test", message: number === 1 ? "old" : "current" };
  } });
  const first = f.controller.refreshCapability();
  await f.controller.refreshCapability();
  release();
  await first;
  assert.equal(f.elements.imageReferenceCapability.textContent, "test：current");
});
