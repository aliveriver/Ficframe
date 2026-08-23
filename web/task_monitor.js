(function initTaskMonitor(global) {
  const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

  function createMonitor({ request, elements, onUpdate }) {
    let activeTask = null;

    function render(task) {
      if (!task || !elements?.panel) return;
      activeTask = task;
      elements.panel.hidden = false;
      elements.kind.textContent = taskKindText(task.kind);
      elements.stage.textContent = task.stage || statusText(task.status);
      elements.message.textContent = task.message || "等待任务状态";
      elements.progress.value = Number(task.progress || 0);
      elements.progressText.textContent = `${Number(task.progress || 0)}%`;
      elements.error.textContent = task.error || "";
      elements.error.hidden = !task.error;
      if (elements.logs) {
        elements.logs.textContent = (task.logs || []).slice(-5).map((item) => item.message).join("\n");
        elements.logs.hidden = !(task.logs || []).length;
      }
      onUpdate?.(task);
    }

    async function wait(taskId, interval = 700) {
      while (true) {
        const task = await request(`/api/tasks/${encodeURIComponent(taskId)}`);
        render(task);
        if (TERMINAL.has(task.status)) {
          if (task.status === "failed") throw new Error(task.error || task.message || "任务执行失败");
          if (task.status === "cancelled") throw new Error("任务已取消");
          return task.result;
        }
        await new Promise((resolve) => setTimeout(resolve, interval));
        interval = Math.min(1500, interval + 100);
      }
    }

    async function submit(path, options) {
      const created = await request(path, options);
      render(created.task || {
        task_id: created.task_id, kind: "task", status: "queued",
        stage: "排队中", progress: 0, message: "任务已创建",
      });
      return { created, result: await wait(created.task_id) };
    }

    async function loadRunTasks(runId) {
      if (!runId) return [];
      const data = await request(`/api/runs/${encodeURIComponent(runId)}/tasks`);
      const tasks = data.tasks || [];
      if (tasks[0]) render(tasks[0]);
      return tasks;
    }

    return { get activeTask() { return activeTask; }, loadRunTasks, render, submit, wait };
  }

  function taskKindText(kind) {
    return ({
      pipeline: "完整工作流",
      storyboard_generate: "新增分镜",
      storyboard_feedback: "分镜 Agent 反馈",
      storyboard_regenerate: "重生成分镜",
      prompt_regenerate: "重建 Prompt",
      image: "生成图片",
      image_batch: "批量生成图片",
    })[kind] || "后台任务";
  }

  function statusText(status) {
    return ({ queued: "排队中", running: "执行中", succeeded: "已完成", failed: "失败", cancelled: "已取消" })[status] || status || "未知状态";
  }

  global.FicFrameTaskMonitor = { createMonitor, statusText, taskKindText };
})(window);
