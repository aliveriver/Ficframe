"use strict";

(function exposePromptState(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.FicFramePromptState = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createPromptState() {
  function updateShotPositivePrompt(shot, prompt) {
    if (!shot || typeof shot !== "object") {
      throw new TypeError("shot must be an object");
    }
    const nextPrompt = String(prompt ?? "");
    const changed = shot.positive_prompt !== nextPrompt;
    if (changed) {
      shot.character_layout = [];
      shot.regional_guidance = null;
    }
    shot.positive_prompt = nextPrompt;
    return changed;
  }

  return { updateShotPositivePrompt };
});
