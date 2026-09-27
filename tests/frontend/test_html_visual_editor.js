const assert = require("node:assert/strict");
const test = require("node:test");

global.window = global;
require("../../web/html_visual_editor.js");

const editor = global.FicFrameHtmlVisualEditor;

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
