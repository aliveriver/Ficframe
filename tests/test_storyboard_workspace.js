const assert = require("node:assert/strict");

global.window = global;
require("../web/storyboard_workspace.js");

const workspace = global.FicFrameStoryboardWorkspace;

async function main() {
  const calls = [];
  const client = workspace.createClient(async (path, options) => {
    calls.push({ path, body: JSON.parse(options.body) });
    return { ok: true };
  });

  await client.feedback("run-1", "请调整 shot_02");
  assert.deepEqual(calls[0], {
    path: "/api/storyboard/feedback",
    body: { run_id: "run-1", content: "请调整 shot_02" },
  });

  await client.promptFeedback("run-1", "保留构图，改成雨夜霓虹");
  assert.deepEqual(calls[1], {
    path: "/api/storyboard/prompt-feedback",
    body: { run_id: "run-1", content: "保留构图，改成雨夜霓虹" },
  });

  assert.equal(workspace.feedbackOutcomeText([]), "分镜 Agent 判断无需重新生成，已记录并回应这条反馈");
  assert.match(workspace.feedbackOutcomeText(["shot_02"]), /shot_02/);
  assert.deepEqual(workspace.splitEditorList("甲、乙，丙"), ["甲", "乙", "丙"]);
  assert.equal(workspace.normalizeNovelText("甲\r\n乙\r丙"), "甲\n乙\n丙");
  assert.equal(workspace.normalizeNovelText("甲\r\r\n\r\r\n乙"), "甲\n\n乙");

  const highlighted = workspace.highlightedContextMarkup("abcdef", 2, 4, (value) => value);
  assert.equal(highlighted, "ab<mark>cd</mark>ef");
  assert.equal(
    workspace.highlightedDocumentMarkup("甲\n乙\n丙", 2, 3, (value) => value),
    "甲\n<mark>乙</mark>\n丙",
  );

  const sourceSelection = workspace.resolveShotSourceSelection("前文\r\n完整原文\r\n后文", {
    source_text: "完整原文\n",
    source_excerpt: "原文",
    source_start: 4,
    source_end: 9,
  });
  assert.deepEqual(sourceSelection, { start: 3, end: 8, text: "完整原文\n" });
  assert.deepEqual(
    workspace.resolveShotSourceSelection("前文\n偶然相同描述\n后文", {
      generation_mode: "description",
      source_excerpt: "偶然相同描述",
    }),
    { start: 0, end: 0, text: "" },
  );

  const history = workspace.versionHistoryMarkup(
    [{ version_id: "v1", created_at: 1, reason: "修改前", shot: { title: "第一版" } }],
    "shot_01",
    (value) => String(value),
  );
  assert.match(history, /data-storyboard-version="v1"/);
  assert.match(history, /第一版/);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
