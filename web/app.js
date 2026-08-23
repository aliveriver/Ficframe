const workspaceState = window.FicFrameWorkspaceState;
const state = workspaceState.createInitialState();

const WORKSPACE_KEY = "ficframe.workspace.v1";
let draftTimer = null;

const el = {
  health: document.querySelector("#health"),
  taskPanel: document.querySelector("#taskPanel"),
  taskKind: document.querySelector("#taskKind"),
  taskStage: document.querySelector("#taskStage"),
  taskMessage: document.querySelector("#taskMessage"),
  taskError: document.querySelector("#taskError"),
  taskProgress: document.querySelector("#taskProgress"),
  taskProgressText: document.querySelector("#taskProgressText"),
  taskLogs: document.querySelector("#taskLogs"),
  runBtn: document.querySelector("#runBtn"),
  configToggle: document.querySelector("#configToggle"),
  cleanStartBtn: document.querySelector("#cleanStartBtn"),
  restoreRunBtn: document.querySelector("#restoreRunBtn"),
  logExportBtn: document.querySelector("#logExportBtn"),
  configPanel: document.querySelector("#configPanel"),
  novelFile: document.querySelector("#novelFile"),
  charactersFile: document.querySelector("#charactersFile"),
  referenceImages: document.querySelector("#referenceImages"),
  referenceTable: document.querySelector("#referenceTable"),
  previewCharactersBtn: document.querySelector("#previewCharactersBtn"),
  llmExtractCharactersBtn: document.querySelector("#llmExtractCharactersBtn"),
  llmEnhanceCharactersBtn: document.querySelector("#llmEnhanceCharactersBtn"),
  llmPromptBankBtn: document.querySelector("#llmPromptBankBtn"),
  localPromptBankBtn: document.querySelector("#localPromptBankBtn"),
  llmDiffBtn: document.querySelector("#llmDiffBtn"),
  manualCharacterToggleBtn: document.querySelector("#manualCharacterToggleBtn"),
  manualCharacterPanel: document.querySelector("#manualCharacterPanel"),
  manualCharacterName: document.querySelector("#manualCharacterName"),
  manualCharacterRole: document.querySelector("#manualCharacterRole"),
  manualCharacterNote: document.querySelector("#manualCharacterNote"),
  addManualCharacterBtn: document.querySelector("#addManualCharacterBtn"),
  maxShots: document.querySelector("#maxShots"),
  useLlm: document.querySelector("#useLlm"),
  llmProfile: document.querySelector("#llmProfile"),
  llmConcurrency: document.querySelector("#llmConcurrency"),
  llmModeHelpToggleBtn: document.querySelector("#llmModeHelpToggleBtn"),
  llmModeHelpPanel: document.querySelector("#llmModeHelpPanel"),
  rulesToggleBtn: document.querySelector("#rulesToggleBtn"),
  rulesPanel: document.querySelector("#rulesPanel"),
  imageSize: document.querySelector("#imageSize"),
  customImageSize: document.querySelector("#customImageSize"),
  charactersBox: document.querySelector("#charactersBox"),
  characterDiffBox: document.querySelector("#characterDiffBox"),
  shotList: document.querySelector("#shotList"),
  runId: document.querySelector("#runId"),
  openNovelBtn: document.querySelector("#openNovelBtn"),
  addShotBtn: document.querySelector("#addShotBtn"),
  regenerateSelectedBtn: document.querySelector("#regenerateSelectedBtn"),
  regenerateAllBtn: document.querySelector("#regenerateAllBtn"),
  feedbackHistory: document.querySelector("#feedbackHistory"),
  feedbackInput: document.querySelector("#feedbackInput"),
  sendFeedbackBtn: document.querySelector("#sendFeedbackBtn"),
  promptFeedbackHistory: document.querySelector("#promptFeedbackHistory"),
  promptFeedbackInput: document.querySelector("#promptFeedbackInput"),
  savePromptFeedbackBtn: document.querySelector("#savePromptFeedbackBtn"),
  locateSourceBtn: document.querySelector("#locateSourceBtn"),
  saveShotBtn: document.querySelector("#saveShotBtn"),
  deleteShotBtn: document.querySelector("#deleteShotBtn"),
  shotTitle: document.querySelector("#shotTitle"),
  shotLocation: document.querySelector("#shotLocation"),
  shotTime: document.querySelector("#shotTime"),
  shotCharacters: document.querySelector("#shotCharacters"),
  shotMood: document.querySelector("#shotMood"),
  shotCamera: document.querySelector("#shotCamera"),
  shotComposition: document.querySelector("#shotComposition"),
  shotVisualGoal: document.querySelector("#shotVisualGoal"),
  shotSourceExcerpt: document.querySelector("#shotSourceExcerpt"),
  storyboardVersionCount: document.querySelector("#storyboardVersionCount"),
  storyboardVersions: document.querySelector("#storyboardVersions"),
  promptBox: document.querySelector("#promptBox"),
  negativePromptBox: document.querySelector("#negativePromptBox"),
  copyBtn: document.querySelector("#copyBtn"),
  restorePromptBtn: document.querySelector("#restorePromptBtn"),
  rebuildPromptBtn: document.querySelector("#rebuildPromptBtn"),
  llmPromptBtn: document.querySelector("#llmPromptBtn"),
  characterEditorSelect: document.querySelector("#characterEditorSelect"),
  identityPromptBox: document.querySelector("#identityPromptBox"),
  appearanceStatesBox: document.querySelector("#appearanceStatesBox"),
  negativeIdentityPromptBox: document.querySelector("#negativeIdentityPromptBox"),
  restoreCharacterBtn: document.querySelector("#restoreCharacterBtn"),
  rebuildAllPromptsBtn: document.querySelector("#rebuildAllPromptsBtn"),
  imageBtn: document.querySelector("#imageBtn"),
  selectedImagesBtn: document.querySelector("#selectedImagesBtn"),
  allImagesBtn: document.querySelector("#allImagesBtn"),
  retryFailedBtn: document.querySelector("#retryFailedBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  skipExistingImages: document.querySelector("#skipExistingImages"),
  imageRetryCount: document.querySelector("#imageRetryCount"),
  preview: document.querySelector("#preview"),
  imageVersions: document.querySelector("#imageVersions"),
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
  providerBaseUrlLabel: document.querySelector("#providerBaseUrlLabel"),
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
  comfyOptions: document.querySelector("#comfyOptions"),
  comfyWorkflowFile: document.querySelector("#comfyWorkflowFile"),
  comfyWorkflow: document.querySelector("#comfyWorkflow"),
  comfyNegativePrompt: document.querySelector("#comfyNegativePrompt"),
  comfyOutputNode: document.querySelector("#comfyOutputNode"),
  comfyPollInterval: document.querySelector("#comfyPollInterval"),
  novelDialog: document.querySelector("#novelDialog"),
  novelDialogTitle: document.querySelector("#novelDialogTitle"),
  novelSelectionStatus: document.querySelector("#novelSelectionStatus"),
  novelText: document.querySelector("#novelText"),
  novelHighlightPreview: document.querySelector("#novelHighlightPreview"),
  newShotDescription: document.querySelector("#newShotDescription"),
  closeNovelBtn: document.querySelector("#closeNovelBtn"),
  clearNovelSelectionBtn: document.querySelector("#clearNovelSelectionBtn"),
  generateShotBtn: document.querySelector("#generateShotBtn"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

const storyboardWorkspace = window.FicFrameStoryboardWorkspace;
const storyboardClient = storyboardWorkspace.createClient(api);
const taskMonitor = window.FicFrameTaskMonitor.createMonitor({
  request: api,
  elements: {
    panel: el.taskPanel,
    kind: el.taskKind,
    stage: el.taskStage,
    message: el.taskMessage,
    error: el.taskError,
    progress: el.taskProgress,
    progressText: el.taskProgressText,
    logs: el.taskLogs,
  },
  onUpdate(task) {
    if (task.status === "running" || task.status === "queued") {
      el.health.textContent = `${task.stage || "执行中"} · ${task.message || "后台任务处理中"}`;
    }
  },
});
const novelSource = window.FicFrameNovelSource.createController({
  state,
  elements: {
    dialog: el.novelDialog,
    title: el.novelDialogTitle,
    status: el.novelSelectionStatus,
    text: el.novelText,
    preview: el.novelHighlightPreview,
    description: el.newShotDescription,
    clear: el.clearNovelSelectionBtn,
    generate: el.generateShotBtn,
  },
  workspace: storyboardWorkspace,
  escapeHtml,
  loadNovel: loadNovelForRun,
});
const imageWorkflow = window.FicFrameImageWorkflow.createController({
  state,
  elements: el,
  api,
  taskMonitor,
  escapeHtml,
  clone,
  setBusy,
  saveSelectedPrompt,
  saveCharacterEditor,
  saveWorkspaceDraft,
  renderShots,
  selectedImageSize,
});

function saveWorkspaceDraft() {
  saveSelectedPrompt();
  saveShotEditor();
  saveCharacterEditor();
  workspaceState.saveDraft(localStorage, WORKSPACE_KEY, state);
}

function scheduleWorkspaceDraftSave() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(saveWorkspaceDraft, 400);
}

function restoreWorkspaceDraft() {
  const draft = workspaceState.loadDraft(localStorage, WORKSPACE_KEY);
  if (!draft) return false;
  hydrateWorkspace(draft, draft.selectedShotId);
  el.health.textContent = state.runId ? `已恢复浏览器草稿 run ${state.runId}` : "已恢复浏览器草稿";
  return true;
}

function hydrateWorkspace(payload, preferredShotId = null) {
  const previousRunId = state.runId;
  state.runId = payload.runId || payload.run_id;
  state.shots = payload.shots || [];
  state.scenes = payload.scenes || [];
  const allCharacters = payload.characters || [];
  const partitioned = partitionCharacters(allCharacters);
  state.autoCharacters = payload.autoCharacters || partitioned.auto;
  state.manualCharacters = payload.manualCharacters || partitioned.manual;
  composeCharacters();
  state.originalShots = payload.originalShots || clone(state.shots);
  state.originalCharacters = payload.originalCharacters || clone(state.characters);
  state.differenceAnalysis = payload.differenceAnalysis || payload.difference_analysis || null;
  state.novelText = storyboardWorkspace.normalizeNovelText(
    payload.novelText || payload.novel_text || (previousRunId === state.runId ? state.novelText : "") || "",
  );
  state.storyboardMessages = payload.storyboardMessages || payload.storyboard_messages || [];
  state.promptFeedbackMessages = payload.promptFeedbackMessages || payload.prompt_feedback_messages || [];
  state.storyboardVersions = payload.storyboardVersions || payload.storyboard_versions || {};
  state.selectedShotIds = new Set(payload.selectedShotIds || []);
  state.selectedCharacterIndex = Math.min(payload.selectedCharacterIndex || 0, Math.max(0, state.characters.length - 1));
  el.runId.textContent = state.runId ? `run ${state.runId}` : "未运行";
  renderCharacters();
  renderFeedbackHistory();
  renderPromptFeedbackHistory();
  renderShots(preferredShotId || state.shots[0]?.id);
  if (state.runId && !state.novelText) {
    loadNovelForRun().catch(() => {});
  }
  if (state.runId) taskMonitor.loadRunTasks(state.runId).catch(() => {});
}

async function refreshRunAfterTask(runId, preferredShotId = null) {
  const payload = await api(`/api/runs/${encodeURIComponent(runId)}`);
  hydrateWorkspace(payload, preferredShotId);
  saveWorkspaceDraft();
  return payload;
}

function clearRunArtifacts(message = "新输入已选择，请重新生成分镜") {
  workspaceState.resetRun(state);
  el.runId.textContent = "新输入未运行";
  el.shotList.innerHTML = "";
  el.promptBox.value = "";
  el.negativePromptBox.value = "";
  loadShotEditor();
  renderStoryboardVersions();
  el.preview.innerHTML = "";
  el.imageVersions.innerHTML = "";
  el.qaBox.textContent = "";
  renderFeedbackHistory();
  renderPromptFeedbackHistory();
  el.health.textContent = message;
  saveWorkspaceDraft();
}

function clearWorkspaceForRecording(message = "") {
  localStorage.removeItem(WORKSPACE_KEY);
  workspaceState.resetAll(state);
  el.runId.textContent = "未运行";
  el.shotList.innerHTML = "";
  el.promptBox.value = "";
  el.negativePromptBox.value = "";
  loadShotEditor();
  renderStoryboardVersions();
  el.charactersBox.textContent = "";
  el.characterDiffBox.textContent = "";
  el.characterEditorSelect.innerHTML = "";
  el.identityPromptBox.value = "";
  el.appearanceStatesBox.value = "";
  el.negativeIdentityPromptBox.value = "";
  el.referenceTable.innerHTML = `<p class="muted">尚未选择参考图</p>`;
  el.preview.innerHTML = "";
  el.imageVersions.innerHTML = "";
  el.qaBox.textContent = "";
  renderFeedbackHistory();
  renderPromptFeedbackHistory();
  if (message) {
    el.health.textContent = message;
  }
}

function cleanStartRequested() {
  const params = new URLSearchParams(window.location.search);
  return params.has("clean") || params.has("fresh");
}

function selectedFileLabel(file) {
  return file ? `${file.name}（${Math.max(0, Math.round(file.size / 1024))} KB）` : "";
}

function validateInputFiles() {
  const novel = el.novelFile.files[0];
  const characters = el.charactersFile.files[0];
  if (!novel || !characters) {
    return "请选择小说和人物文件";
  }
  if (!novel.size) {
    return `小说文件为空：${novel.name}`;
  }
  if (!characters.size) {
    return `人物文件为空：${characters.name}`;
  }
  return "";
}

function partitionCharacters(characters = []) {
  const manual = [];
  const auto = [];
  for (const character of characters) {
    if (character?.manual) {
      manual.push(character);
    } else {
      auto.push(character);
    }
  }
  return { auto, manual };
}

function composeCharacters() {
  const manualNames = new Set(state.manualCharacters.map((character) => character.name));
  state.characters = [
    ...state.autoCharacters.filter((character) => !manualNames.has(character.name)),
    ...state.manualCharacters,
  ];
}

function snapshotCurrentCharacters() {
  state.originalCharacters = clone(state.characters);
}

function replaceCharacterInCollections(card) {
  const collection = card.manual ? state.manualCharacters : state.autoCharacters;
  const index = collection.findIndex((character) => character.name === card.name);
  if (index >= 0) {
    collection[index] = card;
  }
  composeCharacters();
}

async function restoreLatestRun() {
  const data = await api("/api/runs");
  const latest = data.runs?.[0];
  if (!latest) {
    el.health.textContent = "没有可恢复的历史 run";
    return;
  }
  const payload = await api(`/api/runs/${encodeURIComponent(latest.run_id)}`);
  hydrateWorkspace(payload);
  saveWorkspaceDraft();
  el.health.textContent = `已恢复最近 run ${state.runId}，${state.shots.length} 张分镜`;
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
    el.health.textContent = `LLM ${keys.llm ? "已配置" : "未配置"} · VLM ${keys.vlm ? "已配置" : "未配置"} · 图片 ${keys.image ? "已配置" : "未配置"} (${provider})`;
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
    vlm: { label: "新 VLM", model: "gpt-5-mini", base_url: "https://api.openai.com/v1" },
    image: { label: "新图片供应商", model: "doubao-seedream-5-0-260128", base_url: "https://ark.cn-beijing.volces.com/api/v3" },
  }[kind] || { label: "新供应商", model: "", base_url: "" };
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
      workflow_json: "",
      negative_prompt: "",
      output_node_id: "",
      poll_interval: "1",
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
  renderProviderBaseUrlField(source.provider);
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
  el.comfyWorkflow.value = options.workflow_json || "";
  el.comfyNegativePrompt.value = options.negative_prompt || "";
  el.comfyOutputNode.value = options.output_node_id || "";
  el.comfyPollInterval.value = options.poll_interval || "1";
  el.imageOptions.hidden = source.kind !== "image";
  el.comfyOptions.hidden = source.kind !== "image" || source.provider !== "comfyui";
  renderModelTable(source);
}

function renderProviderBaseUrlField(provider) {
  const isComfyUI = provider === "comfyui";
  el.providerBaseUrlLabel.textContent = isComfyUI ? "服务地址（HTTP）" : "请求地址";
  el.providerBaseUrl.placeholder = isComfyUI
    ? "CLI 默认 127.0.0.1:8188；Desktop 从 8000 起自动选端口"
    : "https://api.example.com/v1";
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
    workflow_json: el.comfyWorkflow.value,
    negative_prompt: el.comfyNegativePrompt.value,
    output_node_id: el.comfyOutputNode.value.trim(),
    poll_interval: el.comfyPollInterval.value || "1",
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
  try {
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
  } catch (error) {
    el.providerTestResult.textContent = error.message;
    el.health.textContent = error.message;
  }
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
    if (data.resolved_base_url) {
      el.providerBaseUrl.value = data.resolved_base_url;
      syncProviderForm();
    }
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
    el.characterDiffBox.textContent = "";
    el.characterEditorSelect.innerHTML = "";
    el.identityPromptBox.value = "";
    el.appearanceStatesBox.value = "";
    el.negativeIdentityPromptBox.value = "";
    return;
  }
  el.charactersBox.textContent = state.characters.map((character) => {
    const manual = character.manual ? "（手动）" : "";
    const refs = character.reference_images?.length ? `\n参考图：${character.reference_images.length} 张` : "\n参考图：无";
    const bank = character.identity_prompt ? "\nPrompt Bank：已生成" : "\nPrompt Bank：未生成";
    return `${character.name}${manual}\n${character.role}${refs}${bank}\n${(character.fixed_traits || []).join(" / ")}`;
  }).join("\n\n");
  renderCharacterEditor();
  renderCharacterDiff();
}

