(function initVisualPresets(global) {
  const KINDS = ["style", "composition"];
  const LABELS = { style: "画风", composition: "构图" };
  const DRAFT_KEY = "ficframe.visual-preset-draft.v1";
  const PROBE_KEY = "ficframe.image-reference-test.v1";
  const FIELDS = {
    style: ["stylization", "proportions", "linework", "rendering", "color", "lighting", "materials", "background", "summary"],
    composition: ["shot", "viewpoint", "subject_placement", "whitespace", "visual_weight", "relationships", "background_ratio", "summary"],
  };

  function referenceUrl(path) {
    const parts = String(path || "").replace(/\\/g, "/").split("/");
    return parts.length === 3 && ["drafts", "references"].includes(parts[0]) && parts.every((part) => part && ![".", ".."].includes(part))
      ? `/api/visual-presets/reference/${parts.map(encodeURIComponent).join("/")}` : "";
  }

  function options(presets, kind, selected, snapshot, modes, escapeHtml) {
    const base = modes ? '<option value="inherit">沿用 run 默认</option><option value="none">不使用</option>' : '<option value="">不使用</option>';
    let items = presets.filter((item) => item.type === kind).map((item) => {
      const bound = item.id === selected && snapshot?.id === selected && snapshot.version !== item.version;
      const version = bound ? `绑定 v${snapshot.version} · 最新 v${item.version}` : `v${item.version}`;
      return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${version}</option>`;
    }).join("");
    if (selected && !["inherit", "none"].includes(selected) && !presets.some((item) => item.id === selected)) {
      items += `<option value="${escapeHtml(selected)}">${escapeHtml(snapshot?.name || selected)} · 已删除，保留绑定版本</option>`;
    }
    return base + items;
  }

  function snapshotText(snapshot, kinds = ["style"]) {
    return kinds.map((kind) => {
      const item = snapshot?.[kind];
      return item?.id ? `${LABELS[kind]}：${item.name || item.id} v${item.version || 1}\n模式：${item.reference_mode === "image" ? `原图参考＋文本（${item.reference_images?.length || 0} 张）` : "仅文本"}\n正向：${item.positive || "（空）"}\n负向：${item.negative || "（无）"}` : `${LABELS[kind]}：不使用`;
    }).join("\n\n");
  }

  function createController({ state, elements: el, api, taskMonitor, escapeHtml, setBusy, storage,
                              saveWorkspaceDraft, persistStoryboard, selectedImageSize = () => "1024x1024",
                              enabledKinds = ["style"] }) {
    let activeKinds = KINDS.filter((kind) => enabledKinds.includes(kind));
    state.visualPresetKinds = activeKinds;
    let pending = null;
    let queue = Promise.resolve();
    let defaultsRevision = 0;
    let previewSequence = 0;
    let capabilitySequence = 0;
    let previewTimer;
    let busy = false;
    let testing = false;
    let editingAnalysis = false;
    const json = (path, body, method = "POST") => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    function report(error) { el.health.textContent = error.message || String(error); }
    function enqueue(action) {
      const work = queue.catch(() => {}).then(action);
      queue = work;
      work.catch(report);
      return work;
    }
    function persistDraft() {
      if (!storage) return;
      try {
        if (pending) storage.setItem(DRAFT_KEY, JSON.stringify(pending));
        else storage.removeItem(DRAFT_KEY);
      } catch (_) { el.visualPresetDraftState.textContent = "浏览器草稿存储不可用，请先确认保存。"; }
    }
    function draftImages(paths) {
      return (paths || []).map((path) => {
        const url = referenceUrl(path);
        return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener"><img src="${escapeHtml(url)}" alt="视觉规范参考图" /></a>` : "";
      }).join("");
    }
    function renderSelectors() {
      el.compositionFeatures?.forEach((node) => { node.hidden = !activeKinds.includes("composition"); });
      for (const kind of activeKinds) {
        const selector = kind === "style" ? el.runStylePreset : el.runCompositionPreset;
        const defaults = state.visualPresetDefaults || {};
        const id = defaults[`${kind}_id`] || "";
        selector.innerHTML = options(state.visualPresets || [], kind, id, state.runId ? defaults[`${kind}_snapshot`] : null, false, escapeHtml);
        selector.value = id;
        selector.disabled = false;
        const modeSelector = kind === "style" ? el.runStyleReferenceMode : el.runCompositionReferenceMode;
        modeSelector.value = defaults[`${kind}_reference_mode`] || "text";
        modeSelector.disabled = false;
      }
      loadShot();
      const items = (state.visualPresets || []).filter((item) => activeKinds.includes(item.type));
      el.visualPresetStatus.innerHTML = items.length ? items.map((item) => `<div class="visual-preset-row"><span>${escapeHtml(item.name)} · ${LABELS[item.type]} · v${item.version}</span><span class="visual-preset-actions"><button type="button" data-visual-edit="${escapeHtml(item.id)}">编辑</button><button type="button" data-visual-delete="${escapeHtml(item.id)}">删除</button></span><div class="visual-preset-references">${draftImages(item.reference_images)}</div></div>`).join("") : "尚无预设，可手动创建或上传参考图。";
      el.visualPresetStatus.querySelectorAll("[data-visual-edit]").forEach((button) => button.addEventListener("click", () => openEditor(state.visualPresets.find((item) => item.id === button.dataset.visualEdit))));
      el.visualPresetStatus.querySelectorAll("[data-visual-delete]").forEach((button) => button.addEventListener("click", () => remove(button.dataset.visualDelete).catch(report)));
      renderSnapshot();
    }
    function loadShot() {
      for (const kind of activeKinds) {
        const selector = kind === "style" ? el.shotStylePreset : el.shotCompositionPreset;
        const shot = state.selected;
        const mode = shot?.[`${kind}_preset_mode`] || "inherit";
        const value = mode === "preset" ? shot?.[`${kind}_preset_id`] : mode;
        selector.innerHTML = options(state.visualPresets || [], kind, value, shot?.[`${kind}_preset_snapshot`], true, escapeHtml);
        selector.value = value || "inherit";
        selector.disabled = !shot;
        const modeSelector = kind === "style" ? el.shotStyleReferenceMode : el.shotCompositionReferenceMode;
        modeSelector.value = shot?.[`${kind}_reference_mode`] || "inherit";
        modeSelector.disabled = !shot;
      }
      el.adoptShotVisualPresetsBtn.disabled = !state.selected || !state.runId;
      el.adoptRunVisualPresetsBtn.disabled = !state.runId;
      schedulePreview();
    }
    function saveShot() {
      if (!state.selected) return;
      for (const kind of activeKinds) {
        const selector = kind === "style" ? el.shotStylePreset : el.shotCompositionPreset;
        const value = selector.value || "inherit";
        state.selected[`${kind}_preset_mode`] = ["inherit", "none"].includes(value) ? value : "preset";
        state.selected[`${kind}_preset_id`] = ["inherit", "none"].includes(value) ? null : value;
        const modeSelector = kind === "style" ? el.shotStyleReferenceMode : el.shotCompositionReferenceMode;
        state.selected[`${kind}_reference_mode`] = modeSelector.value || "inherit";
      }
    }
    function renderSnapshot() {
      const shot = state.selected;
      const versions = shot?.image_versions || [];
      const version = versions.find((item) => String(item.image_url || "").split("?")[0] === String(shot?.image_url || "").split("?")[0]);
      const candidate = version?.visual_preset_snapshot || (versions.length ? null : shot?.last_generation_visual_snapshot);
      const snapshot = (shot?.image_url || shot?.image_path) && candidate && Object.keys(candidate).length ? candidate : null;
      el.visualPromptSnapshot.textContent = snapshot ? `当前图片实际规范\n${snapshotText(snapshot, activeKinds)}` : "当前图片暂无规范记录（旧图片或尚未生成）";
    }
    async function preview() {
      const sequence = ++previewSequence;
      const shot = state.selected;
      if (el.promptStyleWarning && (!shot || !state.runId)) el.promptStyleWarning.hidden = true;
      if (!shot || !state.runId) { el.visualPresetEffective.textContent = "选择分镜后查看实际规范"; el.visualFinalPrompt.value = ""; el.visualFinalNegative.value = ""; el.visualReferenceWarning.hidden = true; return; }
      const id = shot.id;
      try {
        const data = await json(`/api/runs/${encodeURIComponent(state.runId)}/visual-preview`, { shot, size: selectedImageSize() });
        if (sequence !== previewSequence || state.selected?.id !== id) return;
        el.visualPresetEffective.textContent = snapshotText(data.visual_preset_snapshot, activeKinds);
        if (el.promptStyleWarning) {
          el.promptStyleWarning.textContent = data.prompt_style_message || "";
          el.promptStyleWarning.hidden = !data.prompt_style_pending;
        }
        el.visualFinalPrompt.value = data.positive_prompt;
        el.visualFinalNegative.value = data.negative_prompt;
        if (data.reference_preflight) showReferenceWarning(data.reference_preflight);
      } catch (error) { if (sequence === previewSequence) el.visualPresetEffective.textContent = `规范预览失败：${error.message}`; }
    }
    function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(preview, 180); }
    async function refresh() {
      el.visualPresetStatus.textContent = "正在加载预设…";
      try {
        const data = await api("/api/visual-presets");
        if (Array.isArray(data.enabled_types)) activeKinds = KINDS.filter((kind) => data.enabled_types.includes(kind));
        state.visualPresetKinds = activeKinds;
        state.visualPresets = (data.presets || []).filter((item) => activeKinds.includes(item.type));
        renderSelectors();
      } catch (error) { el.visualPresetStatus.textContent = `预设加载失败：${error.message}`; throw error; }
    }
    function applyDefaults(data) {
      state.visualPresetDefaults = data.visual_presets;
      for (const saved of data.shots || []) {
        const shot = state.shots.find((item) => item.id === saved.id);
        if (shot) {
          for (const kind of activeKinds) shot[`${kind}_preset_snapshot`] = saved[`${kind}_preset_snapshot`];
          shot.prompt_style_snapshot = saved.prompt_style_snapshot;
        }
      }
      renderSelectors();
      saveWorkspaceDraft();
    }
    function saveDefaults(refreshVersion = false) {
      const runId = state.runId;
      const selected = { ...state.visualPresetDefaults };
      const revision = ++defaultsRevision;
      return enqueue(async () => {
        if (!runId) { saveWorkspaceDraft(); return; }
        const selections = Object.fromEntries(activeKinds.flatMap((kind) => [[`${kind}_id`, selected[`${kind}_id`]], [`${kind}_reference_mode`, selected[`${kind}_reference_mode`]]]));
        const data = await json(`/api/runs/${encodeURIComponent(runId)}/visual-presets`, { run_id: runId, ...selections, refresh: refreshVersion });
        if (state.runId === runId && revision === defaultsRevision) applyDefaults(data);
      });
    }
    async function adoptShot() {
      await flush();
      if (!state.selected || !state.runId) return;
      const runId = state.runId;
      const shot = state.selected;
      const data = await json(`/api/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shot.id)}/visual-presets`, { shot, refresh: true });
      if (state.runId !== runId) return;
      const current = state.shots.find((item) => item.id === shot.id);
      if (current) current.prompt_style_snapshot = data.shot.prompt_style_snapshot;
      if (current) for (const kind of activeKinds) {
        if (current[`${kind}_preset_mode`] === data.shot[`${kind}_preset_mode`] && current[`${kind}_preset_id`] === data.shot[`${kind}_preset_id`] && (current[`${kind}_reference_mode`] || "inherit") === (data.shot[`${kind}_reference_mode`] || "inherit")) current[`${kind}_preset_snapshot`] = data.shot[`${kind}_preset_snapshot`];
      }
      saveWorkspaceDraft();
      await preview();
      el.health.textContent = "此分镜已采用指定预设的最新版；继承项仍使用 run 绑定版本";
    }
    function saveSelection() {
      const runId = state.runId;
      const shot = { ...state.selected };
      return enqueue(async () => {
        if (!runId || !shot.id) return;
        const data = await json(`/api/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shot.id)}/visual-presets`, { shot });
        if (state.runId !== runId) return;
        const current = state.shots.find((item) => item.id === shot.id);
        if (current) current.prompt_style_snapshot = data.shot.prompt_style_snapshot;
        if (current) for (const kind of activeKinds) {
          if (current[`${kind}_preset_mode`] === shot[`${kind}_preset_mode`] && current[`${kind}_preset_id`] === shot[`${kind}_preset_id`] && (current[`${kind}_reference_mode`] || "inherit") === (shot[`${kind}_reference_mode`] || "inherit")) current[`${kind}_preset_snapshot`] = data.shot[`${kind}_preset_snapshot`];
        }
        saveWorkspaceDraft(); schedulePreview();
      });
    }
    function openEditor(item = null, kind = "style", draft = {}) {
      if (!activeKinds.includes(item?.type || kind)) return;
      pending = item ? { kind: item.type, mode: "edit", id: item.id, draft: { ...item, reference_paths: item.reference_images || [] } } : { kind, mode: "create", draft: { ...draft } };
      renderEditor();
      persistDraft();
    }
    function renderEditor() {
      if (!pending) return;
      const { kind, draft, mode } = pending;
      el.visualPresetDialogTitle.textContent = `${mode === "edit" ? "编辑" : "新建"}${LABELS[kind]}预设`;
      el.visualPresetName.value = draft.name || "";
      el.visualPresetPositive.value = draft.positive || "";
      el.visualPresetNegative.value = draft.negative || "";
      el.visualPresetReferenceMode.value = draft.reference_mode || "text";
      el.visualPresetReferenceFiles.value = "";
      el.visualPresetStructured.value = draft.structured_text ?? JSON.stringify(draft.structured || draft.vlm_analysis?.structured || {}, null, 2);
      el.visualPresetDraftState.textContent = draft.status === "vlm_not_configured" ? "未配置 VLM；参考图已保留，可手动填写。" : draft.status === "vlm_failed" ? draft.error : draft.status === "analyzed" ? "分析草稿已就绪，请检查后确认保存。" : "填写规范后确认保存；已绑定的版本和历史图片保持原规范。";
      el.visualPresetDraftImages.innerHTML = draftImages(draft.reference_paths);
      if (!el.visualPresetDialog.open) el.visualPresetDialog.showModal();
    }
    function readEditor() {
      if (!pending) return;
      if (!pending.draft) return;
      Object.assign(pending.draft, { name: el.visualPresetName.value, positive: el.visualPresetPositive.value, negative: el.visualPresetNegative.value, structured_text: el.visualPresetStructured.value, reference_mode: el.visualPresetReferenceMode.value || "text" });
      try { pending.draft.structured = JSON.parse(el.visualPresetStructured.value || "{}"); } catch (_) { /* Preserve invalid edits for correction. */ }
      persistDraft();
    }
    async function saveEditor(event) {
      event.preventDefault();
      if (!pending) return;
      if (editingAnalysis) throw new Error("参考图正在上传或分析，请等待完成。");
      if (el.visualPresetReferenceFiles.files?.length) throw new Error("已选择图片尚未上传，请先点击上传或分析。");
      readEditor();
      const structured = JSON.parse(el.visualPresetStructured.value || "{}");
      if (!structured || Array.isArray(structured) || typeof structured !== "object") throw new Error("结构化分析应为 JSON 对象");
      const name = pending.draft.name?.trim();
      if (!name) throw new Error("请填写预设名称");
      const { kind, draft, mode, id } = pending;
      const cleanStructured = Object.fromEntries(Object.entries(structured).filter(([key]) => FIELDS[kind].includes(key)));
      if (draft.reference_mode === "image" && !draft.reference_paths?.length) throw new Error("原图参考模式需要上传至少一张参考图。");
      const values = { name, positive: draft.positive, negative: draft.negative, reference_mode: draft.reference_mode || "text", vlm_analysis: { positive: draft.positive, negative: draft.negative, structured: cleanStructured } };
      values.reference_paths = draft.reference_paths || [];
      setBusy(el.saveVisualPresetBtn, true);
      try {
        const saved = await json(mode === "edit" ? `/api/visual-presets/${encodeURIComponent(id)}` : "/api/visual-presets", mode === "edit" ? values : { ...values, type: kind }, mode === "edit" ? "PATCH" : "POST");
        pending = null; persistDraft(); el.visualPresetDialog.close();
        await refresh(); el.health.textContent = mode === "edit" && saved.version === draft.version
          ? `内容未修改，保留 v${saved.version}。` : "预设已保存；可在 run 或分镜中选择应用";
      } finally { setBusy(el.saveVisualPresetBtn, false); }
    }
    async function remove(id) {
      if (!global.confirm("删除全局预设？已绑定版本、生成历史与参考图会保留。")) return;
      await api(`/api/visual-presets/${encodeURIComponent(id)}`, { method: "DELETE" });
      await refresh(); saveWorkspaceDraft();
    }
    async function finishAnalysis(kind, taskId) {
      const draft = await taskMonitor.wait(taskId);
      openEditor(null, kind, draft);
    }
    async function analyze(kind) {
      if (!activeKinds.includes(kind)) return;
      if (busy) return;
      const input = kind === "style" ? el.stylePresetImages : el.compositionPresetImages;
      if (!input.files?.length) throw new Error("请选择 1 至 8 张参考图");
      if (input.files.length > 8) throw new Error("最多支持 8 张参考图");
      if ([...input.files].some((file) => file.size > 20 * 1024 * 1024)) throw new Error("单张参考图不能超过 20 MB");
      const form = new FormData(); form.append("preset_type", kind);
      for (const file of input.files) form.append("reference_images", file);
      busy = true; setBusy(el.analyzeStylePresetBtn, true); setBusy(el.analyzeCompositionPresetBtn, true);
      try {
        const created = await api("/api/visual-presets/analyze-task", { method: "POST", body: form });
        pending = { kind, task_id: created.task_id }; persistDraft();
        await finishAnalysis(kind, created.task_id);
      } finally { busy = false; setBusy(el.analyzeStylePresetBtn, false); setBusy(el.analyzeCompositionPresetBtn, false); }
    }
    async function resume() {
      let draft;
      try { draft = JSON.parse(storage?.getItem(DRAFT_KEY) || "null"); } catch (_) { return; }
      if (!draft || !activeKinds.includes(draft.kind)) return;
      if (busy) return;
      pending = draft;
      if (draft.analysis_task_id && draft.draft) {
        editingAnalysis = true; renderEditor(); setBusy(el.saveVisualPresetBtn, true);
        try {
          const result = await taskMonitor.wait(draft.analysis_task_id);
          if (pending === draft) { readEditor(); applyAnalysisSuggestion(draft, result); renderEditor(); persistDraft(); }
        } finally { editingAnalysis = false; setBusy(el.saveVisualPresetBtn, false); }
        return;
      }
      if (draft.task_id) {
        busy = true; setBusy(el.analyzeStylePresetBtn, true); setBusy(el.analyzeCompositionPresetBtn, true);
        try { await finishAnalysis(draft.kind, draft.task_id); }
        finally { busy = false; setBusy(el.analyzeStylePresetBtn, false); setBusy(el.analyzeCompositionPresetBtn, false); }
      }
      else if (draft.draft) renderEditor();
    }
    async function flush() { await queue; }
    async function preflight(ids) {
      if (!state.runId) return [];
      const shots = state.shots.filter((shot) => !ids || ids.includes(shot.id));
      const results = [];
      for (const shot of shots) {
        const data = await json(`/api/runs/${encodeURIComponent(state.runId)}/visual-preview`, { shot, size: selectedImageSize() });
        results.push({ shot, check: data.reference_preflight });
      }
      return results;
    }
    async function prepareGeneration(ids) {
      await flush(); await persistStoryboard({ quiet: true });
      const checks = await preflight(ids);
      const invalid = checks.find((item) => item.check && !item.check.ok);
      if (invalid) {
        showReferenceWarning(invalid.check);
        throw new Error(`${invalid.shot.id}：${invalid.check.message} 不会自动丢弃原图；请调整参考模式。`);
      }
      el.visualReferenceWarning.hidden = true;
    }
    function showReferenceWarning(check) {
      el.visualReferenceWarning.textContent = check.message;
      el.visualReferenceWarning.hidden = check.ok;
    }
    async function refreshCapability() {
      const sequence = ++capabilitySequence;
      const data = await api(`/api/image-reference-capability?size=${encodeURIComponent(selectedImageSize())}`);
      if (sequence === capabilitySequence) el.imageReferenceCapability.textContent = `${data.model || "图片模型"}：${data.message}`;
      return data;
    }
    async function resumeProbe() {
      let saved;
      try { saved = JSON.parse(storage?.getItem(PROBE_KEY) || "null"); } catch (_) { return false; }
      if (!saved?.task_id || testing) return false;
      testing = true; setBusy(el.testImageReferencesBtn, true);
      try {
        const result = await taskMonitor.wait(saved.task_id);
        storage?.removeItem(PROBE_KEY);
        await refreshCapability(); await preview();
        el.health.textContent = `多图参考测试：${result.message}`;
        return true;
      } catch (error) {
        const task = await api(`/api/tasks/${encodeURIComponent(saved.task_id)}`).catch(() => null);
        if (task && ["failed", "cancelled"].includes(task.status)) storage?.removeItem(PROBE_KEY);
        el.imageReferenceCapability.textContent = `测试状态获取失败：${error.message}；可再次点击测试按钮恢复。`;
        throw error;
      } finally { testing = false; setBusy(el.testImageReferencesBtn, false); }
    }
    async function testReferences() {
      if (testing) return;
      if (await resumeProbe()) return;
      if (testing) return;
      testing = true; setBusy(el.testImageReferencesBtn, true);
      try {
        await flush();
        const checks = await preflight();
        const count = Math.max(2, ...checks.map((item) => item.check?.total_count || 0));
        if (count > 32) throw new Error("本次参考图超过 32 张测试上限，请减少图片。");
        const current = await refreshCapability();
        if (current.adapter_supported === false) throw new Error(current.message);
        if (!global.confirm(`将向当前已保存图片供应商（${current.provider} / ${current.model}）发送 ${count} 张内置色块，并实际生成一张测试图，可能产生费用。不会上传用户小说或参考图。是否测试？`)) return;
        el.imageReferenceCapability.textContent = "正在测试多图参考…";
        const created = await json("/api/image-reference-test-task", { confirmed: true, reference_count: count, size: selectedImageSize() });
        try { storage?.setItem(PROBE_KEY, JSON.stringify({ task_id: created.task_id })); }
        catch (_) { el.health.textContent = "测试已启动，但浏览器无法保留任务 ID；刷新后请查询能力状态。"; }
        const result = await taskMonitor.wait(created.task_id);
        storage?.removeItem(PROBE_KEY);
        el.imageReferenceCapability.textContent = result.message;
        await preview();
      } finally { testing = false; setBusy(el.testImageReferencesBtn, false); }
    }
    async function editorReferences(analyzeImages = false) {
      if (!pending || editingAnalysis) return;
      const files = el.visualPresetReferenceFiles.files;
      if (!files?.length || files.length > 8) throw new Error("请选择 1 至 8 张参考图。");
      if ([...files].some((file) => file.size > 20 * 1024 * 1024)) throw new Error("单张参考图不能超过 20 MB。");
      readEditor();
      const editor = pending;
      const form = new FormData(); form.append("preset_type", editor.kind);
      for (const file of files) form.append("reference_images", file);
      editingAnalysis = true; setBusy(el.saveVisualPresetBtn, true);
      setBusy(el.uploadVisualPresetReferencesBtn, true); setBusy(el.analyzeEditorReferencesBtn, true);
      el.visualPresetDraftState.textContent = analyzeImages ? "正在分析参考图，请等待…" : "正在上传参考图…";
      try {
        const result = await api(analyzeImages ? "/api/visual-presets/analyze-task" : "/api/visual-presets/upload", { method: "POST", body: form });
        if (pending !== editor) return;
        if (analyzeImages) {
          editor.analysis_task_id = result.task_id; persistDraft();
          const draft = await taskMonitor.wait(result.task_id);
          if (pending !== editor) return;
          readEditor();
          applyAnalysisSuggestion(editor, draft);
        } else editor.draft.reference_paths = result.reference_paths;
        renderEditor(); persistDraft();
      } finally {
        editingAnalysis = false; setBusy(el.saveVisualPresetBtn, false);
        setBusy(el.uploadVisualPresetReferencesBtn, false); setBusy(el.analyzeEditorReferencesBtn, false);
      }
    }
    function applyAnalysisSuggestion(editor, draft) {
      editor.draft.reference_paths = draft.reference_paths;
      editor.draft.analysis_suggestion = draft;
      delete editor.analysis_task_id;
      if (draft.status === "analyzed" && global.confirm("文字草稿已生成。是否将正向、负向和结构化字段替换为分析结果？选择取消可保留当前手工描述，参考图仍保留。")) {
        Object.assign(editor.draft, { positive: draft.positive, negative: draft.negative, structured: draft.structured });
        delete editor.draft.structured_text;
      }
      editor.draft.status = draft.status; editor.draft.error = draft.error;
    }
    function bindEvents() {
      el.refreshVisualPresetsBtn.addEventListener("click", () => refresh().catch(report));
      el.createStylePresetBtn.addEventListener("click", () => openEditor(null, "style"));
      el.createCompositionPresetBtn.addEventListener("click", () => openEditor(null, "composition"));
      el.analyzeStylePresetBtn.addEventListener("click", () => analyze("style").catch(report));
      el.analyzeCompositionPresetBtn.addEventListener("click", () => analyze("composition").catch(report));
      el.visualPresetForm.addEventListener("submit", (event) => saveEditor(event).catch((error) => { el.visualPresetDraftState.textContent = `保存失败：${error.message}`; }));
      el.cancelVisualPresetBtn.addEventListener("click", () => { readEditor(); el.visualPresetDialog.close(); });
      el.visualPresetDialog.addEventListener("close", readEditor);
      for (const node of [el.visualPresetName, el.visualPresetPositive, el.visualPresetNegative, el.visualPresetStructured]) node.addEventListener("input", readEditor);
      for (const kind of KINDS) {
        const selector = kind === "style" ? el.runStylePreset : el.runCompositionPreset;
        selector.addEventListener("change", () => {
          if (!activeKinds.includes(kind)) return;
          state.visualPresetDefaults[`${kind}_id`] = selector.value || null;
          state.visualPresetDefaults[`${kind}_reference_mode`] = state.visualPresets.find((item) => item.id === selector.value)?.reference_mode || "text";
          const modeSelector = kind === "style" ? el.runStyleReferenceMode : el.runCompositionReferenceMode;
          modeSelector.value = state.visualPresetDefaults[`${kind}_reference_mode`];
          saveDefaults().catch(report);
        });
        const shotSelector = kind === "style" ? el.shotStylePreset : el.shotCompositionPreset;
        shotSelector.addEventListener("change", () => { if (!activeKinds.includes(kind)) return; saveShot(); saveWorkspaceDraft(); saveSelection().catch(report); });
      }
      el.adoptRunVisualPresetsBtn.addEventListener("click", () => saveDefaults(true).then(preview).catch(report));
      el.adoptShotVisualPresetsBtn.addEventListener("click", () => adoptShot().catch(report));
      el.resumeVisualPresetDraftBtn.addEventListener("click", () => resume().catch(report));
      el.testImageReferencesBtn.addEventListener("click", () => testReferences().catch(report));
      el.uploadVisualPresetReferencesBtn.addEventListener("click", () => editorReferences().catch((error) => { el.visualPresetDraftState.textContent = error.message; }));
      el.analyzeEditorReferencesBtn.addEventListener("click", () => editorReferences(true).catch((error) => { el.visualPresetDraftState.textContent = error.message; }));
      el.clearVisualPresetReferencesBtn.addEventListener("click", () => {
        if (!pending || editingAnalysis) return;
        readEditor(); pending.draft.reference_paths = []; pending.draft.reference_mode = "text"; renderEditor(); persistDraft();
      });
      el.visualPresetReferenceMode.addEventListener("change", readEditor);
      for (const kind of KINDS) {
        const selector = kind === "style" ? el.runStyleReferenceMode : el.runCompositionReferenceMode;
        selector.addEventListener("change", () => { if (!activeKinds.includes(kind)) return; state.visualPresetDefaults[`${kind}_reference_mode`] = selector.value; saveDefaults().catch(report); });
        const shotSelector = kind === "style" ? el.shotStyleReferenceMode : el.shotCompositionReferenceMode;
        shotSelector.addEventListener("change", () => { if (!activeKinds.includes(kind)) return; saveShot(); saveWorkspaceDraft(); saveSelection().catch(report); });
      }
      for (const selector of [el.imageSize, el.customImageSize]) selector?.addEventListener("change", () => { refreshCapability().then(preview).catch(report); });
    }
    return { refresh, renderSelectors, loadShot, saveShot, renderSnapshot, schedulePreview, preview, openEditor, analyze, resume, flush, prepareGeneration, bindEvents, refreshCapability, testReferences, resumeProbe, editorReferences };
  }

  global.FicFrameVisualPresets = { createController, referenceUrl, options, snapshotText };
})(window);
