(function initNovelSource(global) {
  function createController({ state, elements, workspace, escapeHtml, loadNovel }) {
    async function open(mode = "browse") {
      if (!state.runId) return false;
      if (!state.novelText) await loadNovel();
      if (elements.dialog.open) elements.dialog.close();
      state.novelText = workspace.normalizeNovelText(state.novelText);
      state.novelDialogMode = mode;
      elements.dialog.dataset.mode = mode;
      elements.text.value = state.novelText;
      elements.description.value = "";
      const adding = mode === "add";
      elements.title.textContent = adding ? "选择新分镜对应的小说段落" : "小说原文定位";
      elements.description.closest("label").hidden = !adding;
      elements.generate.hidden = !adding;
      elements.clear.hidden = !adding;
      state.novelSelection = !adding && state.selected
        ? workspace.resolveShotSourceSelection(state.novelText, state.selected)
        : { start: 0, end: 0, text: "" };
      render();
      elements.dialog.showModal();
      setTimeout(focusSelection, 0);
      return true;
    }

    function focusSelection() {
      const start = state.novelSelection.start || 0;
      const end = state.novelSelection.end || 0;
      elements.text.focus();
      elements.text.setSelectionRange(start, end);
      const linesBefore = state.novelText.slice(0, start).split("\n").length;
      elements.text.scrollTop = Math.max(0, linesBefore * 28 - elements.text.clientHeight / 3);
    }

    function update() {
      const start = elements.text.selectionStart;
      const end = elements.text.selectionEnd;
      state.novelSelection = { start, end, text: state.novelText.slice(start, end) };
      render();
    }

    function render() {
      const { start, end, text } = state.novelSelection;
      if (!text) {
        const status = state.novelSelection.status;
        elements.status.textContent = state.novelDialogMode === "add"
          ? "拖动选择文字，选区会作为新分镜的生成依据。"
          : status === "description"
            ? "这条分镜由文本描述生成，没有小说原文引用。"
            : status === "unresolved"
              ? "原文引用已失效，当前小说中无法重新定位。"
              : "这条分镜没有可定位的小说原文。";
        elements.preview.innerHTML = state.novelText
          ? workspace.highlightedDocumentMarkup(state.novelText, 0, 0, escapeHtml) : "";
        elements.preview.scrollTop = 0;
        return;
      }
      const located = state.novelSelection.status === "relocated" ? "已重新定位" : "精确定位";
      elements.status.textContent = located + " · 已高亮 " + text.length + " 个字符 · 位置 " + (start + 1) + "–" + end;
      elements.preview.innerHTML = workspace.highlightedDocumentMarkup(state.novelText, start, end, escapeHtml);
      const mark = elements.preview.querySelector("mark");
      if (mark) elements.preview.scrollTop = Math.max(0, mark.offsetTop - elements.preview.clientHeight / 2);
    }

    function clear() {
      state.novelSelection = { start: 0, end: 0, text: "" };
      focusSelection();
      render();
    }

    function close() {
      state.novelDialogMode = "browse";
      elements.dialog.dataset.mode = "browse";
      elements.description.closest("label").hidden = true;
      elements.generate.hidden = true;
      elements.clear.hidden = true;
    }

    return { clear, close, open, render, update };
  }

  global.FicFrameNovelSource = { createController };
})(window);