function renderCharacterEditor() {
  const currentName = state.characters[state.selectedCharacterIndex]?.name;
  el.characterEditorSelect.innerHTML = state.characters.map((character, index) => (
    `<option value="${index}">${escapeHtml(character.name)}</option>`
  )).join("");
  if (currentName) {
    const nextIndex = state.characters.findIndex((character) => character.name === currentName);
    state.selectedCharacterIndex = Math.max(0, nextIndex);
  }
  el.characterEditorSelect.value = String(state.selectedCharacterIndex);
  loadCharacterEditor();
}

function loadCharacterEditor() {
  const character = state.characters[state.selectedCharacterIndex];
  if (!character) return;
  el.identityPromptBox.value = character.identity_prompt || character.prompt_en || "";
  el.appearanceStatesBox.value = JSON.stringify(character.appearance_states || [], null, 2);
  el.negativeIdentityPromptBox.value = character.negative_identity_prompt || "";
}

function saveCharacterEditor() {
  const character = state.characters[state.selectedCharacterIndex];
  if (!character) return;
  character.identity_prompt = el.identityPromptBox.value;
  character.negative_identity_prompt = el.negativeIdentityPromptBox.value;
  try {
    character.appearance_states = JSON.parse(el.appearanceStatesBox.value || "[]");
  } catch (error) {
    el.health.textContent = `外貌状态计划 JSON 格式错误：${error.message}`;
  }
}

