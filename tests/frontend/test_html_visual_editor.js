const assert = require("node:assert/strict");
const test = require("node:test");

global.window = global;
require("../../web/html_visual_editor.js");
require("../../web/workspace_state.js");

const editor = global.FicFrameHtmlVisualEditor;

test("vertical drops choose text block boundaries even when only Y changes", () => {
  const blocks = [100, 240, 380].map((top, i) => ({ dataset: { layoutBlock: `block-${i}` },
    getBoundingClientRect: () => ({ top, bottom: top + 100, height: 100 }) }));
  assert.equal(editor.dropTargetFromPointer(blocks, 101).block, blocks[0]);
  assert.equal(editor.dropTargetFromPointer(blocks, 250).block, blocks[1]);
  assert.equal(editor.dropTargetFromPointer(blocks, 250).position, "before");
  assert.equal(editor.dropTargetFromPointer(blocks, 460).block, blocks[2]);
  assert.equal(editor.dropTargetFromPointer(blocks, 460).position, "after");
  assert.equal(editor.dropTargetFromPointer([], 100), null);
});

test("left and right drops enable wrapping while center drops keep a single line", () => {
  const rect = { left: 100, width: 600 };
  const target = { block: { dataset: { layoutBlock: "paragraph" } }, position: "before" };
  assert.deepEqual(editor.layoutFromDrop(130, rect, target, { width: "100%" }), {
    anchor_block: "paragraph", position: "before", alignment: "left", wrap: "left", width: "50%",
  });
  assert.deepEqual(editor.layoutFromDrop(670, rect, target, { width: "35%" }, 210), {
    anchor_block: "paragraph", position: "before", alignment: "right", wrap: "right",
  });
  assert.equal(editor.layoutFromDrop(400, rect, target).wrap, "none");
  assert.equal(editor.layoutFromDrop(130, rect, null), null);
});

test("float drops shrink an oversized custom image to leave text room", () => {
  const target = { block: { dataset: { layoutBlock: "p" } }, position: "after" };
  const result = editor.layoutFromDrop(110, { left: 100, width: 600 }, target, { width: "1200px" }, 600);
  assert.equal(result.width, "50%");
  assert.equal(result.position, "after");
});

test("an already placed image is not reinserted and reordered when controls refresh", () => {
  const calls = [];
  const original = { isConnected: true, before: () => calls.push("source-before"), after: () => calls.push("source-after") };
  const target = { isConnected: true, dataset: { layoutBlock: "target" }, before: () => calls.push("target-before"), after: () => calls.push("target-after") };
  const figure = { dataset: {}, style: {}, classList: { add() {}, remove() {} },
    querySelector: () => null, ownerDocument: { querySelectorAll: () => [target] },
    ficframeTextAnchor: original, ficframeAppliedAnchor: target, ficframeAppliedPosition: "after" };
  editor.applyFigureLayout(figure, { anchor_block: "target", position: "after", width: "42%", wrap: "left" });
  assert.deepEqual(calls, []);
  assert.equal(figure.style.width, "42%");
  editor.applyFigureLayout(figure, { anchor_block: "target", position: "before" });
  assert.deepEqual(calls, ["target-before"]);
  editor.applyFigureLayout(figure, { anchor_block: null, position: "before" });
  assert.deepEqual(calls, ["target-before", "source-before"]);
});

test("visual editor derives responsive placement from horizontal drag", () => {
  const rect = { left: 100, width: 600 };
  assert.equal(editor.positionFromPointer(150, rect), "left");
  assert.equal(editor.positionFromPointer(400, rect), "before");
  assert.equal(editor.positionFromPointer(680, rect), "right");
});

test("visual editor normalizes percentage widths", () => {
  assert.equal(editor.widthPercent("42%"), 42);
  assert.equal(editor.widthPercent("4%"), 15);
  assert.equal(editor.widthPercent("140%"), 100);
  assert.equal(editor.widthPercent("420px", 55), 55);
});

test("visual editor resizes continuously from pointer delta", () => {
  assert.equal(editor.resizeWidthPercent(400, 100, 1000), 50);
  assert.equal(editor.resizeWidthPercent(400, -350, 1000), 15);
  assert.equal(editor.resizeWidthPercent(900, 400, 1000), 100);
});

test("visual editor builds a custom font stack with fallback", () => {
  assert.match(editor.fontStack("serif", "霞鹜文楷"), /^"霞鹜文楷",/);
  assert.match(editor.fontStack("sans", ""), /Microsoft YaHei/);
});

