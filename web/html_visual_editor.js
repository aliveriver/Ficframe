(function initHtmlVisualEditor(global) {
  const positions = ["before", "after", "left", "right", "inline"];
  const fontStacks = {
    sans: '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif',
    serif: '"Noto Serif CJK SC", SimSun, STSong, serif',
    system: "system-ui, sans-serif",
  };

  function fontStack(preset, customName = "") {
    const custom = String(customName || "").trim();
    const fallback = fontStacks[preset] || fontStacks.sans;
    if (!custom) return fallback;
    const escaped = custom.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
    return `"${escaped}", ${fallback}`;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, Number(value) || minimum));
  }

  function widthPercent(width, fallback = 100) {
    const match = String(width || "").trim().match(/^(\d+(?:\.\d+)?)%$/);
    return match ? clamp(match[1], 15, 100) : fallback;
  }

  function positionFromPointer(clientX, rect) {
    if (!rect || !rect.width) return "before";
    const ratio = (clientX - rect.left) / rect.width;
    if (ratio < 0.34) return "left";
    if (ratio > 0.66) return "right";
    return "before";
  }

  function resizeWidthPercent(startWidth, deltaX, containerWidth) {
    if (!Number.isFinite(containerWidth) || containerWidth <= 0) return 100;
    return Math.round(clamp((Number(startWidth) + Number(deltaX)) / containerWidth * 100, 15, 100));
  }

  function applyFigureLayout(figure, layout = {}) {
    if (!figure) return;
    const rawPosition = positions.includes(layout.position) ? layout.position : "before";
    const position = ["left", "right"].includes(rawPosition) ? "before" : rawPosition;
    const alignment = ["left", "center", "right"].includes(layout.alignment) ? layout.alignment : "center";
    const wrap = ["none", "left", "right"].includes(layout.wrap)
      ? layout.wrap
      : (["left", "right"].includes(rawPosition) ? rawPosition : "none");
    const previousPosition = figure.dataset.position;
    for (const name of positions) figure.classList.remove(`image-${name}`);
    for (const name of ["left", "center", "right"]) figure.classList.remove(`image-align-${name}`);
    for (const name of ["left", "right"]) figure.classList.remove(`image-wrap-${name}`);
    figure.classList.add(`image-${position}`);
    figure.classList.add(`image-align-${alignment}`);
    if (wrap !== "none") figure.classList.add(`image-wrap-${wrap}`);
    figure.dataset.position = position;
    figure.dataset.alignment = alignment;
    figure.dataset.wrap = wrap;
    figure.style.width = String(layout.width || "100%");
    const anchor = figure.ficframeTextAnchor;
    if (previousPosition !== position && anchor?.isConnected) {
      if (position === "after") anchor.after(figure);
      else anchor.before(figure);
    }
    let caption = figure.querySelector("figcaption");
    const captionText = String(layout.caption || "");
    if (!caption && captionText) {
      caption = figure.ownerDocument.createElement("figcaption");
      figure.append(caption);
    }
    if (caption) {
      caption.textContent = captionText;
      caption.hidden = !captionText;
    }
  }

  function applyDocumentSettings(documentRef, settings = {}) {
    if (!documentRef?.body) return;
    const body = documentRef.body;
    const main = documentRef.querySelector("main");
    const paragraphs = documentRef.querySelectorAll("p");
    const textBlocks = documentRef.querySelectorAll("p, ul, blockquote");
    const headings = documentRef.querySelectorAll("h1, h2, h3, h4, h5, h6");
    body.style.fontFamily = fontStack(settings.font_family, settings.body_font_name);
    body.style.fontSize = `${clamp(settings.font_size || 18, 14, 30)}px`;
    body.style.lineHeight = String(clamp(settings.line_height || 1.9, 1.3, 2.6));
    body.style.removeProperty("text-align");
    if (main) main.style.maxWidth = `${clamp(settings.content_width || 920, 560, 1400)}px`;
    for (const paragraph of paragraphs) {
      paragraph.style.marginBlock = `${clamp(settings.paragraph_spacing || 1, 0.4, 2.4)}em`;
    }
    for (const block of textBlocks) {
      block.style.textAlign = ["left", "justify", "center"].includes(settings.text_align)
        ? settings.text_align
        : "left";
    }
    for (const heading of headings) {
      heading.style.fontFamily = fontStack(settings.heading_font_family, settings.heading_font_name);
    }
  }

  async function downloadResponse(response, fallbackName) {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || response.statusText);
    }
    const disposition = response.headers.get("content-disposition") || "";
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="?([^";]+)"?/i);
    let filename = plain?.[1] || fallbackName;
    if (encoded) { try { filename = decodeURIComponent(encoded[1]); } catch (_) { /* Use the fallback name. */ } }
    filename = filename.split(/[\\/]/).pop()?.trim() || fallbackName;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url; link.download = filename;
    document.body.append(link);
    try { link.click(); }
    finally { link.remove(); global.setTimeout(() => URL.revokeObjectURL(url), 0); }
    return filename;
  }

  function createController({ state, elements: el, api, setBusy, persistStoryboard,
                              saveSelectedPrompt, saveShotEditor, saveCharacterEditor,
                              selectShot, scheduleWorkspaceDraftSave,
                              workspaceState = global.FicFrameWorkspaceState }) {
    let designerSelectedShotId = null;
    let previewSequence = 0;
    function loadHtmlLayoutEditor() {
      const layout = state.selected?.html_layout || {};
      el.htmlImagePosition.value = ["before", "after", "inline"].includes(layout.position) ? layout.position : "before";
      const presetWidths = new Set(["auto", "35%", "50%", "65%", "80%", "100%"]);
      el.htmlImageWidth.value = presetWidths.has(layout.width) ? layout.width : "custom";
      el.htmlImageCustomWidth.value = presetWidths.has(layout.width) ? "" : (layout.width || "");
      el.htmlImageCaption.value = layout.caption || "";
      el.htmlImageAlignment.value = layout.alignment || "center";
      el.htmlImageWrap.value = layout.wrap || (["left", "right"].includes(layout.position) ? layout.position : "none");
    }

    function saveHtmlLayoutEditor() {
      if (!state.selected) return;
      state.selected.html_layout = {
        ...(state.selected.html_layout || {}),
        position: el.htmlImagePosition.value || "before",
        width: el.htmlImageWidth.value === "custom"
          ? el.htmlImageCustomWidth.value.trim()
          : (el.htmlImageWidth.value || "100%"),
        caption: el.htmlImageCaption.value.trim(),
        alignment: el.htmlImageAlignment.value || "center",
        wrap: el.htmlImageWrap.value || "none",
      };
    }

    const settingsFields = [
      ["font_family", "FontFamily"], ["heading_font_family", "HeadingFontFamily"],
      ["body_font_name", "BodyFontName"], ["heading_font_name", "HeadingFontName"],
      ["font_size", "FontSize", Number, "px"], ["line_height", "LineHeight", Number],
      ["content_width", "ContentWidth", Number, "px"],
      ["paragraph_spacing", "ParagraphSpacing", Number, "em"], ["text_align", "TextAlign"],
    ];
    function writeSettings(prefix) {
      const settings = workspaceState.createHtmlSettings(state.htmlSettings);
      for (const [key, suffix, , unit = ""] of settingsFields) {
        el[`${prefix}${suffix}`].value = settings[key];
        const output = el[`${prefix}${suffix}Value`];
        if (output) output.value = `${settings[key]}${unit}`;
      }
    }
    function readSettings(prefix) {
      return workspaceState.createHtmlSettings(Object.fromEntries(settingsFields.map(([key, suffix, convert]) => {
        const value = el[`${prefix}${suffix}`].value;
        return [key, convert ? convert(value) : value.trim()];
      })));
    }
    function renderHtmlSettings() {
      state.htmlSettings = workspaceState.createHtmlSettings(state.htmlSettings);
      writeSettings("html");
    }
    function saveHtmlSettings() { state.htmlSettings = readSettings("html"); }

    function designerShot() {
      return state.shots.find((shot) => shot.id === designerSelectedShotId) || null;
    }

    function renderDesignerSettings() { writeSettings("htmlDesigner"); }
    function readDesignerSettings() {
      state.htmlSettings = readSettings("htmlDesigner");
      renderDesignerSettings();
      renderHtmlSettings();
      applyDocumentSettings(el.htmlDesignerFrame.contentDocument, state.htmlSettings);
      scheduleWorkspaceDraftSave();
    }

    function selectDesignerShot(shotId) {
      const shot = state.shots.find((item) => item.id === shotId);
      if (!shot) return;
      designerSelectedShotId = shot.id;
      const index = state.shots.indexOf(shot);
      if (state.selected !== shot) selectShot(index);
      const layout = shot.html_layout || {};
      const width = layout.width || "100%";
      el.htmlDesignerShotName.textContent = `${shot.id} · ${shot.title}`;
      el.htmlDesignerWidthInput.value = width;
      const percent = widthPercent(width, 50);
      el.htmlDesignerWidthRange.value = percent;
      el.htmlDesignerWidthValue.value = `${percent}%`;
      el.htmlDesignerCaption.value = layout.caption || "";
      el.htmlDesignerAlignment.value = layout.alignment || "center";
      el.htmlDesignerWrap.value = layout.wrap || (["left", "right"].includes(layout.position) ? layout.position : "none");
      const visualPosition = ["before", "after", "inline"].includes(layout.position) ? layout.position : "before";
      document.querySelectorAll("[data-html-position]").forEach((button) => {
        button.classList.toggle("active", button.dataset.htmlPosition === visualPosition);
      });
      const frameDocument = el.htmlDesignerFrame.contentDocument;
      frameDocument?.querySelectorAll("figure[data-shot-id]").forEach((figure) => {
        figure.classList.toggle("ficframe-editor-selected", figure.dataset.shotId === shot.id);
      });
      el.htmlDesignerStatus.textContent = `${shot.id} 已选中`;
    }

    function syncDesignerLayoutToMainEditor(shot) {
      if (state.selected !== shot) return;
      loadHtmlLayoutEditor();
    }

    function updateDesignerImageLayout(changes) {
      const shot = designerShot();
      if (!shot) return;
      shot.html_layout = {
        position: "before",
        alignment: "center",
        wrap: "none",
        width: "100%",
        caption: "",
        ...(shot.html_layout || {}),
        ...changes,
      };
      const figure = [...(el.htmlDesignerFrame.contentDocument?.querySelectorAll("figure[data-shot-id]") || [])]
        .find((item) => item.dataset.shotId === shot.id);
      applyFigureLayout(figure, shot.html_layout);
      syncDesignerLayoutToMainEditor(shot);
      selectDesignerShot(shot.id);
      scheduleWorkspaceDraftSave();
    }

    function installDesignerDocument() {
      const documentRef = el.htmlDesignerFrame.contentDocument;
      if (!documentRef) return;
      const figures = [...documentRef.querySelectorAll("figure[data-shot-id]")];
      el.htmlDesignerEmpty.hidden = figures.length > 0;
      let editorStyle = documentRef.querySelector("#ficframe-editor-style");
      if (!editorStyle) {
        editorStyle = documentRef.createElement("style");
        editorStyle.id = "ficframe-editor-style";
        editorStyle.textContent = `
          figure[data-shot-id] { cursor: grab; position: relative; transition: outline-color .15s ease, opacity .15s ease; }
          figure[data-shot-id] > img { touch-action: none; user-select: none; -webkit-user-drag: none; }
          figure[data-shot-id]:hover { outline: 2px solid #267b7c66; outline-offset: 5px; }
          figure.ficframe-editor-selected { outline: 3px solid #267b7c; outline-offset: 6px; }
          figure.ficframe-editor-dragging { cursor: grabbing; opacity: .72; }
          .ficframe-resize-handle { background: #267b7c; border: 3px solid #fff; border-radius: 50%; bottom: -13px; cursor: nwse-resize; display: none; height: 26px; position: absolute; right: -13px; touch-action: none; user-select: none; width: 26px; z-index: 10; }
          figure.ficframe-editor-selected > .ficframe-resize-handle { display: block; }
        `;
        documentRef.head.append(editorStyle);
      }
      applyDocumentSettings(documentRef, state.htmlSettings);
      figures.forEach((figure) => {
        const shot = state.shots.find((item) => item.id === figure.dataset.shotId);
        if (!shot) return;
        const initialPosition = figure.dataset.position;
        let anchor = initialPosition === "after" ? figure.previousElementSibling : figure.nextElementSibling;
        while (anchor?.matches?.("figure[data-shot-id]")) {
          anchor = initialPosition === "after" ? anchor.previousElementSibling : anchor.nextElementSibling;
        }
        figure.ficframeTextAnchor = anchor;
        applyFigureLayout(figure, shot.html_layout || {});
        figure.addEventListener("click", (event) => {
          event.preventDefault();
          selectDesignerShot(figure.dataset.shotId);
        });
        const image = figure.querySelector("img");
        if (image) {
          image.draggable = false;
          installDesignerMoveGesture(image, figure);
        }
        const handle = documentRef.createElement("span");
        handle.className = "ficframe-resize-handle";
        handle.setAttribute("role", "slider");
        handle.setAttribute("aria-label", "调整图片宽度");
        handle.tabIndex = 0;
        figure.append(handle);
        installDesignerResizeGesture(handle, figure);
      });
      const preferred = designerSelectedShotId && figures.some((figure) => figure.dataset.shotId === designerSelectedShotId)
        ? designerSelectedShotId
        : figures[0]?.dataset.shotId;
      if (preferred) selectDesignerShot(preferred);
    }

    function installDesignerMoveGesture(target, figure) {
      target.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        selectDesignerShot(figure.dataset.shotId);
        const startX = event.clientX;
        let moved = false;
        target.setPointerCapture(event.pointerId);
        const onMove = (moveEvent) => {
          const delta = moveEvent.clientX - startX;
          if (Math.abs(delta) < 6) return;
          moved = true;
          figure.classList.add("ficframe-editor-dragging");
          figure.style.transform = `translateX(${Math.max(-80, Math.min(80, delta))}px)`;
        };
        const onEnd = (endEvent) => {
          target.removeEventListener("pointermove", onMove);
          target.removeEventListener("pointerup", onEnd);
          target.removeEventListener("pointercancel", onEnd);
          figure.classList.remove("ficframe-editor-dragging");
          figure.style.transform = "";
          if (!moved) return;
          const main = figure.ownerDocument.querySelector("main");
          const pointerPosition = positionFromPointer(endEvent.clientX, main?.getBoundingClientRect());
          const alignment = pointerPosition === "before" ? "center" : pointerPosition;
          const currentWidth = designerShot()?.html_layout?.width || "100%";
          const changes = { alignment };
          if (alignment !== "center" && ["auto", "100%"].includes(currentWidth)) changes.width = "80%";
          updateDesignerImageLayout(changes);
        };
        target.addEventListener("pointermove", onMove);
        target.addEventListener("pointerup", onEnd);
        target.addEventListener("pointercancel", onEnd);
      });
    }

    function installDesignerResizeGesture(handle, figure) {
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectDesignerShot(figure.dataset.shotId);
        const main = figure.ownerDocument.querySelector("main");
        const mainWidth = main?.getBoundingClientRect().width || 1;
        const startX = event.clientX;
        const startWidth = figure.getBoundingClientRect().width;
        let nextWidth = designerShot()?.html_layout?.width || `${Math.round(startWidth / mainWidth * 100)}%`;
        handle.setPointerCapture(event.pointerId);
        const onMove = (moveEvent) => {
          moveEvent.preventDefault();
          const percentage = resizeWidthPercent(startWidth, moveEvent.clientX - startX, mainWidth);
          nextWidth = `${percentage}%`;
          figure.style.width = nextWidth;
          el.htmlDesignerWidthRange.value = percentage;
          el.htmlDesignerWidthValue.value = nextWidth;
          el.htmlDesignerWidthInput.value = nextWidth;
        };
        const onEnd = (endEvent) => {
          endEvent.preventDefault();
          handle.removeEventListener("pointermove", onMove);
          handle.removeEventListener("pointerup", onEnd);
          handle.removeEventListener("pointercancel", onEnd);
          if (handle.hasPointerCapture(endEvent.pointerId)) handle.releasePointerCapture(endEvent.pointerId);
          updateDesignerImageLayout({ width: nextWidth });
        };
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onEnd);
        handle.addEventListener("pointercancel", onEnd);
      });
    }

    async function refreshHtmlDesignerPreview({ persist = true } = {}) {
      const runId = state.runId;
      if (!runId) return;
      const sequence = ++previewSequence;
      setBusy(el.htmlDesignerRefreshBtn, true);
      try {
        if (persist) await persistStoryboard({ quiet: true });
        const data = await api(`/api/export/${encodeURIComponent(runId)}`);
        if (sequence !== previewSequence || state.runId !== runId) return;
        el.htmlDesignerFrame.onload = installDesignerDocument;
        el.htmlDesignerFrame.src = `${data.export_html_url || data.html_url}?preview=${Date.now()}`;
        el.htmlDesignerStatus.textContent = "预览已更新";
      } catch (error) {
        if (sequence === previewSequence && state.runId === runId) el.htmlDesignerStatus.textContent = `预览失败：${error.message}`;
      } finally { if (sequence === previewSequence) setBusy(el.htmlDesignerRefreshBtn, false); }
    }

    async function openHtmlDesigner() {
      if (!state.runId) {
        el.health.textContent = "请先生成或恢复一个分镜 run";
        return;
      }
      saveSelectedPrompt();
      saveShotEditor();
      saveHtmlSettings();
      designerSelectedShotId = state.selected?.id || state.shots.find((shot) => shot.image_url || shot.image_path)?.id || null;
      renderDesignerSettings();
      el.htmlDesignerDialog.showModal();
      await refreshHtmlDesignerPreview();
    }

    async function saveHtmlDesigner() {
      setBusy(el.htmlDesignerSaveBtn, true);
      try {
        readDesignerSettings();
        await persistStoryboard({ quiet: true });
        await refreshHtmlDesignerPreview({ persist: false });
        el.htmlDesignerStatus.textContent = "排版已保存";
        el.health.textContent = "HTML 可视化排版已保存到当前 run";
      } finally {
        setBusy(el.htmlDesignerSaveBtn, false);
      }
    }


    const exportFormats = {
      md: { button: el.exportBtn, label: "配图小说 MD", error: "导出失败", path: "markdown" },
      html: { button: el.exportHtmlBtn, label: "配图小说 HTML", error: "HTML 导出失败", path: "html" },
      zip: { button: el.exportZipBtn, label: "ZIP 成品包", error: "ZIP 导出失败" },
    };
    async function exportDocument(format) {
      const runId = state.runId;
      if (!runId) return;
      const spec = exportFormats[format];
      saveSelectedPrompt(); saveShotEditor(); saveCharacterEditor(); saveHtmlSettings();
      setBusy(spec.button, true);
      try {
        await persistStoryboard({ quiet: true });
        const endpoint = `/api/export/${encodeURIComponent(runId)}`;
        const data = format === "zip" ? null : await api(endpoint);
        const url = data ? data[`export_${spec.path}_url`] || data[`${spec.path}_url`] : `${endpoint}.zip`;
        await downloadResponse(await fetch(url), `illustrated_novel-${runId}.${format}`);
        el.health.textContent = `${spec.label}已导出`;
        el.qaBox.textContent = data
          ? `已生成目录：${data.export_dir}\n图片目录：${data.images_dir}\n图片使用相对 images/ 路径；建议移动整个 export/ 目录。`
          : "ZIP 包包含 Markdown、HTML、images/、manifest.json 和字体/主题说明。";
      } catch (error) { el.health.textContent = `${spec.error}：${error.message}`; }
      finally { setBusy(spec.button, false); }
    }
    const exportMarkdown = () => exportDocument("md");
    const exportHtml = () => exportDocument("html");
    const exportZip = () => exportDocument("zip");

    function bindEvents() {
      const layoutFields = [el.htmlImagePosition, el.htmlImageWidth, el.htmlImageCustomWidth,
                            el.htmlImageCaption, el.htmlImageAlignment, el.htmlImageWrap];
      for (const [nodes, save] of [[layoutFields, saveHtmlLayoutEditor],
                                  [settingsFields.map(([, suffix]) => el[`html${suffix}`]), saveHtmlSettings]]) {
        const update = () => { save(); scheduleWorkspaceDraftSave(); };
        for (const node of nodes) for (const event of ["input", "change"]) node.addEventListener(event, update);
      }

      el.exportBtn.addEventListener("click", exportMarkdown);
      el.openHtmlDesignerBtn.addEventListener("click", () => openHtmlDesigner().catch((error) => {
        el.health.textContent = `打开排版工作台失败：${error.message}`;
      }));
      el.exportHtmlBtn.addEventListener("click", exportHtml);
      el.exportZipBtn.addEventListener("click", exportZip);
      el.htmlDesignerRefreshBtn.addEventListener("click", () => refreshHtmlDesignerPreview());
      el.htmlDesignerSaveBtn.addEventListener("click", () => saveHtmlDesigner().catch((error) => {
        el.htmlDesignerStatus.textContent = `保存失败：${error.message}`;
      }));
      el.htmlDesignerExportBtn.addEventListener("click", () => exportHtml());
      el.htmlDesignerCloseBtn.addEventListener("click", () => el.htmlDesignerDialog.close());
      document.querySelectorAll("[data-preview-width]").forEach((button) => {
        button.addEventListener("click", () => {
          el.htmlDesignerFrame.style.width = button.dataset.previewWidth;
          document.querySelectorAll("[data-preview-width]").forEach((item) => item.classList.toggle("active", item === button));
        });
      });
      document.querySelectorAll("[data-html-position]").forEach((button) => {
        button.addEventListener("click", () => updateDesignerImageLayout({ position: button.dataset.htmlPosition }));
      });
      el.htmlDesignerAlignment.addEventListener("change", () => {
        const alignment = el.htmlDesignerAlignment.value;
        const currentWidth = designerShot()?.html_layout?.width || "100%";
        const changes = { alignment };
        if (alignment !== "center" && ["auto", "100%"].includes(currentWidth)) changes.width = "80%";
        updateDesignerImageLayout(changes);
      });
      el.htmlDesignerWrap.addEventListener("change", () => {
        const wrap = el.htmlDesignerWrap.value;
        const currentWidth = designerShot()?.html_layout?.width || "100%";
        const changes = { wrap };
        if (wrap !== "none" && ["auto", "100%"].includes(currentWidth)) changes.width = "50%";
        updateDesignerImageLayout(changes);
      });
      el.htmlDesignerWidthRange.addEventListener("input", () => {
        const width = `${el.htmlDesignerWidthRange.value}%`;
        el.htmlDesignerWidthValue.value = width;
        el.htmlDesignerWidthInput.value = width;
        updateDesignerImageLayout({ width });
      });
      el.htmlDesignerWidthInput.addEventListener("change", () => {
        const width = el.htmlDesignerWidthInput.value.trim();
        if (!/^\d{1,4}(?:\.\d+)?(?:%|px|rem|em|vw)$/.test(width) && width !== "auto") {
          el.htmlDesignerStatus.textContent = "宽度格式应为 72%、420px、30rem、30em、40vw 或 auto";
          return;
        }
        updateDesignerImageLayout({ width });
      });
      el.htmlDesignerCaption.addEventListener("input", () => {
        const shot = designerShot();
        if (!shot) return;
        shot.html_layout = { position: "before", alignment: "center", wrap: "none", width: "100%", ...(shot.html_layout || {}), caption: el.htmlDesignerCaption.value };
        const figure = [...(el.htmlDesignerFrame.contentDocument?.querySelectorAll("figure[data-shot-id]") || [])]
          .find((item) => item.dataset.shotId === shot.id);
        applyFigureLayout(figure, shot.html_layout);
        syncDesignerLayoutToMainEditor(shot);
        scheduleWorkspaceDraftSave();
      });
      for (const [, suffix] of settingsFields) {
        const node = el[`htmlDesigner${suffix}`];
        for (const event of ["input", "change"]) node.addEventListener(event, readDesignerSettings);
      }
    }
    return { renderHtmlSettings, saveHtmlSettings, loadHtmlLayoutEditor, saveHtmlLayoutEditor,
             refreshHtmlDesignerPreview, openHtmlDesigner, exportMarkdown, exportHtml, exportZip, bindEvents };
  }

  global.FicFrameHtmlVisualEditor = {
    createController,
    downloadResponse,
    applyDocumentSettings,
    applyFigureLayout,
    clamp,
    fontStack,
    positionFromPointer,
    resizeWidthPercent,
    widthPercent,
  };
})(window);
