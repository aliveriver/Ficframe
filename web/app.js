const state = {
  runId: null,
  shots: [],
  characters: [],
  selected: null,
  config: {},
  referenceBindings: [],
};

const el = {
  health: document.querySelector("#health"),
  runBtn: document.querySelector("#runBtn"),
  configToggle: document.querySelector("#configToggle"),
  configPanel: document.querySelector("#configPanel"),
  novelFile: document.querySelector("#novelFile"),
  charactersFile: document.querySelector("#charactersFile"),
  referenceImages: document.querySelector("#referenceImages"),
  referenceTable: document.querySelector("#referenceTable"),
  previewCharactersBtn: document.querySelector("#previewCharactersBtn"),
  maxShots: document.querySelector("#maxShots"),
  useLlm: document.querySelector("#useLlm"),
  imageSize: document.querySelector("#imageSize"),
  charactersBox: document.querySelector("#charactersBox"),
  shotList: document.querySelector("#shotList"),
  runId: document.querySelector("#runId"),
  promptBox: document.querySelector("#promptBox"),
  copyBtn: document.querySelector("#copyBtn"),
  imageBtn: document.querySelector("#imageBtn"),
  allImagesBtn: document.querySelector("#allImagesBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  qaImage: document.querySelector("#qaImage"),
  preview: document.querySelector("#preview"),
  qaBox: document.querySelector("#qaBox"),
  llmKey: document.querySelector("#llmKey"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmModel: document.querySelector("#llmModel"),
  imageKey: document.querySelector("#imageKey"),
  imageBaseUrl: document.querySelector("#imageBaseUrl"),
  imageProvider: document.querySelector("#imageProvider"),
  imageModel: document.querySelector("#imageModel"),
  imageSteps: document.querySelector("#imageSteps"),
  imageGuidance: document.querySelector("#imageGuidance"),
  imageBatch: document.querySelector("#imageBatch"),
  vlmKey: document.querySelector("#vlmKey"),
  vlmBaseUrl: document.querySelector("#vlmBaseUrl"),
  vlmModel: document.querySelector("#vlmModel"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.dataset.originalText ||= button.textContent;
  button.textContent = busy ? "处理中" : button.dataset.originalText;
}

function renderCharacters() {
  if (!state.characters.length) {
    el.charactersBox.textContent = "";
    return;
  }
  el.charactersBox.textContent = state.characters
    .map((character) => {
      const refs = character.reference_images?.length ? `\n参考图：${character.reference_images.length} 张` : "\n参考图：无";
      return `${character.name}\n${character.role}${refs}\n${(character.fixed_traits || []).join(" / ")}`;
    })
    .join("\n\n");
}

function selectShot(index) {
  state.selected = state.shots[index];
  el.promptBox.value = state.selected?.positive_prompt || "";
  el.qaBox.textContent = (state.selected?.qa_notes || []).join("\n");
  if (state.selected?.image_url) {
    el.preview.innerHTML = `<img alt="${state.selected.id}" src="${state.selected.image_url}" />`;
  } else {
    el.preview.innerHTML = "";
  }
  document.querySelectorAll(".shot").forEach((node, nodeIndex) => {
    node.classList.toggle("active", nodeIndex === index);
  });
}

function renderShots(preferredId = null) {
  el.shotList.innerHTML = "";
  state.shots.forEach((shot, index) => {
    const button = document.createElement("button");
    button.className = "shot";
    button.type = "button";
    button.innerHTML = `
      <strong>${shot.id} · ${shot.title}</strong>
      <small>${shot.characters.join("、") || "无明确角色"} · ${shot.location} · ${shot.time}</small>
      <small>${shot.image_url ? "已生成图片" : "未生成图片"}</small>
      <small>${shot.visual_goal}</small>
    `;
    button.addEventListener("click", () => selectShot(index));
    el.shotList.append(button);
  });
  if (state.shots.length) {
    const index = Math.max(0, state.shots.findIndex((shot) => shot.id === preferredId));
    selectShot(index);
  }
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    const keys = data.keys || {};
    const provider = data.providers?.image || "openai";
    el.health.textContent = `LLM ${keys.llm ? "已配置" : "未配置"} · 图片 ${keys.image ? "已配置" : "未配置"} (${provider}) · VLM ${keys.vlm ? "已配置" : "未配置"}`;
  } catch (error) {
    el.health.textContent = error.message;
  }
}

async function loadConfig() {
  const data = await api("/api/config");
  state.config = data.values || {};
  el.llmKey.value = state.config.FICFRAME_LLM_API_KEY || "";
  el.llmBaseUrl.value = state.config.FICFRAME_LLM_BASE_URL || "";
  el.llmModel.value = state.config.FICFRAME_LLM_MODEL || "";
  el.imageKey.value = state.config.FICFRAME_IMAGE_API_KEY || "";
  el.imageBaseUrl.value = state.config.FICFRAME_IMAGE_BASE_URL || "";
  el.imageProvider.value = state.config.FICFRAME_IMAGE_PROVIDER || "openai";
  el.imageModel.value = state.config.FICFRAME_IMAGE_MODEL || "";
  el.imageSteps.value = state.config.FICFRAME_IMAGE_STEPS || "";
  el.imageGuidance.value = state.config.FICFRAME_IMAGE_GUIDANCE_SCALE || "";
  el.imageBatch.value = state.config.FICFRAME_IMAGE_BATCH_SIZE || "";
  el.vlmKey.value = state.config.FICFRAME_VLM_API_KEY || "";
  el.vlmBaseUrl.value = state.config.FICFRAME_VLM_BASE_URL || "";
  el.vlmModel.value = state.config.FICFRAME_VLM_MODEL || "";
}

async function saveConfig() {
  const values = {
    FICFRAME_LLM_API_KEY: el.llmKey.value,
    FICFRAME_LLM_BASE_URL: el.llmBaseUrl.value,
    FICFRAME_LLM_MODEL: el.llmModel.value,
    FICFRAME_IMAGE_API_KEY: el.imageKey.value,
    FICFRAME_IMAGE_BASE_URL: el.imageBaseUrl.value,
    FICFRAME_IMAGE_PROVIDER: el.imageProvider.value,
    FICFRAME_IMAGE_MODEL: el.imageModel.value,
    FICFRAME_IMAGE_STEPS: el.imageSteps.value,
    FICFRAME_IMAGE_GUIDANCE_SCALE: el.imageGuidance.value,
    FICFRAME_IMAGE_BATCH_SIZE: el.imageBatch.value,
    FICFRAME_VLM_API_KEY: el.vlmKey.value,
    FICFRAME_VLM_BASE_URL: el.vlmBaseUrl.value,
    FICFRAME_VLM_MODEL: el.vlmModel.value,
  };
  await api("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  await checkHealth();
  el.health.textContent = "API 配置已保存";
}

async function previewCharacters() {
  if (!el.charactersFile.files[0]) {
    el.health.textContent = "请先选择人物 Markdown";
    return;
  }
  const text = await el.charactersFile.files[0].text();
  const data = await api("/api/characters/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  state.characters = data.characters || [];
  renderCharacters();
  rebuildReferenceBindings();
  el.health.textContent = `识别到 ${state.characters.length} 个角色`;
}

function rebuildReferenceBindings() {
  const previous = new Map(state.referenceBindings.map((item) => [item.filename, item]));
  state.referenceBindings = Array.from(el.referenceImages.files).map((file) => {
    const old = previous.get(file.name);
    return old || {
      filename: file.name,
      character: suggestCharacter(file.name),
      type: suggestReferenceType(file.name),
      note: "",
      enabled: true,
      previewUrl: URL.createObjectURL(file),
    };
  });
  renderReferenceTable();
}

function suggestCharacter(filename) {
  const stem = filename.toLowerCase();
  for (const character of state.characters) {
    const names = [character.name, ...(character.aliases || [])].filter(Boolean);
    if (names.some((name) => stem.includes(name.toLowerCase()))) return character.name;
  }
  return state.characters.length === 1 ? state.characters[0].name : "";
}

function suggestReferenceType(filename) {
  const stem = filename.toLowerCase();
  if (stem.includes("正面") || stem.includes("front")) return "正面";
  if (stem.includes("半身") || stem.includes("bust")) return "半身";
  if (stem.includes("全身") || stem.includes("full")) return "全身";
  if (stem.includes("表情") || stem.includes("face")) return "表情";
  if (stem.includes("服装") || stem.includes("outfit")) return "服装";
  return "参考";
}

function renderReferenceTable() {
  if (!state.referenceBindings.length) {
    el.referenceTable.innerHTML = `<p class="muted">尚未选择参考图</p>`;
    return;
  }
  const options = [`<option value="">未绑定</option>`]
    .concat(state.characters.map((character) => `<option value="${escapeHtml(character.name)}">${escapeHtml(character.name)}</option>`))
    .join("");
  el.referenceTable.innerHTML = state.referenceBindings
    .map((binding, index) => `
      <div class="reference-row" data-index="${index}">
        <img src="${binding.previewUrl}" alt="${escapeHtml(binding.filename)}" />
        <div class="reference-name">${escapeHtml(binding.filename)}</div>
        <select data-field="character">${options}</select>
        <input data-field="type" value="${escapeHtml(binding.type)}" placeholder="类型" />
        <input data-field="note" value="${escapeHtml(binding.note)}" placeholder="备注" />
        <label class="mini-toggle">
          <input data-field="enabled" type="checkbox" ${binding.enabled ? "checked" : ""} />
          <span>启用</span>
        </label>
      </div>
    `)
    .join("");
  el.referenceTable.querySelectorAll(".reference-row").forEach((row) => {
    const index = Number(row.dataset.index);
    row.querySelector('[data-field="character"]').value = state.referenceBindings[index].character;
    row.addEventListener("input", () => updateReferenceBinding(row));
    row.addEventListener("change", () => updateReferenceBinding(row));
  });
}

function updateReferenceBinding(row) {
  const index = Number(row.dataset.index);
  const binding = state.referenceBindings[index];
  binding.character = row.querySelector('[data-field="character"]').value;
  binding.type = row.querySelector('[data-field="type"]').value;
  binding.note = row.querySelector('[data-field="note"]').value;
  binding.enabled = row.querySelector('[data-field="enabled"]').checked;
}

function serializeReferenceBindings() {
  return state.referenceBindings.map(({ filename, character, type, note, enabled }) => ({
    filename,
    character,
    type,
    note,
    enabled,
  }));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

async function runPipeline() {
  if (!el.novelFile.files[0] || !el.charactersFile.files[0]) {
    el.health.textContent = "请选择小说和人物文件";
    return;
  }
  setBusy(el.runBtn, true);
  try {
    const form = new FormData();
    form.append("novel", el.novelFile.files[0]);
    form.append("characters", el.charactersFile.files[0]);
    for (const file of el.referenceImages.files) {
      form.append("reference_images", file);
    }
    form.append("reference_bindings", JSON.stringify(serializeReferenceBindings()));
    form.append("max_shots", el.maxShots.value);
    form.append("use_llm", el.useLlm.checked ? "true" : "false");
    const data = await api("/api/pipeline", { method: "POST", body: form });
    state.runId = data.run_id;
    state.shots = data.shots;
    state.characters = data.characters;
    el.runId.textContent = `run ${state.runId}`;
    renderCharacters();
    renderShots(state.selected?.id);
    el.health.textContent = `已生成 ${state.shots.length} 张分镜`;
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.runBtn, false);
  }
}

async function generateImage() {
  if (!state.selected || !state.runId) return;
  setBusy(el.imageBtn, true);
  try {
    const data = await api("/api/images", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.runId,
        size: el.imageSize.value,
        shot: { ...state.selected, positive_prompt: el.promptBox.value },
      }),
    });
    state.selected.image_url = data.image_url;
    state.selected.image_path = data.image_path;
    el.preview.innerHTML = `<img alt="${state.selected.id}" src="${data.image_url}" />`;
    renderShots(state.selected?.id);
    el.health.textContent = "图片已生成";
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.imageBtn, false);
  }
}

