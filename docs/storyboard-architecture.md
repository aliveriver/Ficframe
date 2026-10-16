# 分镜工作流架构

分镜功能按“HTTP 编排、领域规则、LLM 能力、浏览器交互”分层，避免把版本、图片和 Agent 决策混在同一个路由或页面函数中。

## 后端边界

| 模块 | 责任 |
| --- | --- |
| `ficframe/api.py` | FastAPI 应用装配、HTTP 参数/错误转换、任务入口和兼容 Python API |
| `ficframe/pipeline.py` | Web / CLI 共用的场景分析、Prompt Bank、分镜构建及有序 LLM 精修 |
| `ficframe/payloads.py` | 人设、场景、手动角色和参考图绑定的统一输入转换，不依赖 HTTP |
| `ficframe/image_workflow.py` | 图片输入组装、单张/批量共用生成与重试、版本保存及激活，不依赖 HTTP |
| `ficframe/provider_probe.py` | provider、ComfyUI 与本地端口的可达性探测 |
| `ficframe/run_repository.py` | run 路径校验、`pipeline.json` 读写、事务和投影刷新 |
| `ficframe/visual_presets.py` | 全局画风/构图预设存储、参考图校验、VLM 草稿字段规范化和 Prompt 约束组装 |
| `ficframe/storyboard_routes.py` | 分镜请求模型、HTTP 路由和用例编排 |
| `ficframe/storyboard_workflow.py` | 分镜版本、来源校验、旧数据迁移和重生成保护 |
| `ficframe/source_reference.py` | `source_ref` 构建、校验、锚点重定位和旧字段迁移 |
| `ficframe/task_manager.py` | 后台任务执行、阶段更新、错误记录和 `tasks.json` 持久化 |
| `ficframe/llm_pipeline.py` | LLM 提示词、反馈决策解析、单条分镜生成或修订 |
| `ficframe/storyboard.py` | 不依赖 LLM 的基础分镜构建与场景选择 |
| `ficframe/render.py` | `storyboard.md`、`prompts.md` 和图文小说正文投影 |
| `ficframe/export.py` | 生成可携带的 Markdown + `images/` 目录、`manifest.json`、主题说明和 ZIP 成品包 |

`pipeline.json` 是当前 run 的唯一规范状态。`storyboard.md` 和 `prompts.md` 是可重新生成的阅读投影，不应反向作为数据源。

### 入口与共享工作流

Web 路由负责上传、供应商选择和任务调度，CLI 负责文件路径和输出目录；两者均调用 `build_story_payload`，共用分段、Prompt Bank、差异分析、连续性、分镜与来源引用。快速模式复用现有人设并跳过全流程精修，完整模式和 CLI 的 LLM 模式沿用同一构建流程。`polish_shots_with_llm` 在串行和并发模式下均隔离单条异常，保留本地 Prompt，输出顺序与输入一致。

`ImageWorkflow` 显式接收 repository、视觉预设存储和角色参考图解析回调。同步单张、后台单张和批量生成均使用 `generate_item`：先固定预设版本和最终 Prompt，再调用图片供应商，成功后在同一事务保存图片版本及生成快照。重试复用首次组装的参数，不会因全局预设编辑而改变中途请求。仅固定绑定快照时不重写 Markdown 投影，保存或激活图片时仍更新投影。已有图片的后续候选文件采用唯一名称，避免同一毫秒内的重生成覆盖历史；分镜 ID 不可作为路径逃逸到图片目录外。

领域模块不导入 `api.py`、不调用 FastAPI；HTTP 入口将普通校验错误、供应商异常和版本不存在分别转换为原有响应。`api.py` 中的薄适配函数保留原有 Python 调用名称，现有 HTTP 路径和请求/响应模型保持兼容。

### 视觉规范预设

