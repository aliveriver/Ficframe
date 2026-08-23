# 分镜工作流架构

分镜功能按“HTTP 编排、领域规则、LLM 能力、浏览器交互”分层，避免把版本、图片和 Agent 决策混在同一个路由或页面函数中。

## 后端边界

| 模块 | 责任 |
| --- | --- |
| `ficframe/api.py` | FastAPI 应用装配、通用路由、任务入口和兼容 API |
| `ficframe/provider_probe.py` | provider、ComfyUI 与本地端口的可达性探测 |
| `ficframe/run_repository.py` | run 路径校验、`pipeline.json` 读写、事务和投影刷新 |
| `ficframe/storyboard_routes.py` | 分镜请求模型、HTTP 路由和用例编排 |
| `ficframe/storyboard_workflow.py` | 分镜版本、来源校验、旧数据迁移和重生成保护 |
| `ficframe/source_reference.py` | `source_ref` 构建、校验、锚点重定位和旧字段迁移 |
| `ficframe/task_manager.py` | 后台任务执行、阶段更新、错误记录和 `tasks.json` 持久化 |
| `ficframe/llm_pipeline.py` | LLM 提示词、反馈决策解析、单条分镜生成或修订 |
| `ficframe/storyboard.py` | 不依赖 LLM 的基础分镜构建与场景选择 |
| `ficframe/render.py` | `storyboard.md`、`prompts.md` 和图文小说投影 |

`pipeline.json` 是当前 run 的唯一规范状态。`storyboard.md` 和 `prompts.md` 是可重新生成的阅读投影，不应反向作为数据源。

## 核心不变量

1. 分镜文本版本和图片版本互相独立。
2. 任何分镜修订都经过 `revise_storyboard_items`；该边界会强制恢复修订前的图片字段。
3. 手动编辑、Agent 自动重生成、手动重生成和版本恢复前，都先调用 `archive_storyboard_versions`；内容相同的文本快照不会重复保存。
4. 历史快照不包含 `image_path`、`image_url` 或 `image_versions`，每条分镜最多保留 50 个互不重复的文本版本。
5. LLM 反馈先返回结构化决策，再由 API 执行；LLM 不直接写文件。
6. 小说选区必须由字符区间或原文包含关系验证，不能把模型生成文本伪装成原文。
7. LLM Prompt 重建会读取当前 run 的反馈历史，只改 Prompt 字段，并在修改前归档完整分镜版本。
8. `source_ref` 是原文引用的规范模型；`source_start`、`source_end`、`source_text` 只作为兼容投影。
9. 文本描述生成使用 `kind=description`，不能伪装成小说原文。
10. 耗时生成先创建任务并返回 `202`，异常必须进入任务的 `error` 和 `logs`。

## 原文引用模型

每个场景和分镜都可以携带 `source_ref`：

| 字段 | 说明 |
| --- | --- |
| `version` | 引用模型版本，当前为 `1` |
| `kind` | `novel` 表示小说原文，`description` 表示用户画面描述 |
| `document` | 原文文件标识，当前为 `novel.md` |
| `start` / `end` | LF 规范化文本中的字符区间 |
| `quote` | 被引用的原文快照或画面描述 |
| `prefix` / `suffix` | 用于处理正文编辑和重复文本的上下文锚点 |
| `document_hash` / `quote_hash` | 文档与引用文本的 SHA-256 校验值 |
| `status` | `exact`、`relocated`、`description` 或 `unresolved` |

读取旧 run 时，系统会从旧版 `source_*` 字段或场景文本构造 `source_ref`。如果字符坐标仍匹配，则状态为 `exact`；坐标失效但原文和上下文锚点可唯一匹配时，更新坐标并标记为 `relocated`；无法可靠定位时标记为 `unresolved`，前端不会产生错误高亮。迁移完成后仍同步旧字段，供旧客户端和导出逻辑继续读取。

## 可观察任务

第一版任务执行器使用进程内 `ThreadPoolExecutor`，任务快照写入 `<run>/tasks.json`。它不依赖请求连接持续存在，页面可按 `task_id` 查询进度。服务进程重启后可以查看已持久化的历史任务，但不会自动恢复当时正在执行的 worker。

任务状态为 `queued`、`running`、`succeeded`、`failed`、`cancelled`。快照包含当前 `stage`、`progress`、`message`、时间戳、结果摘要、错误和最近 100 条日志。当前取消接口只接受尚未开始的任务。

```text
创建任务 -> 202 + task_id
  -> GET /api/tasks/{task_id}
  -> queued / running：继续轮询
  -> succeeded：刷新 run 或应用图片结果
  -> failed：展示 error 与最近日志
```

任务 API：

- `POST /api/pipeline/task`：完整工作流。
- `POST /api/storyboard/generate-task`：按原文引用或描述新增分镜。
- `POST /api/storyboard/feedback-task`：分镜 Agent 分析反馈，并按结构化决策选择是否重生成。
- `POST /api/storyboard/regenerate-task`：批量重新生成分镜并保留图片。
- `POST /api/storyboard/prompt-task`：结合独立 Prompt 反馈重建生图 Prompt。
- `POST /api/images/task`：生成单张图片。
- `POST /api/images/batch-task`：生成选中、全部或失败项图片。
- `GET /api/tasks/{task_id}`：读取任务快照。
- `GET /api/runs/{run_id}/tasks`：读取 run 的任务历史。
- `POST /api/tasks/{task_id}/cancel`：取消尚未开始的任务。

## Agent 反馈流程

```text
用户反馈
  -> respond_to_storyboard_feedback
  -> { action, shot_ids, reply, reason }
  -> action=none：保存对话
  -> action=regenerate：归档目标分镜 -> 修订目标分镜 -> 保存对话和新版本
```

若修订中任意一条失败，工作流不会写入半成品状态。

## 前端边界

| 文件 | 责任 |
| --- | --- |
| `web/app.js` | 页面状态、DOM 事件和工作流编排 |
| `web/workspace_state.js` | 页面草稿序列化、run 状态重置和选中项恢复 |
| `web/storyboard_workspace.js` | 分镜 API 客户端、无状态 HTML 模板与展示文案 |
| `web/prompt_state.js` | Prompt 修改时的布局失效规则 |
| `web/novel_source.js` | 小说预览、选区同步、引用状态和高亮渲染 |
| `web/task_monitor.js` | 任务创建、轮询、阶段/进度/错误渲染 |
| `web/image_workflow.js` | 图片生成任务、结果回填和图片版本切换 |

新增分镜接口时，优先把 URL 和 JSON 结构放进 `createClient`；无状态的文本转换或模板放进 `storyboard_workspace.js`；只有确实依赖当前 DOM/选中状态的逻辑才留在 `app.js`。

## 测试

- `tests/test_storyboard_workflow.py`：API 工作流与持久化回归。
- `tests/test_storyboard_workflow_unit.py`：领域不变量与错误边界。
- `tests/test_storyboard_workspace.js`：前端客户端和纯展示函数。
- `tests/frontend/test_workspace_state.js`：页面草稿和 run 状态重置。
- `tests/frontend/test_image_workflow.js`：图片任务结果回填和版本区域状态。
- `tests/test_run_repository.py`：run 校验、事务写入和规范状态投影。
- `tests/test_source_reference.py`：引用校验、重定位、描述引用和旧数据迁移。
- `tests/test_task_manager.py`：任务完成、失败、日志和磁盘持久化。