function restoreSelectedCharacter() {
  const current = state.characters[state.selectedCharacterIndex];
  if (!current) return;
  const original = state.originalCharacters.find((character) => character.name === current.name);
  if (!original) return;
  replaceCharacterInCollections(clone(original));
  state.selectedCharacterIndex = state.characters.findIndex((character) => character.name === current.name);
  loadCharacterEditor();
  renderCharacters();
  el.health.textContent = `${current.name} 已恢复到初始角色文本`;
}

function renderCharacterDiff() {
  const analysis = state.differenceAnalysis;
  if (!analysis?.pairs?.length) {
    el.characterDiffBox.textContent = state.characters.length > 1 ? "角色差异分析：暂无明显混淆风险" : "";
    return;
  }
  const riskyPairs = analysis.pairs.filter((pair) => pair.risk_score >= 30).slice(0, 6);
  if (!riskyPairs.length) {
    el.characterDiffBox.textContent = "角色差异分析：暂无明显混淆风险";
    return;
  }
  el.characterDiffBox.textContent = [
    "角色差异分析",
    ...riskyPairs.map((pair) => {
      const shared = pair.shared_features?.length ? `共享：${pair.shared_features.join("、")}` : "共享：较少";
      const left = pair.left_unique?.length ? `${pair.left}：${pair.left_unique.join("、")}` : `${pair.left}：建议补充差异点`;
      const right = pair.right_unique?.length ? `${pair.right}：${pair.right_unique.join("、")}` : `${pair.right}：建议补充差异点`;
      return `\n${pair.left} / ${pair.right} · 风险${pair.risk_level}(${pair.risk_score})\n${shared}\n${left}\n${right}`;
    }),
  ].join("\n");
}