发布开关集中在 `ficframe/features.py`，当前 `COMPOSITION_REFERENCES_ENABLED = False`。构图预设、VLM 分析和供应商适配实现保留，但构图 CRUD/上传/分析接口返回 404，列表只返回启用的类型。绑定与生图解析只处理 `visual_preset_kinds()`，旧 run 和分镜中的构图 ID、快照、历史图片保留且不参与新 Prompt 或原图请求；缺失的旧构图文件不会阻断生成。多图实测只使用已启用的画风通道。前端以画风为安全默认值，按列表返回的 `enabled_types` 展示控件；不会恢复构图草稿或轮询旧分析任务。保留功能的回归测试显式打开开关，默认发布行为由 `test_composition_reference_release.py` 和前端停用测试覆盖。以下两类型结构说明描述保留实现。

画风（`style`）和构图（`composition`）是独立的全局预设，存放在用户数据目录的 `visual-presets/`，参考图也不进入 run 的角色参考图目录。run 在 `visual_presets` 中记录两个默认 ID 及 `*_snapshot`；`Shot` 用 `*_preset_mode`（`inherit`、`preset`、`none`）表示继承、覆盖或显式禁用。应用预设时固定版本；更改全局预设不自动改变已有绑定，只有显式选择或 `refresh` 才采用最新版。run 默认更新只改变继承项。旧 pipeline 缺少这些字段时由 `RunRepository` 补默认值；早期仅保存默认 ID 的 run 可从匹配的继承分镜快照补全绑定。

职责分为 `visual_presets.py`（原子 JSON 存储、上传校验、纯 Prompt 组装）、`visual_preset_analysis.py`（类型限定 VLM 分析与结果规范化）、`visual_preset_workflow.py`（版本绑定、统一生成解析）、`visual_preset_routes.py`（CRUD、分析和 run API）、`web/visual_presets.js`（前端独立控制器）。单张、选中、全部和失败重试共用解析器，临时组合原始 Prompt 与两类规范，不改写手工 Prompt。生成前事务固定选择，即使调用失败也可稳定重试；成功图片与 `visual_preset_snapshot` 在同一事务提交，记录 ID、版本、规范、参考图路径、组装版本及实际正负 Prompt。`last_generation_visual_snapshot` 表示最近成功生成，当前图片实际规范从相应图片版本读取。

VLM 分析复用 `TaskManager`，任务独立持久化于 `visual-presets/analysis-tasks/analysis/tasks.json`，不依赖 run。分析只生成草稿，类型限定的结构化字段可编辑；未配置、异常或无效返回提供可手填草稿，供应商异常不原样持久化以免回显凭据或图像请求内容。浏览器单独保存编辑草稿和待分析 task ID，刷新后可恢复。选择保存排队串行，生图等待选择及分镜保存完成再提交。

参考图上传校验数量、扩展名、MIME、文件头和大小；客户端文件名去路径并安全化。预览接口仅可访问存储内三段 `drafts|references/<owner>/<filename>` 图片路径，不开放整个存储目录。删除或替换参考图时保留历史原文件，分析草稿和任务结果也暂不自动清理，避免悬空引用；后续垃圾回收需同时考虑 run、历史版本、任务与待确认编辑器。没有 ControlNet、漫画页或画格概念。

### 文本 / 原图双模式及多图能力验证

所有图片供应商和模型统一使用 `image_sizes.normalize_image_size`，将 1K/2K/4K 转换为 1024x1024/2048x2048/2880x2880，自定义尺寸保持不变。`OpenAICompatibleProvider.image` 在供应商分支前执行转换，覆盖 JSON 生图、multipart 参考图编辑与 ComfyUI 工作流；`comfyui.parse_size` 也复用该映射，避免直接渲染工作流时出现不同结果。能力指纹使用同一转换后的实际请求尺寸，使 2K 与 2048x2048 的测试结果一致，也不复用旧版发送符号尺寸的测试记录。通用 `generate failed` 失败保持 `unknown`，不能据此判定多图不支持。

默认画风与参考模式属于生成输入，不依赖已存在的 run。前端在空工作区也允许选择，并将仅包含画风选择的状态保存为草稿；更换小说或人设时保留选择、清除上一 run 的绑定快照。`POST /api/pipeline` 与 `POST /api/pipeline/task` 接受可选表单字段 `style_id`、`style_reference_mode`；在调用模型前校验并固定预设快照，新生成分镜继承该快照。任务完成后以服务端保存的默认值刷新选择框，保持后续生图和显示一致。

