const assert = require("node:assert/strict");
const test = require("node:test");

global.window = global;
require("../../web/workspace_state.js");

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

test("workspace draft round-trips sets as selected shot ids", () => {
  const storage = memoryStorage();
  const state = FicFrameWorkspaceState.createInitialState();
  state.runId = "run-1";
  state.shots = [{ id: "shot-1" }];
  state.selected = state.shots[0];
  state.selectedShotIds.add("shot-1");

  assert.equal(FicFrameWorkspaceState.saveDraft(storage, "workspace", state), true);
  const draft = FicFrameWorkspaceState.loadDraft(storage, "workspace");

  assert.equal(draft.selectedShotId, "shot-1");
  assert.deepEqual(draft.selectedShotIds, ["shot-1"]);
});

test("workspace draft preserves visual preset defaults and per-shot choices", () => {
  const storage = memoryStorage();
  const state = FicFrameWorkspaceState.createInitialState();
  state.runId = "run-visual";
  state.visualPresetDefaults = { style_id: "style-1", composition_id: "composition-1" };
  state.shots = [{ id: "shot-1", style_preset_mode: "none", composition_preset_mode: "preset", composition_preset_id: "composition-2" }];

  FicFrameWorkspaceState.saveDraft(storage, "workspace", state);
  const draft = FicFrameWorkspaceState.loadDraft(storage, "workspace");

  assert.deepEqual(draft.visualPresetDefaults, state.visualPresetDefaults);
  assert.equal(draft.shots[0].style_preset_mode, "none");
  assert.equal(draft.shots[0].composition_preset_id, "composition-2");
});

test("empty workspace removes stale draft", () => {
  const storage = memoryStorage();
  storage.setItem("workspace", "stale");
  const state = FicFrameWorkspaceState.createInitialState();

  assert.equal(FicFrameWorkspaceState.saveDraft(storage, "workspace", state), false);
  assert.equal(storage.getItem("workspace"), null);
});

test("a style selection is saved and restored before importing input files", () => {
  const storage = memoryStorage();
  const state = FicFrameWorkspaceState.createInitialState();
  state.visualPresetDefaults = { style_id: "style-1", style_reference_mode: "image" };
  assert.equal(FicFrameWorkspaceState.saveDraft(storage, "workspace", state), true);
  assert.deepEqual(FicFrameWorkspaceState.loadDraft(storage, "workspace").visualPresetDefaults, state.visualPresetDefaults);

  state.visualPresetDefaults = { style_id: null, style_reference_mode: "text" };
  assert.equal(FicFrameWorkspaceState.saveDraft(storage, "workspace", state), false);
});

test("changing input files retains style choices and releases the previous run snapshot", () => {
  const state = FicFrameWorkspaceState.createInitialState();
  state.runId = "old-run";
  state.visualPresetDefaults = { style_id: "style-1", style_reference_mode: "image", style_snapshot: { id: "style-1", version: 1 } };
  FicFrameWorkspaceState.resetRun(state);
  assert.deepEqual(state.visualPresetDefaults, { style_id: "style-1", style_reference_mode: "image" });
  assert.equal(state.runId, null);
});

test("reset run preserves prepared characters and provider config", () => {
  const state = FicFrameWorkspaceState.createInitialState();
  state.runId = "run-1";
  state.characters = [{ name: "A" }];
  state.providerConfig = { active: { llm: "one" }, sources: [] };
  state.selectedShotIds.add("shot-1");

  FicFrameWorkspaceState.resetRun(state);

  assert.equal(state.runId, null);
  assert.deepEqual(state.characters, [{ name: "A" }]);
  assert.equal(state.selectedShotIds.size, 0);
  assert.equal(state.providerConfig.active.llm, "one");
});