async function generateAllImages() {
  if (!state.shots.length || !state.runId) return;
  setBusy(el.allImagesBtn, true);
  try {
    const data = await api("/api/images/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.runId,
        size: el.imageSize.value,
        shots: state.shots.map((shot) => ({ ...shot, positive_prompt: shot === state.selected ? el.promptBox.value : shot.positive_prompt })),
      }),
    });
    for (const result of data.results || []) {
      if (!result.ok) continue;
      const shot = state.shots.find((item) => item.id === result.shot_id);
      if (shot) {
        shot.image_url = result.image_url;
        shot.image_path = result.image_path;
      }
    }
    renderShots();
    el.health.textContent = `批量生成完成：${(data.results || []).filter((item) => item.ok).length}/${state.shots.length}`;
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.allImagesBtn, false);
  }
}

async function exportMarkdown() {
  if (!state.runId) return;
  const response = await fetch(`/api/export/${state.runId}.md`);
  if (!response.ok) {
    el.health.textContent = "导出失败";
    return;
  }
  const markdown = await response.text();
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `ficframe-${state.runId}.md`;
  link.click();
  URL.revokeObjectURL(url);
  el.health.textContent = "Markdown 已导出";
}

async function runVlmCheck() {
  if (!state.selected || !el.qaImage.files[0]) return;
  const form = new FormData();
  form.append("image", el.qaImage.files[0]);
  form.append("shot_json", JSON.stringify({ ...state.selected, positive_prompt: el.promptBox.value }));
  try {
    const data = await api("/api/vlm", { method: "POST", body: form });
    el.qaBox.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    el.qaBox.textContent = error.message;
  }
}

el.runBtn.addEventListener("click", runPipeline);
el.charactersFile.addEventListener("change", () => {
  previewCharacters().catch((error) => {
    el.health.textContent = error.message;
  });
});
el.referenceImages.addEventListener("change", rebuildReferenceBindings);
el.previewCharactersBtn.addEventListener("click", () => {
  previewCharacters().catch((error) => {
    el.health.textContent = error.message;
  });
});
el.configToggle.addEventListener("click", () => {
  el.configPanel.hidden = !el.configPanel.hidden;
});
document.querySelector("#saveConfigBtn").addEventListener("click", saveConfig);
document.querySelector("#refreshConfigBtn").addEventListener("click", async () => {
  await loadConfig();
  await checkHealth();
});
el.imageBtn.addEventListener("click", generateImage);
el.allImagesBtn.addEventListener("click", generateAllImages);
el.exportBtn.addEventListener("click", exportMarkdown);
el.qaImage.addEventListener("change", runVlmCheck);
el.copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(el.promptBox.value);
  el.health.textContent = "Prompt 已复制";
});

loadConfig().catch((error) => {
  el.health.textContent = error.message;
});
checkHealth();