function selectShot(index) {
  saveSelectedPrompt();
  saveShotEditor();
  saveCharacterEditor();
  state.selected = state.shots[index];
  el.promptBox.value = state.selected?.positive_prompt || "";
  el.negativePromptBox.value = state.selected?.negative_prompt || "";
  loadShotEditor();
  renderStoryboardVersions();
  el.qaBox.textContent = (state.selected?.qa_notes || []).join("\n");
  el.preview.innerHTML = state.selected?.image_url ? `<img alt="${state.selected.id}" src="${state.selected.image_url}" />` : "";
  imageWorkflow.renderVersions();
  document.querySelectorAll(".shot").forEach((node, nodeIndex) => {
    node.classList.toggle("active", nodeIndex === index);
  });
}

function loadShotEditor() {
  const shot = state.selected;
  const values = shot ? {
    shotTitle: shot.title,
    shotLocation: shot.location,
    shotTime: shot.time,
    shotCharacters: (shot.characters || []).join("、"),
    shotMood: (shot.mood || []).join("、"),
    shotCamera: shot.camera,
    shotComposition: shot.composition,
    shotVisualGoal: shot.visual_goal,
  } : {};
  for (const [key, value] of Object.entries(values)) {
    el[key].value = value || "";
  }
  if (!shot) {
    for (const key of ["shotTitle", "shotLocation", "shotTime", "shotCharacters", "shotMood", "shotCamera", "shotComposition", "shotVisualGoal"]) {
      el[key].value = "";
    }
  }
  el.shotSourceExcerpt.textContent = shot
    ? sourceReferenceSummary(shot)
    : "选择分镜后显示对应小说段落";
}

function sourceReferenceSummary(shot) {
  const reference = shot.source_ref || {};
  const labels = { exact: "精确定位", relocated: "已重新定位", unresolved: "无法定位", description: "文本描述生成" };
  const status = labels[reference.status] || (shot.generation_mode === "description" ? "文本描述生成" : "旧版引用");
  const quote = reference.quote || shot.source_text || shot.source_excerpt || shot.generation_description || "这条分镜没有绑定小说原文";
  return `${status} · ${quote}`;
}

function saveShotEditor() {
  if (!state.selected) return;
  state.selected.title = el.shotTitle.value.trim();
  state.selected.location = el.shotLocation.value.trim();
  state.selected.time = el.shotTime.value.trim();
  state.selected.characters = storyboardWorkspace.splitEditorList(el.shotCharacters.value);
  state.selected.mood = storyboardWorkspace.splitEditorList(el.shotMood.value);
  state.selected.camera = el.shotCamera.value.trim();
  state.selected.composition = el.shotComposition.value.trim();
  state.selected.visual_goal = el.shotVisualGoal.value.trim();
}

function renderStoryboardVersions() {
  if (!el.storyboardVersions || !el.storyboardVersionCount) return;
  const versions = state.selected ? (state.storyboardVersions[state.selected.id] || []) : [];
  el.storyboardVersionCount.textContent = versions.length ? `${versions.length} 个历史版本` : "暂无历史版本";
  el.storyboardVersions.innerHTML = storyboardWorkspace.versionHistoryMarkup(
    versions,
    state.selected?.id || "",
    escapeHtml,
  );
  el.storyboardVersions.querySelectorAll("button[data-storyboard-version]").forEach((button) => {
    button.addEventListener("click", () => restoreStoryboardVersion(button.dataset.storyboardVersion).catch((error) => {
      el.health.textContent = `恢复失败：${error.message}`;
    }));
  });
}

async function restoreStoryboardVersion(versionId) {
  if (!state.runId || !state.selected || !versionId) return;
  const shotId = state.selected.id;
  const data = await storyboardClient.restoreVersion(state.runId, shotId, versionId);
  state.shots = data.shots || state.shots;
  state.storyboardVersions = data.storyboard_versions || state.storyboardVersions;
  renderShots(shotId);
  saveWorkspaceDraft();
  el.health.textContent = `${shotId} 已恢复历史版本；恢复前的版本和现有图片均已保留`;
}

function saveSelectedPrompt() {
  if (!state.selected) return;
  window.FicFramePromptState.updateShotPositivePrompt(state.selected, el.promptBox.value);
  state.selected.negative_prompt = el.negativePromptBox.value;
}

function restoreSelectedPrompt() {
  if (!state.selected) return;
  const original = state.originalShots.find((shot) => shot.id === state.selected.id);
  if (!original) return;
  state.selected.positive_prompt = original.positive_prompt || "";
  state.selected.negative_prompt = original.negative_prompt || "";
  state.selected.character_layout = clone(original.character_layout || []);
  state.selected.regional_guidance = original.regional_guidance ?? null;
  el.promptBox.value = state.selected.positive_prompt;
  el.negativePromptBox.value = state.selected.negative_prompt;
  el.health.textContent = `${state.selected.id} prompt 已恢复到初始文本`;
  saveWorkspaceDraft();
}

function rebuildSelectedPrompt() {
  if (!state.selected) return;
  saveCharacterEditor();
  window.FicFramePromptState.updateShotPositivePrompt(state.selected, buildPromptFromShot(state.selected));
  state.selected.negative_prompt = buildNegativePromptFromShot(state.selected);
  el.promptBox.value = state.selected.positive_prompt;
  el.negativePromptBox.value = state.selected.negative_prompt;
  el.health.textContent = `${state.selected.id} prompt 已根据角色库重建`;
  saveWorkspaceDraft();
}

async function regenerateSelectedPromptWithLlm() {
  if (!state.selected || !state.runId) return;
  const shotId = state.selected.id;
  setBusy(el.llmPromptBtn, true);
  try {
    await persistStoryboard({ quiet: true });
    const created = await storyboardClient.regeneratePromptTask(state.runId, shotId);
    const data = await taskMonitor.wait(created.task_id);
    state.shots = data.shots || state.shots;
    state.promptFeedbackMessages = data.prompt_feedback_messages || state.promptFeedbackMessages;
    state.storyboardVersions = data.storyboard_versions || state.storyboardVersions;
    renderShots(shotId);
    renderPromptFeedbackHistory();
    saveWorkspaceDraft();
    el.health.textContent = `${shotId} 的生图 Prompt 已由 LLM 重建，旧版本已保存`;
  } finally {
    setBusy(el.llmPromptBtn, false);
  }
}

function rebuildAllPrompts(message = "全部 prompt 已根据角色库重建") {
  saveSelectedPrompt();
  saveCharacterEditor();
  for (const shot of state.shots) {
    window.FicFramePromptState.updateShotPositivePrompt(shot, buildPromptFromShot(shot));
    shot.negative_prompt = buildNegativePromptFromShot(shot);
  }
  if (state.selected) {
    el.promptBox.value = state.selected.positive_prompt;
    el.negativePromptBox.value = state.selected.negative_prompt;
  }
  el.health.textContent = message;
  saveWorkspaceDraft();
}

