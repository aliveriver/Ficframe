(function initProviderManager(global) {
  function createController({ state, elements: el, api, escapeHtml, setBusy, checkHealth, onSaved = async () => {} }) {
    const optionFields = {
      steps: el.imageSteps, guidance_scale: el.imageGuidance, batch_size: el.imageBatch,
      sequential: el.imageSequential, response_format: el.imageResponseFormat, watermark: el.imageWatermark,
      workflow_json: el.comfyWorkflow, negative_prompt: el.comfyNegativePrompt,
      output_node_id: el.comfyOutputNode, poll_interval: el.comfyPollInterval,
    };
    const optionDefaults = { watermark: "true", poll_interval: "1" };
    function updateVisibility(source = findProvider()) {
      el.imageOptions.hidden = source?.kind !== "image";
      el.comfyOptions.hidden = source?.kind !== "image" || source?.provider !== "comfyui";
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
      updateVisibility(source);
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
      for (const [key, node] of Object.entries(optionFields)) node.value = options[key] ?? optionDefaults[key] ?? "";
      updateVisibility(source);
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
          row.remove();
          syncProviderForm();
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
      const models = Array.from(el.modelTable.querySelectorAll(".model-row")).map((row) => ({
        nickname: row.querySelector('[data-field="nickname"]').value.trim(),
        model: row.querySelector('[data-field="model"]').value.trim(),
        active: row.querySelector('[data-field="active"]').checked,
      })).filter((model) => model.model);
      source.active_model = models.find((model) => model.active)?.model || models[0]?.model || "";
      source.models = models.map(({ nickname, model }) => ({ nickname: nickname || model, model }));
      source.options = source.kind === "image" ? Object.fromEntries(Object.entries(optionFields).map(([key, node]) =>
        [key, key === "output_node_id" ? node.value.trim() : node.value || optionDefaults[key] || ""]
      )) : {};
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
        await onSaved();
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


    function kindLabel(kind) {
      return { llm: "LLM", image: "图片", vlm: "VLM" }[kind] || kind;
    }
    function bindEvents() {
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
      const updateForm = () => { syncProviderForm(); renderProviderList(); updateVisibility(); };
      const fields = [el.providerKind, el.providerType, el.providerActive, el.providerLabel,
                      el.providerBaseUrl, el.providerKey, ...Object.values(optionFields)];
      for (const node of fields) for (const event of ["input", "change"]) node.addEventListener(event, updateForm);
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
    }
    return { loadConfig, bindEvents };
  }
  global.FicFrameProviderManager = { createController };
})(window);
