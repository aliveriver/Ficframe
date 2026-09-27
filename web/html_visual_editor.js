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

  global.FicFrameHtmlVisualEditor = {
    applyDocumentSettings,
    applyFigureLayout,
    clamp,
    fontStack,
    positionFromPointer,
    resizeWidthPercent,
    widthPercent,
  };
})(window);