function buildPromptFromShot(shot) {
  const characters = (shot.characters || []).map((name, index) => {
    const character = state.characters.find((item) => item.name === name);
    if (!character) return `Character ${index + 1}: ${name}`;
    return [
      `Character ${index + 1}: ${character.identity_prompt || character.prompt_en || character.name}`,
      `Current visible state: ${currentAppearanceState(character, shot)}`,
    ].join("\n");
  }).join("\n");
  return [
    "high quality anime light novel illustration, cinematic composition",
    "",
    "Scene:",
    `${shot.location || "unspecified location"}, ${shot.time || "unspecified time"}. ${shot.visual_goal || shot.source_excerpt || ""}`,
    `Mood: ${(shot.mood || []).join(", ") || "calm"}.`,
    "",
    "Composition:",
    `${shot.camera || "cinematic shot"}. ${shot.composition || "clear readable composition"}.`,
    `${shot.characters?.length || 0 ? `exactly ${shot.characters.length} visible characters, no extra people.` : "no extra people unless explicitly required by the story."}`,
    "",
    "Characters:",
    characters,
    "",
    "Relationships:",
    "Keep each named character individually recognizable. Preserve identity, silhouette, hairstyle, outfit logic, props, and emotional function.",
    "",
    "Style:",
    "soft volumetric light, gentle rim light, natural skin tones, restrained teal and amber accents, clean detailed linework, subtle painterly texture, quiet emotional storytelling, detailed character design.",
  ].join("\n");
}

function buildNegativePromptFromShot(shot) {
  const constraints = [
    "extra people",
    "duplicate character",
    "same face between different characters",
    "merged characters",
    "wrong character identity",
    ...(shot.characters || []).map((name) => {
      const character = state.characters.find((item) => item.name === name);
      return character?.negative_identity_prompt || "";
    }),
  ].filter(Boolean);
  let result = (shot.negative_prompt || "").trim();
  for (const constraint of constraints) {
    if (!result.toLowerCase().includes(constraint.toLowerCase())) {
      result = [result, constraint].filter(Boolean).join(", ");
    }
  }
  return result;
}

function currentAppearanceState(character, shot) {
  const states = Array.isArray(character.appearance_states) ? character.appearance_states : [];
  const matched = states.find((stateItem) => Array.isArray(stateItem.scene_ids) && stateItem.scene_ids.includes(shot.scene_id));
  const fallback = matched || states[0];
  if (!fallback) return "default visible state from character profile";
  return fallback.prompt || fallback.label || "default visible state from character profile";
}

function renderShots(preferredId = null) {
  el.shotList.innerHTML = "";
  state.shots.forEach((shot, index) => {
    const row = document.createElement("div");
    row.className = "shot-row";
    const checkbox = document.createElement("input");
    checkbox.className = "shot-check";
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedShotIds.has(shot.id);
    checkbox.title = `选择 ${shot.id} 用于批量生成`;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedShotIds.add(shot.id);
      } else {
        state.selectedShotIds.delete(shot.id);
      }
      saveWorkspaceDraft();
    });
    const button = document.createElement("button");
    button.className = "shot";
    button.type = "button";
    button.innerHTML = `
      <strong>${escapeHtml(shot.id)} · ${escapeHtml(shot.title)}</strong>
      <small>${escapeHtml((shot.characters || []).join("、") || "无明确角色")} · ${escapeHtml(shot.location)} · ${escapeHtml(shot.time)}</small>
      <small>${shot.image_url ? "已生成图片" : "未生成图片"}</small>
      <small>${escapeHtml(shot.visual_goal)}</small>
      <small>原文：${escapeHtml(shot.source_excerpt || shot.generation_description || "未绑定")}</small>
    `;
    button.addEventListener("click", () => selectShot(index));
    row.append(checkbox, button);
    el.shotList.append(row);
  });
  if (state.shots.length) {
    const index = Math.max(0, state.shots.findIndex((shot) => shot.id === preferredId));
    selectShot(index);
  }
}

function currentCharacterPayload() {
  return state.characters.map((character) => clone(character));
}

function applyCharacterResponse(data, message) {
  if (Array.isArray(data.characters)) {
    state.autoCharacters = data.characters.filter((character) => !character.manual);
    state.manualCharacters = data.characters.filter((character) => character.manual);
    composeCharacters();
    snapshotCurrentCharacters();
    renderCharacters();
    rebuildReferenceBindings();
  }
  if (data.difference_analysis) {
    state.differenceAnalysis = data.difference_analysis;
    renderCharacters();
  }
  saveWorkspaceDraft();
  el.health.textContent = message;
}

async function previewCharacters() {
  if (!el.charactersFile.files[0]) {
    el.health.textContent = "请先选择人物 Markdown";
    return;
  }
  el.health.textContent = "正在使用本地规则识别角色";
  const text = await el.charactersFile.files[0].text();
  const data = await api("/api/characters/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, use_llm: false }),
  });
  applyCharacterResponse(data, `识别到 ${state.characters.length} 个角色 · 本地规则`);
}

async function runCharacterLlmAction(path, body, successPrefix) {
  if (!el.charactersFile.files[0]) {
    el.health.textContent = "请先选择人物 Markdown";
    return;
  }
  if (path !== "/api/characters/llm/extract" && !state.characters.length) {
    el.health.textContent = "请先识别角色";
    return;
  }
  el.health.textContent = "正在请求 LLM";
  const data = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  applyCharacterResponse(data, data.llm_status || successPrefix);
}

async function runPromptBankAction() {
  if (!el.charactersFile.files[0]) {
    el.health.textContent = "请先选择人物 Markdown";
    return;
  }
  if (!state.characters.length) {
    el.health.textContent = "请先识别角色";
    return;
  }
  if (!el.referenceImages.files.length) {
    await runCharacterLlmAction(
      "/api/characters/llm/prompt-bank",
      { characters: currentCharacterPayload(), scenes: state.scenes, text: "" },
      "已生成角色 Prompt Bank"
    );
    return;
  }
  el.health.textContent = "正在先用 VLM 分析参考图，再生成 Prompt Bank";
  const form = new FormData();
  for (const file of el.referenceImages.files) {
    form.append("reference_images", file);
  }
  form.append("characters", JSON.stringify(currentCharacterPayload()));
  form.append("scenes", JSON.stringify(state.scenes));
  form.append("reference_bindings", JSON.stringify(serializeReferenceBindings()));
  const data = await api("/api/characters/llm/prompt-bank/references", { method: "POST", body: form });
  applyCharacterResponse(data, data.llm_status || "已生成角色 Prompt Bank");
}

async function runLocalPromptBankAction() {
  if (!el.charactersFile.files[0]) {
    el.health.textContent = "请先选择人物 Markdown";
    return;
  }
  if (!state.characters.length) {
    el.health.textContent = "请先识别角色";
    return;
  }
  el.health.textContent = "正在使用本地规则生成 Prompt Bank";
  const data = await api("/api/characters/prompt-bank/local", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ characters: currentCharacterPayload(), scenes: state.scenes, text: "" }),
  });
  applyCharacterResponse(data, data.llm_status || "已改用本地规则生成 Prompt Bank");
  rebuildAllPrompts(data.llm_status || "已改用本地规则生成 Prompt Bank，并已重建全部 prompt");
}