function controllerFixture(t, api = async () => ({ export_html_url: "/export/novel.html", export_markdown_url: "/export/novel.md", export_dir: "/export", images_dir: "/export/images" })) {
  const previousDocument = global.document;
  const downloads = [];
  global.document = { querySelectorAll: () => [], body: { append() {} },
    createElement: () => ({ click() { downloads.push({ filename: this.download, href: this.href }); }, remove() {} }),
  };
  t.after(() => { global.document = previousDocument; });
  const nodes = new Map();
  const elements = new Proxy({}, { get(_, key) {
    if (!nodes.has(key)) nodes.set(key, { value: "", textContent: "", listeners: {}, contentDocument: null,
      addEventListener(event, action) { this.listeners[event] = action; }, showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(key);
  } });
  const state = FicFrameWorkspaceState.createInitialState();
  state.runId = "run";
  let saves = 0;
  const controller = editor.createController({ state, elements, api, setBusy: (node, busy) => { node.disabled = busy; },
    persistStoryboard: async () => { saves++; }, saveSelectedPrompt() {}, saveShotEditor() {}, saveCharacterEditor() {},
    selectShot() {}, scheduleWorkspaceDraftSave() {},
  });
  controller.renderHtmlSettings();
  return { controller, elements, state, downloads, saves: () => saves };
}

test("main settings and the visual designer share text formatting state", async (t) => {
  const f = controllerFixture(t);
  f.controller.bindEvents();
  f.elements.htmlFontSize.value = "22";
  f.elements.htmlBodyFontName.value = " Custom Font ";
  f.controller.saveHtmlSettings();
  await f.controller.openHtmlDesigner();
  assert.equal(f.elements.htmlDesignerFontSize.value, 22);
  assert.equal(f.elements.htmlDesignerBodyFontName.value, "Custom Font");
  f.elements.htmlDesignerFontSize.value = "24";
  f.elements.htmlDesignerFontSize.listeners.input();
  assert.equal(f.state.htmlSettings.font_size, 24);
  assert.equal(f.elements.htmlFontSize.value, 24);
  assert.equal(f.elements.htmlDesignerFontSizeValue.value, "24px");
});

test("an older preview cannot replace the current run preview", async (t) => {
  let release;
  const f = controllerFixture(t, async (path) => path.includes("old")
    ? new Promise((resolve) => { release = resolve; }) : { export_html_url: "/new.html" });
  f.state.runId = "old";
  const first = f.controller.refreshHtmlDesignerPreview({ persist: false });
  f.state.runId = "new";
  await f.controller.refreshHtmlDesignerPreview({ persist: false });
  release({ export_html_url: "/old.html" });
  await first;
  assert.match(f.elements.htmlDesignerFrame.src, /^\/new.html\?/);
  assert.equal(f.elements.htmlDesignerRefreshBtn.disabled, false);
});

test("failed Markdown exports show the server error without downloading it as a novel", async (t) => {
  const originalFetch = global.fetch;
  t.after(() => { global.fetch = originalFetch; });
  global.fetch = async () => new Response(JSON.stringify({ detail: "missing novel" }), { status: 404 });
  const f = controllerFixture(t);
  await f.controller.exportMarkdown();
  assert.match(f.elements.health.textContent, /missing novel/);
  assert.equal(f.downloads.length, 0);
  assert.equal(f.elements.exportBtn.disabled, false);
});

test("all export formats persist edits and use the shared checked download", async (t) => {
  const originalFetch = global.fetch;
  t.after(() => { global.fetch = originalFetch; });
  const urls = [];
  global.fetch = async (url) => { urls.push(url); return new Response("exported document"); };
  const f = controllerFixture(t);
  f.elements.htmlFontSize.value = "23";
  await f.controller.exportMarkdown();
  await f.controller.exportHtml();
  await f.controller.exportZip();
  assert.equal(f.state.htmlSettings.font_size, 23);
  assert.equal(f.saves(), 3);
  assert.deepEqual(urls, ["/export/novel.md", "/export/novel.html", "/api/export/run.zip"]);
  assert.deepEqual(f.downloads.map((item) => item.filename), ["illustrated_novel-run.md", "illustrated_novel-run.html", "illustrated_novel-run.zip"]);
});

test("downloads support UTF-8 attachment filenames", async (t) => {
  const f = controllerFixture(t);
  const filename = await editor.downloadResponse(new Response("zip", {
    headers: { "content-disposition": "attachment; filename*=UTF-8''%E5%B0%8F%E8%AF%B4.zip" },
  }), "fallback.zip");
  assert.equal(filename, "小说.zip");
  assert.equal(f.downloads[0].filename, "小说.zip");
});
