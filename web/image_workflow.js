(function initImageWorkflow(global) {
  function createController({
    state, elements, api, taskMonitor, escapeHtml, clone, setBusy,
    saveSelectedPrompt, saveCharacterEditor, saveShotEditor = () => {}, saveWorkspaceDraft,
    renderShots, selectedImageSize, prepareGeneration = async () => {},
  }) {
    function stripVersionQuery(url = "") {
      return String(url).split("?", 1)[0];
    }

    function versionedUrl(url, seed) {
      const clean = stripVersionQuery(url);
      return clean ? `${clean}?v=${encodeURIComponent(seed || Date.now())}` : "";
    }

    function appendImageVersion(versions = [], next) {
      const items = Array.isArray(versions) ? versions.slice() : [];
      const exists = items.some((item) => stripVersionQuery(item.image_url || "") === stripVersionQuery(next.image_url || ""));
      if (!exists) items.push(next);
      return items;
    }

    function applyResult(result) {
      const shot = state.shots.find((item) => item.id === result.shot_id);
      if (shot) {
        if (result.visual_preset_snapshot) shot.last_generation_visual_snapshot = result.visual_preset_snapshot;
        if (Array.isArray(result.image_versions)) {
          shot.image_versions = result.image_versions;
        } else if (result.raw_image_url || result.image_url) {
          const rawUrl = result.raw_image_url || stripVersionQuery(result.image_url);
          shot.image_versions = appendImageVersion(shot.image_versions, {
            image_path: result.image_path,
            image_url: rawUrl,
            created_at: Math.floor(Date.now() / 1000),
          });
        }
        if (result.activated || !shot.image_url) {
          shot.image_url = result.raw_image_url || stripVersionQuery(result.image_url);
          shot.image_path = result.image_path;
        }
      }
      if (state.selected?.id === result.shot_id) {
        if (shot?.image_url) {
          elements.preview.innerHTML = `<img alt="${escapeHtml(result.shot_id)}" src="${escapeHtml(versionedUrl(shot.image_url, Date.now()))}" />`;
        }
        renderVersions();
        if (elements.visualPromptSnapshot) {
          const snapshot = shot?.last_generation_visual_snapshot || {};
          const label = (kind, text) => snapshot[kind]?.id ? `${text}：${snapshot[kind].name || snapshot[kind].id} v${snapshot[kind].version || 1}${snapshot[kind].positive ? ` · ${snapshot[kind].positive}` : ""}` : `${text}：未使用`;
          const kinds = state.visualPresetKinds || ["style"];
          elements.visualPromptSnapshot.textContent = `最近生成实际规范（软约束） · ${kinds.map((kind) => label(kind, kind === "style" ? "画风" : "构图")).join(" · ")}`;
        }
      }
      renderShots(state.selected?.id);
      saveWorkspaceDraft();
    }

    async function activateVersion(imageUrl) {
      if (!state.selected || !state.runId || !imageUrl) return;
      saveSelectedPrompt();
      try {
        const data = await api("/api/images/version", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ run_id: state.runId, shot_id: state.selected.id, image_url: imageUrl }),
        });
        applyResult({ ...data, ok: true, activated: true });
        elements.health.textContent = `${state.selected.id} 已切换图片版本`;
      } catch (error) {
        elements.health.textContent = `切换版本失败：${error.message}`;
      }
    }

    function renderVersions() {
      if (!elements.imageVersions) return;
      if (!state.selected) {
        elements.imageVersions.innerHTML = "";
        return;
      }
      const versions = Array.isArray(state.selected.image_versions) ? state.selected.image_versions : [];
      if (!versions.length) {
        elements.imageVersions.innerHTML = "";
        return;
      }
      elements.imageVersions.innerHTML = `
        <div class="image-version-head">
          <strong>图片版本</strong>
          <span>${versions.length} 个本地版本</span>
        </div>
        <div class="image-version-grid">
          ${versions.map((version, index) => {
            const url = version.image_url || "";
            const active = stripVersionQuery(url) === stripVersionQuery(state.selected.image_url || "");
            return `
              <div class="image-version ${active ? "active" : ""}">
                <img src="${escapeHtml(versionedUrl(url, version.created_at || index))}" alt="${escapeHtml(state.selected.id)} version ${index + 1}" />
                <div class="image-version-actions">
                  <span>${active ? "当前" : `版本 ${index + 1}`}</span>
                  <button type="button" data-image-url="${escapeHtml(url)}" ${active ? "disabled" : ""}>设为当前</button>
                </div>
              </div>`;
          }).join("")}
        </div>`;
      elements.imageVersions.querySelectorAll("button[data-image-url]").forEach((button) => {
        button.addEventListener("click", () => activateVersion(button.dataset.imageUrl));
      });
    }

    async function generateBatch(shots, { skipExisting, retryCount, label }) {
      const created = await api("/api/images/batch-task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: state.runId,
          size: selectedImageSize(),
          retry_count: retryCount,
          skip_existing: skipExisting,
          shots: shots.map((shot) => ({
            ...shot,
            positive_prompt: shot === state.selected ? elements.promptBox.value : shot.positive_prompt,
          })),
        }),
      });
      const data = await taskMonitor.wait(created.task_id);
      const results = data.results || [];
      for (const result of results) {
        if (result.ok && !result.skipped) applyResult(result);
      }
      elements.health.textContent = `${label}任务已完成`;
      return results;
    }

    async function generateCurrent() {
      if (!state.selected || !state.runId) return;
      saveSelectedPrompt();
      saveCharacterEditor();
      saveShotEditor();
      setBusy(elements.imageBtn, true);
      try {
        await prepareGeneration([state.selected.id]);
        const shot = clone(state.selected);
        const created = await api("/api/images/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ run_id: state.runId, size: selectedImageSize(), overwrite: true, shot }),
        });
        const data = await taskMonitor.wait(created.task_id);
        applyResult({ ...data, shot_id: shot.id, ok: true });
        elements.health.textContent = data.activated ? `${shot.id} 图片已生成` : `${shot.id} 新图已保存为候选版本`;
      } catch (error) {
        elements.health.textContent = error.message;
      } finally {
        setBusy(elements.imageBtn, false);
      }
    }

    async function runBatch(button, shots, options, emptyMessage = "") {
      if (!state.runId || !state.shots.length) return;
      saveSelectedPrompt();
      saveCharacterEditor();
      saveShotEditor();
      if (!shots.length) {
        elements.health.textContent = emptyMessage;
        return;
      }
      setBusy(button, true);
      try {
        const ids = new Set(shots.map((shot) => shot.id));
        await prepareGeneration([...ids]);
        const savedShots = state.shots.filter((shot) => ids.has(shot.id));
        const results = await generateBatch(savedShots, options);
        const failures = results.filter((item) => !item.ok);
        const skipped = results.filter((item) => item.skipped).length;
        elements.health.textContent = `${options.label}完成：${results.length - failures.length}/${shots.length}${skipped ? `，跳过 ${skipped}` : ""}`;
        elements.qaBox.textContent = failures.length
          ? failures.map((item) => `${item.shot_id}: ${item.error}`).join("\n\n")
          : `${options.label}已完成`;
      } catch (error) {
        elements.health.textContent = error.message;
      } finally {
        setBusy(button, false);
      }
    }

    function generateSelected() {
      const shots = state.shots.filter((shot) => state.selectedShotIds.has(shot.id));
      return runBatch(elements.selectedImagesBtn, shots, {
        skipExisting: false, retryCount: Number(elements.imageRetryCount.value || 0), label: "选中生成",
      }, "请先在分镜列表左侧勾选要生成的分镜");
    }

    function generateAll() {
      return runBatch(elements.allImagesBtn, state.shots, {
        skipExisting: elements.skipExistingImages.checked,
        retryCount: Number(elements.imageRetryCount.value || 0),
        label: "批量生成",
      });
    }

    function retryFailed() {
      const shots = state.shots.filter((shot) => !shot.image_url && !shot.image_path);
      return runBatch(elements.retryFailedBtn, shots, {
        skipExisting: false, retryCount: Number(elements.imageRetryCount.value || 1), label: "失败重试",
      }, "没有需要重试的失败分镜");
    }

    return { generateAll, generateCurrent, generateSelected, renderVersions, retryFailed };
  }

  global.FicFrameImageWorkflow = { createController };
})(window);