function addManualCharacter() {
  const name = el.manualCharacterName.value.trim();
  if (!name) {
    el.health.textContent = "请先填写角色名";
    return;
  }
  const role = el.manualCharacterRole.value.trim();
  const note = el.manualCharacterNote.value.trim();
  const card = {
    name,
    role,
    source_text: [role, note].filter(Boolean).join("\n\n"),
    manual: true,
    aliases: [],
    visual_traits: [],
    personality_traits: [],
    fixed_traits: [],
    variable_states: {},
    relationships: {},
    reference_images: [],
    reference_visuals: [],
    identity_prompt: role,
    negative_identity_prompt: "",
    appearance_states: [],
    prompt_cn: role || name,
    prompt_en: role || name,
  };
  const existingIndex = state.manualCharacters.findIndex((character) => character.name === name);
  if (existingIndex >= 0) {
    state.manualCharacters[existingIndex] = card;
    el.health.textContent = `已更新手动角色 ${name}`;
  } else {
    state.manualCharacters.push(card);
    el.health.textContent = `已添加手动角色 ${name}`;
  }
  composeCharacters();
  snapshotCurrentCharacters();
  renderCharacters();
  renderReferenceTable();
  saveWorkspaceDraft();
}

function rebuildReferenceBindings() {
  const previous = new Map();
  for (const item of state.referenceBindings) {
    const queue = previous.get(item.filename) || [];
    queue.push(item);
    previous.set(item.filename, queue);
  }
  state.referenceBindings = Array.from(el.referenceImages.files).map((file) => {
    const old = previous.get(file.name)?.shift();
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

async function loadNovelForRun() {
  if (!state.runId) return "";
  state.novelText = await storyboardClient.loadNovel(state.runId);
  saveWorkspaceDraft();
  return state.novelText;
}

function renderFeedbackHistory() {
  if (!el.feedbackHistory) return;
  const messages = Array.isArray(state.storyboardMessages) ? state.storyboardMessages : [];
  el.feedbackHistory.innerHTML = storyboardWorkspace.feedbackHistoryMarkup(messages, escapeHtml);
  el.feedbackHistory.scrollTop = el.feedbackHistory.scrollHeight;
}

function renderPromptFeedbackHistory() {
  if (!el.promptFeedbackHistory) return;
  const messages = Array.isArray(state.promptFeedbackMessages) ? state.promptFeedbackMessages : [];
  el.promptFeedbackHistory.innerHTML = storyboardWorkspace.feedbackHistoryMarkup(
    messages,
    escapeHtml,
    "Prompt LLM",
  );
  el.promptFeedbackHistory.scrollTop = el.promptFeedbackHistory.scrollHeight;
}

async function persistStoryboard({ quiet = false } = {}) {
  if (!state.runId) return;
  saveSelectedPrompt();
  saveShotEditor();
  const preferredId = state.selected?.id || null;
  const data = await storyboardClient.save(state.runId, state.shots);
  state.shots = data.shots || state.shots;
  state.storyboardMessages = data.storyboard_messages || state.storyboardMessages;
  state.promptFeedbackMessages = data.prompt_feedback_messages || state.promptFeedbackMessages;
  state.storyboardVersions = data.storyboard_versions || state.storyboardVersions;
  renderShots(preferredId);
  renderFeedbackHistory();
  renderPromptFeedbackHistory();
  saveWorkspaceDraft();
  if (!quiet) el.health.textContent = "分镜修改已保存到当前 run";
}

async function deleteSelectedShot() {
  if (!state.selected || !state.runId) return;
  const targetId = state.selected.id;
  if (!window.confirm(`确定删除 ${targetId}？已生成的图片文件仍会保留在 run 目录中。`)) return;
  saveSelectedPrompt();
  saveShotEditor();
  const index = state.shots.findIndex((shot) => shot.id === targetId);
  state.shots = state.shots.filter((shot) => shot.id !== targetId);
  state.selectedShotIds.delete(targetId);
  state.selected = state.shots[Math.min(index, state.shots.length - 1)] || null;
  await persistStoryboard({ quiet: true });
  renderShots(state.selected?.id);
  el.health.textContent = `${targetId} 已删除；图片文件未删除`;
}

async function openNovelDialog(mode = "browse") {
  if (!state.runId) {
    el.health.textContent = "请先生成或恢复一个分镜 run";
    return;
  }
  await novelSource.open(mode);
}

function updateNovelSelection() {
  novelSource.update();
}

function renderNovelSelection() {
  novelSource.render();
}

async function generateNewShot() {
  if (!state.runId) return;
  updateNovelSelection();
  const description = el.newShotDescription.value.trim();
  if (!state.novelSelection.text.trim() && !description) {
    el.novelSelectionStatus.textContent = "请先选择一段小说原文，或填写画面描述。";
    return;
  }
  setBusy(el.generateShotBtn, true);
  try {
    await persistStoryboard({ quiet: true });
    const sourceRef = state.novelSelection.text ? {
      version: 1,
      kind: "novel",
      document: "novel.md",
      start: state.novelSelection.start,
      end: state.novelSelection.end,
      quote: state.novelSelection.text,
      status: "exact",
    } : {
      version: 1,
      kind: "description",
      document: "",
      quote: description,
      status: "description",
    };
    const created = await storyboardClient.generateTask(state.runId, {
      source_ref: sourceRef,
      source_text: state.novelSelection.text,
      source_start: state.novelSelection.text ? state.novelSelection.start : null,
      source_end: state.novelSelection.text ? state.novelSelection.end : null,
      description,
      insert_after: state.selected?.id || null,
    });
    const data = await taskMonitor.wait(created.task_id);
    state.shots = data.shots || [...state.shots, data.shot];
    state.originalShots.push(clone(data.shot));
    el.novelDialog.close();
    renderShots(data.shot.id);
    saveWorkspaceDraft();
    el.health.textContent = `${data.shot.id} 已由 LLM 添加`;
  } finally {
    setBusy(el.generateShotBtn, false);
  }
}

async function sendStoryboardFeedback() {
  const content = el.feedbackInput.value.trim();
  if (!state.runId || !content) return;
  setBusy(el.sendFeedbackBtn, true);
  try {
    await persistStoryboard({ quiet: true });
    const created = await storyboardClient.feedbackTask(state.runId, content);
    const data = await taskMonitor.wait(created.task_id);
    const preferredId = state.selected?.id;
    state.shots = data.shots || state.shots;
    state.storyboardMessages = data.storyboard_messages || [];
    state.storyboardVersions = data.storyboard_versions || state.storyboardVersions;
    el.feedbackInput.value = "";
    renderShots(preferredId);
    renderFeedbackHistory();
    saveWorkspaceDraft();
    const regenerated = data.regenerated_shot_ids || [];
    el.health.textContent = storyboardWorkspace.feedbackOutcomeText(regenerated);
  } finally {
    setBusy(el.sendFeedbackBtn, false);
  }
}

async function savePromptFeedback() {
  const content = el.promptFeedbackInput.value.trim();
  if (!state.runId || !content) return;
  setBusy(el.savePromptFeedbackBtn, true);
  try {
    const data = await storyboardClient.promptFeedback(state.runId, content);
    state.promptFeedbackMessages = data.prompt_feedback_messages || [];
    el.promptFeedbackInput.value = "";
    renderPromptFeedbackHistory();
    saveWorkspaceDraft();
    el.health.textContent = "Prompt 重建意见已保存，只会用于生图 Prompt 的 LLM 重建";
  } finally {
    setBusy(el.savePromptFeedbackBtn, false);
  }
}

async function regenerateStoryboard(shotIds, button) {
  if (!state.runId || !shotIds.length) {
    el.health.textContent = "请先勾选要重新生成的分镜";
    return;
  }
  setBusy(button, true);
  const preferredId = state.selected?.id;
  try {
    await persistStoryboard({ quiet: true });
    const created = await storyboardClient.regenerateTask(state.runId, shotIds);
    const data = await taskMonitor.wait(created.task_id);
    state.shots = data.shots || state.shots;
    state.storyboardMessages = data.storyboard_messages || state.storyboardMessages;
    state.storyboardVersions = data.storyboard_versions || state.storyboardVersions;
    renderShots(preferredId);
    renderFeedbackHistory();
    saveWorkspaceDraft();
    el.health.textContent = `已重新生成 ${shotIds.length} 条分镜，原有图片全部保留`;
  } finally {
    setBusy(button, false);
  }
}

async function runPipeline() {
  const inputError = validateInputFiles();
  if (inputError) {
    el.health.textContent = inputError;
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
    form.append("manual_characters", JSON.stringify(state.manualCharacters));
    form.append("prepared_characters", JSON.stringify(currentCharacterPayload()));
    form.append("max_shots", el.maxShots.value);
    form.append("use_llm", el.useLlm.checked ? "true" : "false");
    form.append("llm_profile", el.llmProfile?.value || "fast");
    form.append("llm_concurrency", el.llmConcurrency?.value || "3");
    const { created } = await taskMonitor.submit("/api/pipeline/task", { method: "POST", body: form });
    const data = await api(`/api/runs/${encodeURIComponent(created.run_id)}`);
    state.runId = data.run_id;
    state.shots = data.shots || [];
    state.scenes = data.scenes || [];
    state.novelText = storyboardWorkspace.normalizeNovelText(await el.novelFile.files[0].text());
    state.storyboardMessages = data.storyboard_messages || [];
    state.promptFeedbackMessages = data.prompt_feedback_messages || [];
    state.storyboardVersions = data.storyboard_versions || {};
    const partitioned = partitionCharacters(data.characters || []);
    state.autoCharacters = partitioned.auto;
    state.manualCharacters = partitioned.manual;
    composeCharacters();
    state.originalShots = clone(state.shots);
    snapshotCurrentCharacters();
    state.differenceAnalysis = data.difference_analysis || null;
    el.runId.textContent = `run ${state.runId}`;
    renderCharacters();
    renderFeedbackHistory();
    renderPromptFeedbackHistory();
    renderShots(state.selected?.id);
    saveWorkspaceDraft();
    el.health.textContent = `已生成 ${state.shots.length} 张分镜`;
  } catch (error) {
    el.health.textContent = error.message;
  } finally {
    setBusy(el.runBtn, false);
  }
}

async function exportMarkdown() {
  if (!state.runId) return;
  saveSelectedPrompt();
  saveCharacterEditor();
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

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

function kindLabel(kind) {
  return { llm: "LLM", image: "图片", vlm: "VLM" }[kind] || kind;
}

function togglePanel(panel, button, openText, closedText) {
  panel.hidden = !panel.hidden;
  button.textContent = panel.hidden ? closedText : openText;
}

el.runBtn.addEventListener("click", runPipeline);
el.novelFile.addEventListener("change", () => {
  const file = el.novelFile.files[0];
  clearRunArtifacts(file ? `已选择新小说 ${selectedFileLabel(file)}，请重新生成分镜` : "已清空小说文件");
});
el.charactersFile.addEventListener("change", () => {
  const file = el.charactersFile.files[0];
  clearRunArtifacts(file ? `已选择新人设 ${selectedFileLabel(file)}，正在重新识别角色` : "已清空人设文件");
  previewCharacters().catch((error) => {
    el.health.textContent = error.message;
  });
});
el.referenceImages.addEventListener("change", rebuildReferenceBindings);
el.previewCharactersBtn.addEventListener("click", () => previewCharacters().catch((error) => {
  el.health.textContent = error.message;
}));
el.llmExtractCharactersBtn.addEventListener("click", async () => {
  try {
    if (!el.charactersFile.files[0]) {
      el.health.textContent = "请先选择人物 Markdown";
      return;
    }
    const text = await el.charactersFile.files[0].text();
    await runCharacterLlmAction("/api/characters/llm/extract", { text }, "已完成 LLM 拆分人设");
  } catch (error) {
    el.health.textContent = error.message;
  }
});
el.llmEnhanceCharactersBtn.addEventListener("click", () => runCharacterLlmAction(
  "/api/characters/llm/enhance",
  { characters: currentCharacterPayload() },
  "已完成 LLM 增强人设"
).catch((error) => {
  el.health.textContent = error.message;
}));
el.llmPromptBankBtn.addEventListener("click", () => runPromptBankAction().catch((error) => {
  el.health.textContent = error.message;
}));
el.localPromptBankBtn.addEventListener("click", () => runLocalPromptBankAction().catch((error) => {
  el.health.textContent = error.message;
}));
el.llmDiffBtn.addEventListener("click", () => runCharacterLlmAction(
  "/api/characters/llm/diff",
  { characters: currentCharacterPayload() },
  "已完成 LLM 差异分析"
).catch((error) => {
  el.health.textContent = error.message;
}));
el.manualCharacterToggleBtn.addEventListener("click", () => {
  togglePanel(el.manualCharacterPanel, el.manualCharacterToggleBtn, "收起手动添加", "手动添加角色");
});
el.addManualCharacterBtn.addEventListener("click", addManualCharacter);
el.llmModeHelpToggleBtn.addEventListener("click", () => {
  togglePanel(el.llmModeHelpPanel, el.llmModeHelpToggleBtn, "收起 LLM 模式说明", "查看 LLM 模式说明");
});
el.rulesToggleBtn.addEventListener("click", () => {
  togglePanel(el.rulesPanel, el.rulesToggleBtn, "收起本地规则", "查看本地规则");
});
el.configToggle.addEventListener("click", () => {
  el.configPanel.hidden = !el.configPanel.hidden;
});
if (el.cleanStartBtn) {
  el.cleanStartBtn.addEventListener("click", () => {
    clearWorkspaceForRecording();
    const cleanUrl = `${window.location.pathname}?clean=1`;
    window.history.replaceState(null, "", cleanUrl);
  });
}
el.restoreRunBtn.addEventListener("click", () => restoreLatestRun().catch((error) => {
  el.health.textContent = `恢复失败：${error.message}`;
}));
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
el.providerType.addEventListener("change", () => {
  const source = findProvider();
  const knownCloudDefaults = [
    "https://api.openai.com/v1",
    "https://api.siliconflow.cn/v1",
    "https://ark.cn-beijing.volces.com/api/v3",
  ];
  if (el.providerType.value === "comfyui" && source?.provider !== "comfyui" && (!el.providerBaseUrl.value || knownCloudDefaults.includes(el.providerBaseUrl.value))) {
    el.providerBaseUrl.value = "http://127.0.0.1:8188";
    el.providerKey.value = "";
  }
  renderProviderBaseUrlField(el.providerType.value);
});
for (const node of [el.providerKind, el.providerType, el.providerActive, el.providerLabel, el.providerBaseUrl, el.providerKey, el.imageSteps, el.imageGuidance, el.imageBatch, el.imageSequential, el.imageResponseFormat, el.imageWatermark, el.comfyWorkflow, el.comfyNegativePrompt, el.comfyOutputNode, el.comfyPollInterval]) {
  node.addEventListener("input", () => {
    syncProviderForm();
    renderProviderList();
    el.imageOptions.hidden = findProvider()?.kind !== "image";
    el.comfyOptions.hidden = findProvider()?.kind !== "image" || findProvider()?.provider !== "comfyui";
  });
  node.addEventListener("change", () => {
    syncProviderForm();
    renderProviderList();
    el.imageOptions.hidden = findProvider()?.kind !== "image";
    el.comfyOptions.hidden = findProvider()?.kind !== "image" || findProvider()?.provider !== "comfyui";
  });
}
el.comfyWorkflowFile.addEventListener("change", async () => {
  const file = el.comfyWorkflowFile.files[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const workflow = data?.prompt && typeof data.prompt === "object" ? data.prompt : data;
    el.comfyWorkflow.value = JSON.stringify(workflow, null, 2);
    syncProviderForm();
    el.providerTestResult.textContent = `已导入 ${file.name}`;
  } catch (error) {
    el.providerTestResult.textContent = `工作流 JSON 无效：${error.message}`;
  }
});
el.saveConfigBtn.addEventListener("click", saveProviders);
el.refreshConfigBtn.addEventListener("click", async () => {
  await loadConfig();
  await checkHealth();
});
el.testProviderBtn.addEventListener("click", testProvider);
el.promptBox.addEventListener("input", () => {
  saveSelectedPrompt();
  scheduleWorkspaceDraftSave();
});
el.negativePromptBox.addEventListener("input", () => {
  saveSelectedPrompt();
  scheduleWorkspaceDraftSave();
});
for (const node of [el.shotTitle, el.shotLocation, el.shotTime, el.shotCharacters, el.shotMood, el.shotCamera, el.shotComposition, el.shotVisualGoal]) {
  node.addEventListener("input", () => {
    saveShotEditor();
    scheduleWorkspaceDraftSave();
  });
}

el.characterEditorSelect.addEventListener("change", () => {
  saveCharacterEditor();
  state.selectedCharacterIndex = Number(el.characterEditorSelect.value || 0);
  loadCharacterEditor();
});
for (const node of [el.identityPromptBox, el.appearanceStatesBox, el.negativeIdentityPromptBox]) {
  node.addEventListener("input", () => {
    saveCharacterEditor();
    saveWorkspaceDraft();
  });
}
el.restorePromptBtn.addEventListener("click", restoreSelectedPrompt);
el.rebuildPromptBtn.addEventListener("click", rebuildSelectedPrompt);
el.llmPromptBtn.addEventListener("click", () => regenerateSelectedPromptWithLlm().catch((error) => {
  el.health.textContent = `LLM Prompt 重建失败：${error.message}`;
}));
el.savePromptFeedbackBtn.addEventListener("click", () => savePromptFeedback().catch((error) => {
  el.health.textContent = `保存 Prompt 意见失败：${error.message}`;
}));
el.promptFeedbackInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    el.savePromptFeedbackBtn.click();
  }
});
el.restoreCharacterBtn.addEventListener("click", restoreSelectedCharacter);
el.rebuildAllPromptsBtn.addEventListener("click", rebuildAllPrompts);
el.imageBtn.addEventListener("click", imageWorkflow.generateCurrent);
el.selectedImagesBtn.addEventListener("click", imageWorkflow.generateSelected);
el.allImagesBtn.addEventListener("click", imageWorkflow.generateAll);
el.retryFailedBtn.addEventListener("click", imageWorkflow.retryFailed);
el.exportBtn.addEventListener("click", exportMarkdown);
el.copyBtn.addEventListener("click", async () => {
  saveSelectedPrompt();
  await navigator.clipboard.writeText(el.promptBox.value);
  el.health.textContent = "Prompt 已复制";
});
el.openNovelBtn.addEventListener("click", () => openNovelDialog("locate").catch((error) => {
  el.health.textContent = error.message;
}));
el.addShotBtn.addEventListener("click", () => openNovelDialog("add").catch((error) => {
  el.health.textContent = error.message;
}));
el.locateSourceBtn.addEventListener("click", () => openNovelDialog("locate").catch((error) => {
  el.health.textContent = error.message;
}));
el.closeNovelBtn.addEventListener("click", () => el.novelDialog.close());
el.novelDialog.addEventListener("close", novelSource.close);
el.novelText.addEventListener("select", updateNovelSelection);
el.novelText.addEventListener("mouseup", updateNovelSelection);
el.novelText.addEventListener("keyup", updateNovelSelection);
el.clearNovelSelectionBtn.addEventListener("click", () => {
  novelSource.clear();
});
el.generateShotBtn.addEventListener("click", () => generateNewShot().catch((error) => {
  el.health.textContent = error.message;
}));
el.saveShotBtn.addEventListener("click", () => persistStoryboard().catch((error) => {
  el.health.textContent = `保存失败：${error.message}`;
}));
el.deleteShotBtn.addEventListener("click", () => deleteSelectedShot().catch((error) => {
  el.health.textContent = `删除失败：${error.message}`;
}));
el.sendFeedbackBtn.addEventListener("click", () => sendStoryboardFeedback().catch((error) => {
  el.health.textContent = error.message;
}));
el.regenerateSelectedBtn.addEventListener("click", () => regenerateStoryboard(
  state.shots.filter((shot) => state.selectedShotIds.has(shot.id)).map((shot) => shot.id),
  el.regenerateSelectedBtn,
).catch((error) => {
  el.health.textContent = error.message;
}));
el.regenerateAllBtn.addEventListener("click", () => regenerateStoryboard(
  state.shots.map((shot) => shot.id),
  el.regenerateAllBtn,
).catch((error) => {
  el.health.textContent = error.message;
}));
el.feedbackInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    el.sendFeedbackBtn.click();
  }
});

window.addEventListener("beforeunload", saveWorkspaceDraft);

loadConfig().catch((error) => {
  el.health.textContent = error.message;
});
checkHealth().then(() => {
  if (cleanStartRequested()) {
    clearWorkspaceForRecording();
    return;
  }
  if (!restoreWorkspaceDraft()) {
    restoreLatestRun().catch(() => {});
  }
});
