const assert = require("node:assert/strict");
const test = require("node:test");

global.window = global;
require("../../web/image_workflow.js");

function makeElements() {
  return {
    imageBtn: { disabled: false, textContent: "生成图片", dataset: {} },
    selectedImagesBtn: { disabled: false, textContent: "生成选中", dataset: {} },
    allImagesBtn: { disabled: false, textContent: "生成全部", dataset: {} },
    retryFailedBtn: { disabled: false, textContent: "失败重试", dataset: {} },
    imageRetryCount: { value: "0" },
    skipExistingImages: { checked: false },
    promptBox: { value: "当前 Prompt" },
    preview: { innerHTML: "" },
    imageVersions: { innerHTML: "", querySelectorAll: () => [] },
    health: { textContent: "" },
    qaBox: { textContent: "" },
  };
}

function makeController(state, elements, result) {
  return FicFrameImageWorkflow.createController({
    state,
    elements,
    api: async () => ({ task_id: "task-1" }),
    taskMonitor: { wait: async () => result },
    escapeHtml: (value) => String(value),
    clone: (value) => JSON.parse(JSON.stringify(value)),
    setBusy: (button, busy) => { button.disabled = busy; },
    saveSelectedPrompt: () => {},
    saveCharacterEditor: () => {},
    saveWorkspaceDraft: () => {},
    renderShots: () => {},
    selectedImageSize: () => "1024x1024",
  });
}

test("图片任务结果会回填当前分镜及图片版本", async () => {
  const state = {
    runId: "run-1",
    selected: { id: "shot-1", positive_prompt: "旧 Prompt" },
    shots: [{ id: "shot-1", positive_prompt: "旧 Prompt" }],
    selectedShotIds: new Set(),
  };
  const elements = makeElements();
  const controller = makeController(state, elements, {
    shot_id: "shot-1",
    image_path: "images/shot-1.png",
    raw_image_url: "/runs/run-1/images/shot-1.png",
    image_url: "/runs/run-1/images/shot-1.png?v=1",
    activated: true,
    image_versions: [{ image_path: "images/shot-1.png", image_url: "/runs/run-1/images/shot-1.png", created_at: 1 }],
  });

  await controller.generateCurrent();

  assert.equal(state.shots[0].image_path, "images/shot-1.png");
  assert.equal(state.shots[0].image_url, "/runs/run-1/images/shot-1.png");
  assert.equal(state.shots[0].image_versions.length, 1);
  assert.match(elements.health.textContent, /图片已生成/);
});

test("没有选中分镜时版本区域会清空", () => {
  const elements = makeElements();
  const controller = makeController({ runId: null, selected: null, shots: [], selectedShotIds: new Set() }, elements, {});
  elements.imageVersions.innerHTML = "旧内容";

  controller.renderVersions();

  assert.equal(elements.imageVersions.innerHTML, "");
});
