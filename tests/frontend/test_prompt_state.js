"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { updateShotPositivePrompt } = require("../../web/prompt_state.js");

test("changing a prompt invalidates generated character layout", () => {
  const shot = {
    id: "shot-1",
    positive_prompt: "A on the left, B on the right",
    character_layout: [
      { character: "A", region: [0, 0, 0.5, 1] },
      { character: "B", region: [0.5, 0, 1, 1] },
    ],
    regional_guidance: true,
    negative_prompt: "duplicate character",
  };

  const changed = updateShotPositivePrompt(shot, "B on the left, A on the right");

  assert.equal(changed, true);
  assert.equal(shot.positive_prompt, "B on the left, A on the right");
  assert.deepEqual(shot.character_layout, []);
  assert.equal(shot.regional_guidance, null);
  assert.equal(shot.negative_prompt, "duplicate character");
  assert.equal(shot.id, "shot-1");
});

test("saving an unchanged prompt preserves its layout", () => {
  const layout = [{ character: "A", region: [0, 0, 1, 1] }];
  const shot = {
    positive_prompt: "A centered portrait",
    character_layout: layout,
    regional_guidance: true,
  };

  const changed = updateShotPositivePrompt(shot, "A centered portrait");

  assert.equal(changed, false);
  assert.equal(shot.character_layout, layout);
  assert.equal(shot.regional_guidance, true);
});

test("null prompt input is normalized before layout invalidation", () => {
  const shot = {
    positive_prompt: "old prompt",
    character_layout: [{ character: "A", region: [0, 0, 1, 1] }],
    regional_guidance: false,
  };

  updateShotPositivePrompt(shot, null);

  assert.equal(shot.positive_prompt, "");
  assert.deepEqual(shot.character_layout, []);
  assert.equal(shot.regional_guidance, null);
});