预设的 `reference_mode` 为 `text` 或 `image`（旧预设默认为文本），仅作为选择 run 预设时的建议。run 分别记录 `style_reference_mode`、`composition_reference_mode`，单条 `Shot` 同名字段还可取 `inherit`，独立于 `*_preset_mode` 的预设来源选择。绑定快照记录当时有效模式与原始图片路径；仅文本模式不发送视觉图片，即使预设保留参考图。手工原图上传不调用 VLM，分析操作仍只返回待确认草稿。新字段加入保存、修订和浏览器恢复链路，旧 run 继续默认文本。

`image_reference_workflow.py` 负责图片用途 Prompt、原图路径解析、总图数 preflight、能力记录和显式实际测试。单张/批量共用 `image_generation_inputs`。`provider.image` 新增独立 `style_reference_images`、`composition_reference_images` 参数，不写入 `reference_image_groups`。云端最终发送顺序为角色身份、画风、构图，Prompt 使用 1-based 序号逐组说明用途；视觉图片存在时不再套用“所有图片都是角色设计”的旧身份模板。原有仅角色参考行为保持不变。模式、用途排序、数量、能力依据随生成快照保存。

能力测试为可选诊断，需 `confirmed: true`，复用全局后台任务机制，发送 2–32 张内置 PNG 色块，实际生成一张图（可能计费），临时输入和输出仅在任务自有临时目录保存，结束自动清理。成功仅表示多图请求得到图片，无法证明每张图被模型使用。浏览器保存测试 task ID，刷新或临时断网后可继续监控原任务，不重复发起收费测试；并发点击也只提交一次。能力缓存 `visual-presets/reference-capabilities.json` 按供应商、地址、模型、凭据散列、尺寸和适配器版本隔离，不保存 API key。preflight 统计人设＋画风＋构图总数，仅在缺图、文件无效或适配器未实现原图发送时阻止生成。未测试、缓存为失败、配置或尺寸改变、总数超过测试数量均允许直接生成，不触发额外测试请求。限流、鉴权、超时等记为 `unknown`，明确拒绝参考图时记为 `unsupported`；缓存状态仅供参考。实际生成中明确拒绝参考图时停止当前批次的后续调用，之后的新请求仍可直接重试，不做静默文本降级。

