const state = {
  runId: null,
  shots: [],
  characters: [],
  selected: null,
  providerConfig: { active: {}, sources: [] },
  selectedProviderId: null,
  referenceBindings: [],
};

const el = {
  health: document.querySelector("#health"),
  runBtn: document.querySelector("#runBtn"),
  configToggle: document.querySelector("#configToggle"),
  logExportBtn: document.querySelector("#logExportBtn"),
  configPanel: document.querySelector("#configPanel"),
  novelFile: document.querySelector("#novelFile"),
  charactersFile: document.querySelector("#charactersFile"),
  referenceImages: document.querySelector("#referenceImages"),
  referenceTable: document.querySelector("#referenceTable"),
  previewCharactersBtn: document.querySelector("#previewCharactersBtn"),
  maxShots: document.querySelector("#maxShots"),
  useLlm: document.querySelector("#useLlm"),
  imageSize: document.querySelector("#imageSize"),
  customImageSize: document.querySelector("#customImageSize"),
  charactersBox: document.querySelector("#charactersBox"),
  shotList: document.querySelector("#shotList"),
  runId: document.querySelector("#runId"),
  promptBox: document.querySelector("#promptBox"),
  copyBtn: document.querySelector("#copyBtn"),
  imageBtn: document.querySelector("#imageBtn"),
  allImagesBtn: document.querySelector("#allImagesBtn"),
  retryFailedBtn: document.querySelector("#retryFailedBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  skipExistingImages: document.querySelector("#skipExistingImages"),
  imageRetryCount: document.querySelector("#imageRetryCount"),
  preview: document.querySelector("#preview"),
  qaBox: document.querySelector("#qaBox"),
  providerList: document.querySelector("#providerList"),
  addProviderBtn: document.querySelector("#addProviderBtn"),
  deleteProviderBtn: document.querySelector("#deleteProviderBtn"),
  saveConfigBtn: document.querySelector("#saveConfigBtn"),
  refreshConfigBtn: document.querySelector("#refreshConfigBtn"),
  testProviderBtn: document.querySelector("#testProviderBtn"),
  providerTestResult: document.querySelector("#providerTestResult"),
  providerKind: document.querySelector("#providerKind"),
  providerType: document.querySelector("#providerType"),
  providerActive: document.querySelector("#providerActive"),
  providerLabel: document.querySelector("#providerLabel"),
  providerBaseUrl: document.querySelector("#providerBaseUrl"),
  providerKey: document.querySelector("#providerKey"),
  addModelBtn: document.querySelector("#addModelBtn"),
  modelTable: document.querySelector("#modelTable"),
  imageOptions: document.querySelector("#imageOptions"),
  imageSteps: document.querySelector("#imageSteps"),
  imageGuidance: document.querySelector("#imageGuidance"),
  imageBatch: document.querySelector("#imageBatch"),
  imageSequential: document.querySelector("#imageSequential"),
  imageResponseFormat: document.querySelector("#imageResponseFormat"),
  imageWatermark: document.querySelector("#imageWatermark"),
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

async function checkHealth() {
  try {
    const data = await api("/api/health");
    const keys = data.keys || {};
    const provider = data.providers?.image || "openai";
    el.health.textContent = `LLM ${keys.llm ? "已配置" : "未配置"} · 图片 ${keys.image ? "已配置" : "未配置"} (${provider})`;
  } catch (error) {
    el.health.textContent = error.message;
  }
}

async function loadConfig() {
  const data = await api("/api/providers");
  state.providerConfig = data.config || { active: {}, sources: [] };
  if (!state.selectedProviderId || !findProvider(state.selectedProviderId)) {
    state.selectedProviderId = state.providerConfig.sources[0]?.id || null;
  }
  renderProviderList();
  renderProviderDetail();
}

function findProvider(id = state.selectedProviderId) {
  return state.providerConfig.sources.find((source) => source.id === id);
}

function selectedProvider() {
  syncProviderForm();
  return findProvider();
}

function providerTemplate(kind = "image") {
  const id = `${kind}-${Date.now()}`;
  const defaults = {
    llm: { label: "新 LLM", model: "gpt-5-mini", base_url: "https://api.openai.com/v1" },
    image: { label: "新图片供应商", model: "doubao-seedream-5-0-260128", base_url: "https://ark.cn-beijing.volces.com/api/v3" },
  }[kind];
  return {
    id,
    label: defaults.label,
    kind,
    provider: kind === "image" ? "ark" : "openai",
    base_url: defaults.base_url,
    api_key: "",
    models: [{ nickname: "默认模型", model: defaults.model }],
    active_model: defaults.model,
    options: kind === "image" ? {
      steps: "20",
      guidance_scale: "7.5",
      batch_size: "1",
      sequential: "disabled",
      response_format: "url",
      watermark: "true",
    } : {},
    created_at: Math.floor(Date.now() / 1000),
  };
}

function renderProviderList() {
  const active = state.providerConfig.active || {};
  if (!state.providerConfig.sources.length) {
    el.providerList.innerHTML = `<p class="muted">暂无供应商</p>`;
    return;
  }
  el.providerList.innerHTML = state.providerConfig.sources.map((source) => {
    const isActive = active[source.kind] === source.id;
    const activeText = isActive ? "当前使用" : source.provider;
    return `
      <button class="provider-item ${source.id === state.selectedProviderId ? "active" : ""}" type="button" data-id="${escapeHtml(source.id)}">
        <strong>${escapeHtml(source.label || source.id)}</strong>
        <small>${kindLabel(source.kind)} · ${escapeHtml(activeText)}</small>
      </button>
    `;
  }).join("");
  el.providerList.querySelectorAll(".provider-item").forEach((button) => {
    button.addEventListener("click", () => {
      syncProviderForm();
      state.selectedProviderId = button.dataset.id;
      renderProviderList();
      renderProviderDetail();
    });
  });
}

function renderProviderDetail() {
  const source = findProvider();
  const disabled = !source;
  for (const node of [el.providerKind, el.providerType, el.providerActive, el.providerLabel, el.providerBaseUrl, el.providerKey, el.addModelBtn, el.deleteProviderBtn, el.testProviderBtn]) {
    node.disabled = disabled;
  }
  if (!source) {
    el.providerLabel.value = "";
    el.providerBaseUrl.value = "";
    el.providerKey.value = "";
    el.modelTable.innerHTML = "";
    return;
  }
  el.providerKind.value = source.kind || "image";
  el.providerType.value = source.provider || "openai";
  el.providerActive.value = state.providerConfig.active?.[source.kind] === source.id ? "true" : "false";
  el.providerLabel.value = source.label || "";
  el.providerBaseUrl.value = source.base_url || "";
  el.providerKey.value = source.api_key || "";
  const options = source.options || {};
  el.imageSteps.value = options.steps || "";
  el.imageGuidance.value = options.guidance_scale || "";
  el.imageBatch.value = options.batch_size || "";
  el.imageSequential.value = options.sequential || "";
  el.imageResponseFormat.value = options.response_format || "";
  el.imageWatermark.value = options.watermark || "true";
  el.imageOptions.hidden = source.kind !== "image";
  renderModelTable(source);
}

function renderModelTable(source) {
  if (!source.models?.length) {
    source.models = [{ nickname: "默认模型", model: source.active_model || "" }];
  }
  el.modelTable.innerHTML = source.models.map((model, index) => `
    <div class="model-row" data-index="${index}">
      <input data-field="nickname" value="${escapeHtml(model.nickname || "")}" placeholder="昵称，如 豆包 5.0" />
      <input data-field="model" value="${escapeHtml(model.model || "")}" placeholder="模型 ID" />
      <label class="mini-toggle">
        <input data-field="active" type="radio" name="activeModel" ${source.active_model === model.model ? "checked" : ""} />
        <span>使用</span>
      </label>
      <button data-action="remove-model" type="button">删除</button>
    </div>
  `).join("");
  el.modelTable.querySelectorAll(".model-row").forEach((row) => {
    row.addEventListener("input", () => syncProviderForm());
    row.addEventListener("change", () => syncProviderForm());
    row.querySelector('[data-action="remove-model"]').addEventListener("click", () => {
      const item = findProvider();
      if (!item || item.models.length <= 1) return;
      item.models.splice(Number(row.dataset.index), 1);
      item.active_model = item.models[0]?.model || "";
      renderModelTable(item);
    });
  });
}

function syncProviderForm() {
  const source = findProvider();
  if (!source) return;
  const previousKind = source.kind;
  source.kind = el.providerKind.value;
  source.provider = el.providerType.value;
  source.label = el.providerLabel.value.trim() || source.id;
  source.base_url = el.providerBaseUrl.value.trim();
  source.api_key = el.providerKey.value;
  source.models = Array.from(el.modelTable.querySelectorAll(".model-row")).map((row) => ({
    nickname: row.querySelector('[data-field="nickname"]').value.trim(),
    model: row.querySelector('[data-field="model"]').value.trim(),
    active: row.querySelector('[data-field="active"]').checked,
  })).filter((model) => model.model).map(({ nickname, model }) => ({ nickname: nickname || model, model }));
  const activeIndex = Array.from(el.modelTable.querySelectorAll(".model-row")).findIndex((row) => row.querySelector('[data-field="active"]').checked);
  source.active_model = source.models[Math.max(0, activeIndex)]?.model || source.models[0]?.model || "";
  source.options = source.kind === "image" ? {
    steps: el.imageSteps.value,
    guidance_scale: el.imageGuidance.value,
    batch_size: el.imageBatch.value,
    sequential: el.imageSequential.value,
    response_format: el.imageResponseFormat.value,
    watermark: el.imageWatermark.value,
  } : {};
  if (previousKind !== source.kind && state.providerConfig.active?.[previousKind] === source.id) {
    state.providerConfig.active[previousKind] = "";
  }
  if (el.providerActive.value === "true") {
    state.providerConfig.active[source.kind] = source.id;
  } else if (state.providerConfig.active?.[source.kind] === source.id) {
    state.providerConfig.active[source.kind] = "";
  }
}

async function saveProviders() {
  syncProviderForm();
  const data = await api("/api/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config: state.providerConfig }),
  });
  state.providerConfig = data.config;
  renderProviderList();
  renderProviderDetail();
  await checkHealth();
  el.health.textContent = "供应商配置已保存";
}

async function testProvider() {
  const source = selectedProvider();
  if (!source) return;
  setBusy(el.testProviderBtn, true);
  el.providerTestResult.textContent = "测试中";
  try {
    const data = await api("/api/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    el.providerTestResult.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    el.providerTestResult.textContent = error.message;
  } finally {
    setBusy(el.testProviderBtn, false);
  }
}

function renderCharacters() {
  if (!state.characters.length) {
    el.charactersBox.textContent = "";
    return;
  }
  el.charactersBox.textContent = state.characters.map((character) => {
    const refs = character.reference_images?.length ? `\n参考图：${character.reference_images.length} 张` : "\n参考图：无";
    return `${character.name}\n${character.role}${refs}\n${(character.fixed_traits || []).join(" / ")}`;
  }).join("\n\n");
}

function selectShot(index) {
  state.selected = state.shots[index];
  el.promptBox.value = state.selected?.positive_prompt || "";
  el.qaBox.textContent = (state.selected?.qa_notes || []).join("\n");
  el.preview.innerHTML = state.selected?.image_url ? `<img alt="${state.selected.id}" src="${state.selected.image_url}" />` : "";
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
      <strong>${escapeHtml(shot.id)} · ${escapeHtml(shot.title)}</strong>
      <small>${escapeHtml(shot.characters.join("、") || "无明确角色")} · ${escapeHtml(shot.location)} · ${escapeHtml(shot.time)}</small>
      <small>${shot.image_url ? "已生成图片" : "未生成图片"}</small>
      <small>${escapeHtml(shot.visual_goal)}</small>
    `;
    button.addEventListener("click", () => selectShot(index));
    el.shotList.append(button);
  });
  if (state.shots.length) {
    const index = Math.max(0, state.shots.findIndex((shot) => shot.id === preferredId));
    selectShot(index);
  }
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
  const options = [`<option value="">未绑定</option>`].concat(
    state.characters.map((character) => `<option value="${escapeHtml(character.name)}">${escapeHtml(character.name)}</option>`)
  ).join("");
  el.referenceTable.innerHTML = state.referenceBindings.map((binding, index) => `
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
  `).join("");
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

function selectedImageSize() {
  return el.customImageSize.value.trim() || el.imageSize.value;
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
        size: selectedImageSize(),
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
    const data = await generateImageBatch(state.shots, {
      skipExisting: el.skipExistingImages.checked,
      retryCount: Number(el.imageRetryCount.value || 0),
    });
    applyImageBatchResults(data.results || []);
    const okCount = (data.results || []).filter((item) => item.ok).length;
    const skippedCount = (data.results || []).filter((item) => item.skipped).length;
    const failures = (data.results || []).filter((item) => !item.ok);
    el.health.textContent = `批量生成完成：${okCount}/${state.shots.length}${skippedCount ? `，跳过 ${skippedCount}` : ""}`;
    if (failures.length) {
      el.qaBox.textContent = failures.map((item) => `${item.shot_id}: ${item.error}`).join("\n\n");
    }
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.allImagesBtn, false);
  }
}

async function retryFailedImages() {
  if (!state.shots.length || !state.runId) return;
  const failedShots = state.shots.filter((shot) => !shot.image_url && !shot.image_path);
  if (!failedShots.length) {
    el.health.textContent = "没有需要重试的失败分镜";
    return;
  }
  setBusy(el.retryFailedBtn, true);
  try {
    const data = await generateImageBatch(failedShots, {
      skipExisting: false,
      retryCount: Number(el.imageRetryCount.value || 1),
    });
    applyImageBatchResults(data.results || []);
    const okCount = (data.results || []).filter((item) => item.ok).length;
    const failures = (data.results || []).filter((item) => !item.ok);
    el.health.textContent = `失败重试完成：${okCount}/${failedShots.length}`;
    el.qaBox.textContent = failures.length ? failures.map((item) => `${item.shot_id}: ${item.error}`).join("\n\n") : "失败项已全部重试成功";
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.retryFailedBtn, false);
  }
}

async function generateImageBatch(shots, { skipExisting, retryCount }) {
  return api("/api/images/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.runId,
        size: selectedImageSize(),
        skip_existing: skipExisting,
        retry_count: retryCount,
        shots: shots.map((shot) => ({ ...shot, positive_prompt: shot === state.selected ? el.promptBox.value : shot.positive_prompt })),
      }),
    });
}

function applyImageBatchResults(results) {
  for (const result of results) {
    if (!result.ok) continue;
    const shot = state.shots.find((item) => item.id === result.shot_id);
    if (shot) {
      shot.image_url = result.image_url;
      shot.image_path = result.image_path;
    }
  }
  renderShots(state.selected?.id);
}

async function exportMarkdown() {
  if (!state.runId) return;
  try {
    const data = await api(`/api/export/${state.runId}`);
    const response = await fetch(data.markdown_url);
    const markdown = await response.text();
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `illustrated_novel-${state.runId}.md`;
    link.click();
    URL.revokeObjectURL(url);
    el.health.textContent = "配图小说 MD 已导出";
    el.qaBox.textContent = `已保存到：${data.markdown_path}\n图片路径相对于该 Markdown 所在目录。`;
  } catch (error) {
    el.health.textContent = `导出失败：${error.message}`;
  }
}

async function exportLogs() {
  setBusy(el.logExportBtn, true);
  try {
    const response = await fetch("/api/logs/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.runId }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || response.statusText);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match?.[1] || `ficframe-logs-${Date.now()}.zip`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    el.health.textContent = "日志包已导出";
    el.qaBox.textContent = `已导出日志包：${filename}\n反馈 bug 时可以附带这个 zip。`;
  } catch (error) {
    el.health.textContent = `日志导出失败：${error.message}`;
  } finally {
    setBusy(el.logExportBtn, false);
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function kindLabel(kind) {
  return { llm: "LLM", image: "图片" }[kind] || kind;
}

el.runBtn.addEventListener("click", runPipeline);
el.charactersFile.addEventListener("change", () => previewCharacters().catch((error) => {
  el.health.textContent = error.message;
}));
el.referenceImages.addEventListener("change", rebuildReferenceBindings);
el.previewCharactersBtn.addEventListener("click", () => previewCharacters().catch((error) => {
  el.health.textContent = error.message;
}));
el.configToggle.addEventListener("click", () => {
  el.configPanel.hidden = !el.configPanel.hidden;
});
el.logExportBtn.addEventListener("click", exportLogs);
el.addProviderBtn.addEventListener("click", () => {
  syncProviderForm();
  const source = providerTemplate(el.providerKind.value || "image");
  state.providerConfig.sources.push(source);
  state.selectedProviderId = source.id;
  renderProviderList();
  renderProviderDetail();
});
el.deleteProviderBtn.addEventListener("click", () => {
  const source = findProvider();
  if (!source) return;
  state.providerConfig.sources = state.providerConfig.sources.filter((item) => item.id !== source.id);
  if (state.providerConfig.active?.[source.kind] === source.id) {
    state.providerConfig.active[source.kind] = "";
  }
  state.selectedProviderId = state.providerConfig.sources[0]?.id || null;
  renderProviderList();
  renderProviderDetail();
});
el.addModelBtn.addEventListener("click", () => {
  const source = selectedProvider();
  if (!source) return;
  source.models.push({ nickname: "新模型", model: "" });
  renderModelTable(source);
});
for (const node of [el.providerKind, el.providerType, el.providerActive, el.providerLabel, el.providerBaseUrl, el.providerKey, el.imageSteps, el.imageGuidance, el.imageBatch, el.imageSequential, el.imageResponseFormat, el.imageWatermark]) {
  node.addEventListener("input", () => {
    syncProviderForm();
    renderProviderList();
    el.imageOptions.hidden = findProvider()?.kind !== "image";
  });
  node.addEventListener("change", () => {
    syncProviderForm();
    renderProviderList();
    el.imageOptions.hidden = findProvider()?.kind !== "image";
  });
}
el.saveConfigBtn.addEventListener("click", saveProviders);
el.refreshConfigBtn.addEventListener("click", async () => {
  await loadConfig();
  await checkHealth();
});
el.testProviderBtn.addEventListener("click", testProvider);
el.imageBtn.addEventListener("click", generateImage);
el.allImagesBtn.addEventListener("click", generateAllImages);
el.retryFailedBtn.addEventListener("click", retryFailedImages);
el.exportBtn.addEventListener("click", exportMarkdown);
el.copyBtn.addEventListener("click", async () => {
  await navigator.clipboard.writeText(el.promptBox.value);
  el.health.textContent = "Prompt 已复制";
});

loadConfig().catch((error) => {
  el.health.textContent = error.message;
});
checkHealth();
