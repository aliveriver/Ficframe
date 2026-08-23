(function initStoryboardWorkspace(global) {
  function createClient(jsonRequest, fetchImpl = global.fetch.bind(global)) {
    return {
      save(runId, shots) {
        return postJson(jsonRequest, "/api/storyboard/save", { run_id: runId, shots });
      },
      generate(runId, input) {
        return postJson(jsonRequest, "/api/storyboard/generate", { run_id: runId, ...input });
      },
      generateTask(runId, input) {
        return postJson(jsonRequest, "/api/storyboard/generate-task", { run_id: runId, ...input });
      },
      feedback(runId, content) {
        return postJson(jsonRequest, "/api/storyboard/feedback", { run_id: runId, content });
      },
      feedbackTask(runId, content) {
        return postJson(jsonRequest, "/api/storyboard/feedback-task", { run_id: runId, content });
      },
      promptFeedback(runId, content) {
        return postJson(jsonRequest, "/api/storyboard/prompt-feedback", { run_id: runId, content });
      },
      regenerate(runId, shotIds) {
        return postJson(jsonRequest, "/api/storyboard/regenerate", { run_id: runId, shot_ids: shotIds });
      },
      regenerateTask(runId, shotIds) {
        return postJson(jsonRequest, "/api/storyboard/regenerate-task", { run_id: runId, shot_ids: shotIds });
      },
      restoreVersion(runId, shotId, versionId) {
        return postJson(jsonRequest, "/api/storyboard/version", {
          run_id: runId,
          shot_id: shotId,
          version_id: versionId,
        });
      },
      regeneratePrompt(runId, shotId) {
        return postJson(jsonRequest, "/api/storyboard/prompt", {
          run_id: runId,
          shot_id: shotId,
        });
      },
      regeneratePromptTask(runId, shotId) {
        return postJson(jsonRequest, "/api/storyboard/prompt-task", {
          run_id: runId,
          shot_id: shotId,
        });
      },
      async loadNovel(runId) {
        const response = await fetchImpl(`/api/runs/${encodeURIComponent(runId)}/novel`);
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || response.statusText);
        }
        return response.text().then(normalizeNovelText);
      },
    };
  }

  function normalizeNovelText(text) {
    return String(text || "")
      .replace(/\r+\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\n{3,}/g, "\n\n");
  }

  function postJson(jsonRequest, path, body) {
    return jsonRequest(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function feedbackHistoryMarkup(messages, escapeHtml, agentLabel = "分镜 Agent") {
    if (!messages.length) {
      return `<p class="feedback-empty">还没有反馈。LLM 会在这里记住本轮工作流中的取舍。</p>`;
    }
    return messages.map((message) => `
      <div class="feedback-message ${message.role === "user" ? "user" : "assistant"}">
        <span class="feedback-role">${message.role === "user" ? "你" : escapeHtml(agentLabel)}</span>
        ${escapeHtml(message.content)}
      </div>
    `).join("");
  }

  function versionHistoryMarkup(versions, shotId, escapeHtml) {
    if (!versions.length) {
      return `<p class="feedback-empty">修改或重生成后，之前的分镜会保存在这里。</p>`;
    }
    return [...versions].reverse().map((version, reverseIndex) => {
      const shot = version.shot || {};
      const timeText = version.created_at ? new Date(version.created_at * 1000).toLocaleString() : "未知时间";
      const versionNumber = versions.length - reverseIndex;
      return `
        <div class="storyboard-version">
          <div class="storyboard-version-copy">
            <strong>版本 ${versionNumber} · ${escapeHtml(shot.title || shotId)}</strong>
            <small>${escapeHtml(timeText)} · ${escapeHtml(version.reason || "历史版本")}</small>
            <small>${escapeHtml(shot.visual_goal || shot.source_excerpt || "")}</small>
          </div>
          <button type="button" data-storyboard-version="${escapeHtml(version.version_id)}">恢复</button>
        </div>
      `;
    }).join("");
  }

  function highlightedContextMarkup(novelText, start, end, escapeHtml, radius = 80) {
    const contextStart = Math.max(0, start - radius);
    const contextEnd = Math.min(novelText.length, end + radius);
    return `${escapeHtml(novelText.slice(contextStart, start))}<mark>${escapeHtml(novelText.slice(start, end))}</mark>${escapeHtml(novelText.slice(end, contextEnd))}`;
  }

  function highlightedDocumentMarkup(novelText, start, end, escapeHtml) {
    return `${escapeHtml(novelText.slice(0, start))}<mark>${escapeHtml(novelText.slice(start, end))}</mark>${escapeHtml(novelText.slice(end))}`;
  }

  function resolveShotSourceSelection(novelText, shot) {
    const text = normalizeNovelText(novelText);
    const reference = shot?.source_ref || {};
    const hasReference = Boolean(shot?.source_ref);
    if (reference.kind === "description" || reference.status === "unresolved") {
      const selection = { start: 0, end: 0, text: "" };
      if (hasReference) selection.status = reference.status || "description";
      return selection;
    }
    const sourceText = normalizeNovelText(reference.quote || shot?.source_text || "");
    let start = Number.isInteger(reference.start) ? reference.start : (Number.isInteger(shot?.source_start) ? shot.source_start : -1);
    let end = Number.isInteger(reference.end) ? reference.end : (Number.isInteger(shot?.source_end) ? shot.source_end : -1);
    if (start >= 0 && end > start && text.slice(start, end) === sourceText) {
      const selection = { start, end, text: sourceText };
      if (hasReference) selection.status = reference.status || "exact";
      return selection;
    }
    const fallback = sourceText || (shot?.generation_mode === "description" ? "" : normalizeNovelText(shot?.source_excerpt || ""));
    start = fallback ? text.indexOf(fallback) : -1;
    end = start >= 0 ? start + fallback.length : 0;
    const selection = { start: Math.max(0, start), end: Math.max(0, end), text: start >= 0 ? text.slice(start, end) : "" };
    if (hasReference) selection.status = start >= 0 ? "relocated" : "unresolved";
    return selection;
  }

  function feedbackOutcomeText(regeneratedShotIds) {
    return regeneratedShotIds.length
      ? `分镜 Agent 已自动重新生成 ${regeneratedShotIds.join("、")}，图片与历史版本已保留`
      : "分镜 Agent 判断无需重新生成，已记录并回应这条反馈";
  }

  function splitEditorList(value) {
    return String(value || "").split(/[、，,]/).map((item) => item.trim()).filter(Boolean);
  }

  global.FicFrameStoryboardWorkspace = {
    createClient,
    feedbackHistoryMarkup,
    feedbackOutcomeText,
    highlightedContextMarkup,
    highlightedDocumentMarkup,
    normalizeNovelText,
    resolveShotSourceSelection,
    splitEditorList,
    versionHistoryMarkup,
  };
})(window);