当前 SiliconFlow 适配器没有发送视觉原图的参数，ComfyUI 只有现有身份参考工作流，两者标为适配器不支持，不触发收费测试。通用编辑接口、GRSAI、Ark 沿用已有图片参数形状，可直接生成或由用户选择测试；不新增 ControlNet/IP-Adapter 样式或布局工作流。视觉原图调用和测试日志不保存文本预览、图像内容及供应商完整错误响应。HTTP 错误仅提取结构化错误描述、错误码与请求 ID；HTTP 200 中的 `status: failed` / `error` 也按失败处理。生成错误经过凭据、已提交文本和图片 data URL 脱敏后显示，不再统一覆盖为无具体原因的提示。`excessive system load` 保留原文并提示供应商负载过高，不更新为能力不支持。

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
- `POST /api/visual-presets/analyze-task`：后台分析画风或构图参考图，返回待确认草稿。
- `GET/POST/PATCH/DELETE /api/visual-presets`：全局视觉预设的列表、创建、编辑和删除。
- `GET /api/visual-presets/reference/{zone}/{owner}/{filename}`：安全预览参考图。
- `POST /api/runs/{run_id}/visual-presets`：保存默认选择；`refresh: true` 显式采用最新版。
- `POST /api/runs/{run_id}/shots/{shot_id}/visual-presets`：保存单条选择；同样支持显式更新。
- `POST /api/runs/{run_id}/visual-preview`：只读预览生图规范和最终 Prompt。
- `POST /api/visual-presets/upload`：只上传原图并返回草稿路径，不调用 VLM 或自动保存预设。
- `GET /api/image-reference-capability?size=...`：查询当前已保存图片模型/尺寸的多图能力，不产生外部请求。
- `POST /api/image-reference-test-task`：确认后实际多图测试，返回后台任务；`confirmed`、`reference_count`、`size`。
- `GET /api/export/{run_id}.md`：生成并返回图文 Markdown。
- `GET /api/export/{run_id}.html`：按当前 HTML 图片布局和文本设置生成并返回 HTML。
- `GET /api/export/{run_id}`：生成导出目录并返回 Markdown、图片目录、manifest、主题说明和 ZIP 的路径/URL。
- `GET /api/export/{run_id}.zip`：下载 ZIP 成品包。
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
| `web/app.js` | DOM 控件索引、共享页面状态、控制器装配和主工作流编排 |
| `web/provider_manager.js` | 供应商/模型表单、用途切换、配置保存及可达性测试 |
| `web/html_visual_editor.js` | 图片排版与手势、主页面/排版器共用文本设置、预览及 MD/HTML/ZIP 导出 |
| `web/action_menus.js` | 同类操作的菜单互斥、外部点击收起、Esc/方向键操作及视口边界定位 |
| `web/workspace_state.js` | 页面草稿序列化、run 状态重置和选中项恢复 |
| `web/storyboard_workspace.js` | 分镜 API 客户端、无状态 HTML 模板与展示文案 |
| `web/prompt_state.js` | Prompt 修改时的布局失效规则 |
| `web/novel_source.js` | 小说预览、选区同步、引用状态和高亮渲染 |
| `web/task_monitor.js` | 任务创建、轮询、阶段/进度/错误渲染 |
| `web/image_workflow.js` | 图片生成任务、结果回填和图片版本切换 |

各控制器以 `createController` 接收共享 `state`、DOM 元素及 API/保存回调，通过 `bindEvents` 绑定各自操作；供应商和排版事件不再集中在 `app.js`。DOM 控件按现有 ID 一次建立索引。文本设置用同一字段映射同步主页面和排版器，预览按请求序号及 run 校验，只应用当前响应。

MD、HTML、ZIP 及日志下载共用 `downloadResponse`，统一检查 HTTP 错误、解析普通/UTF-8 文件名并释放对象 URL；服务端返回错误时显示原因，不将错误正文当成小说下载。供应商模型表单先过滤空行，再按勾选项确定模型，避免空行导致当前模型错位。

新增分镜接口时，优先把 URL 和 JSON 结构放进 `createClient`；无状态的文本转换或模板放进 `storyboard_workspace.js`；供应商、排版或图片流程分别在对应控制器内维护。主入口只协调跨业务状态与操作，不反向成为控制器的隐式全局依赖。

## 测试

- `tests/test_storyboard_workflow.py`：API 工作流与持久化回归。
- `tests/test_storyboard_workflow_unit.py`：领域不变量与错误边界。
- `tests/test_pipeline.py`：CLI / Web 输出一致性、串行/并发精修的顺序和异常隔离。
- `tests/test_image_workflow.py`：候选文件隔离、路径校验、重试固定预设与成功版本提交。
- `tests/test_storyboard_workspace.js`：前端客户端和纯展示函数。
- `tests/frontend/test_workspace_state.js`：页面草稿和 run 状态重置。
- `tests/frontend/test_image_workflow.js`：图片任务结果回填和版本区域状态。
- `tests/frontend/test_provider_manager.js`：空模型行、用途切换、零值参数和水印选项。
- `tests/frontend/test_html_visual_editor.js`：排版与主页面同步、过期预览隔离、导出错误和下载文件名。
- `tests/test_run_repository.py`：run 校验、事务写入和规范状态投影。
- `tests/test_source_reference.py`：引用校验、重定位、描述引用和旧数据迁移。
- `tests/test_export.py`：Markdown 图片目录、manifest、主题说明和 ZIP 内容。
- `tests/test_task_manager.py`：任务完成、失败、日志和磁盘持久化。
