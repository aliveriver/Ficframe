(function initWorkspaceState(global) {
  const defaultHtmlSettings = {
    font_family: "sans",
    heading_font_family: "serif",
    font_size: 18,
    line_height: 1.9,
    content_width: 920,
    text_align: "left",
    paragraph_spacing: 1,
  };

  function createHtmlSettings(value = {}) {
    return { ...defaultHtmlSettings, ...(value && typeof value === "object" ? value : {}) };
  }

  function createInitialState() {
    return {
      runId: null, shots: [], scenes: [], autoCharacters: [], manualCharacters: [], characters: [],
      originalShots: [], originalCharacters: [], differenceAnalysis: null, selected: null,
      selectedShotIds: new Set(), selectedCharacterIndex: 0, providerConfig: { active: {}, sources: [] },
      selectedProviderId: null, referenceBindings: [], novelText: "", storyboardMessages: [],
      promptFeedbackMessages: [], storyboardVersions: {},
      htmlSettings: createHtmlSettings(),
      novelSelection: { start: null, end: null, text: "" }, novelDialogMode: "browse",
    };
  }

  function serializeDraft(state) {
    return {
      runId: state.runId, shots: state.shots, scenes: state.scenes,
      autoCharacters: state.autoCharacters, manualCharacters: state.manualCharacters, characters: state.characters,
      originalShots: state.originalShots, originalCharacters: state.originalCharacters,
      differenceAnalysis: state.differenceAnalysis, selectedShotId: state.selected?.id || null,
      selectedShotIds: Array.from(state.selectedShotIds), selectedCharacterIndex: state.selectedCharacterIndex,
      novelText: state.novelText, storyboardMessages: state.storyboardMessages,
      promptFeedbackMessages: state.promptFeedbackMessages, storyboardVersions: state.storyboardVersions,
      htmlSettings: state.htmlSettings,
      savedAt: Date.now(),
    };
  }

  function saveDraft(storage, key, state) {
    if (!state.runId && !state.shots.length && !state.characters.length && !state.manualCharacters.length) {
      storage.removeItem(key);
      return false;
    }
    storage.setItem(key, JSON.stringify(serializeDraft(state)));
    return true;
  }

  function loadDraft(storage, key) {
    const raw = storage.getItem(key);
    if (!raw) return null;
    try {
      const draft = JSON.parse(raw);
      return Array.isArray(draft.shots) || Array.isArray(draft.characters) ? draft : null;
    } catch (error) {
      return null;
    }
  }

  function resetRun(state) {
    Object.assign(state, {
      runId: null, shots: [], scenes: [], originalShots: [], selected: null,
      storyboardMessages: [], promptFeedbackMessages: [], storyboardVersions: {}, novelText: "",
      htmlSettings: createHtmlSettings(),
    });
    state.selectedShotIds.clear();
  }

  function resetAll(state) {
    Object.assign(state, createInitialState());
  }

  global.FicFrameWorkspaceState = { createHtmlSettings, createInitialState, loadDraft, resetAll, resetRun, saveDraft, serializeDraft };
})(window);
