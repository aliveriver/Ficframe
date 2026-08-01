# FicFrame

FicFrame 是一套面向二创小说配图的本地工具集。它会把小说章节、人物简介和风格配置整理成可追踪的视觉流水线：

- 分析小说章节并切成可视化场景
- 从人物简介中抽取角色视觉卡
- 生成章节分镜表
- 结合角色、剧情和连续性状态生成生图 prompt
- 维护角色服装、伤痕、道具、地点和情绪的连续性
- 对生成计划做基础质检，提示可能的人设漂移和画面问题

当前版本不直接调用生图模型，而是输出结构化 JSON 与 Markdown prompt。你可以把 prompt 接到 ComfyUI、Stable Diffusion WebUI、OpenAI Images 或其他模型后端。

## 快速开始

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
uv run ficframe run --novel "小说示例.md" --characters "人物示例.md" --out "outputs/demo"
```

输出目录包含：

- `pipeline.json`：完整结构化结果
- `storyboard.md`：章节分镜表
- `prompts.md`：每张图的正向 / 负向 prompt
- `continuity.json`：角色与场景连续性记忆

也可以单独运行某一步：

```powershell
uv run ficframe segment --novel "小说示例.md"
uv run ficframe characters --characters "人物示例.md"
```

## Web 前端

复制 `.env.example` 为 `.env`，填入你的 key 和模型名；也可以直接用环境变量。

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run ficframe serve --host 127.0.0.1 --port 8787
```

打开 `http://127.0.0.1:8787`。

可选环境变量：

- `FICFRAME_LLM_API_KEY` / `FICFRAME_LLM_BASE_URL` / `FICFRAME_LLM_MODEL`：章节理解和 prompt 增强
- `FICFRAME_IMAGE_API_KEY` / `FICFRAME_IMAGE_BASE_URL` / `FICFRAME_IMAGE_MODEL`：生图
- `FICFRAME_IMAGE_PROVIDER`：生图接口方言，默认 `openai`；Grsai 填 `grsai`，硅基流动填 `siliconflow`
- `FICFRAME_IMAGE_STEPS` / `FICFRAME_IMAGE_GUIDANCE_SCALE` / `FICFRAME_IMAGE_BATCH_SIZE`：硅基流动生图参数
- `FICFRAME_VLM_API_KEY` / `FICFRAME_VLM_BASE_URL` / `FICFRAME_VLM_MODEL`：图片质检

兼容旧配置：如果没有设置上面三组专用 key，会兜底读取 `OPENAI_API_KEY` 或 `FICFRAME_API_KEY`；如果没有设置专用 base url，会兜底读取 `FICFRAME_BASE_URL`。

依赖源已经配置为清华 PyPI 镜像：

```toml
[[tool.uv.index]]
name = "tuna"
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

没有配置对应 API key 时，Web 前端仍可生成本地分镜和 prompt；LLM 增强、生成图片、VLM 质检会分别提示缺少对应 key。

硅基流动图片接口示例：

```env
FICFRAME_IMAGE_API_KEY=你的硅基流动 key
FICFRAME_IMAGE_BASE_URL=https://api.siliconflow.cn/v1
FICFRAME_IMAGE_PROVIDER=siliconflow
FICFRAME_IMAGE_MODEL=Kwai-Kolors/Kolors
FICFRAME_IMAGE_STEPS=20
FICFRAME_IMAGE_GUIDANCE_SCALE=7.5
```

Grsai 的 `gpt-image-2` 参考图模式：

```env
FICFRAME_IMAGE_API_KEY=你的 Grsai key
FICFRAME_IMAGE_BASE_URL=https://grsai.dakka.com.cn/v1
FICFRAME_IMAGE_PROVIDER=grsai
FICFRAME_IMAGE_MODEL=gpt-image-2
```

当分镜中的角色绑定了人设参考图时，FicFrame 会把参考图读取成 data URL，放进 Grsai 的 `images` 请求字段；没有参考图的分镜仍走普通文生图。

Web 前端支持：

- 上传小说 Markdown、人物 Markdown 和多张人设参考图
- 在“参考图绑定”表里确认每张图绑定到哪个角色，并标记正面、半身、服装、表情等类型
- 在 API 管理面板中添加、切换、保存 LLM / 图片 / VLM 三套 API
- 为单个分镜生成图片，或为所有分镜批量生成图片
- 对上传的图片执行 VLM 质检
- 导出配图后的完整小说 Markdown：保留正文，在对应剧情位置插入已生成图片

人物 Markdown 也可以直接写参考图：

```markdown
![多萝西参考图](references/dorothy.png)
```

通过 Web 上传的人设参考图会先按文件名匹配角色名；例如 `多萝西_正面.png` 会建议绑定到多萝西角色卡。最终以“参考图绑定”表里的选择为准，适合一个角色多张参考图、多个角色混合上传的情况。

## 推荐工作流

1. 先维护一份稳定的 `人物示例.md`，写清楚外貌、服装、性格、固定标志物和禁止变化项。
2. 跑 `ficframe run` 生成分镜和 prompt。
3. 使用任意生图模型生成第一轮图片。
4. 把选中的图片作为角色参考图和场景参考图，在实际生图工具里搭配 seed / reference image / LoRA / IP-Adapter 使用。
5. 后续章节继续使用 `continuity.json`，确保服装、伤痕、地点和人物关系连续。

## 后续可扩展点

- 接入 LLM，把当前启发式分析替换成更细腻的章节理解。
- 接入图像模型 API，自动生成和保存图片。
- 接入视觉模型，读取实际生成图并自动检查人物数量、服装、表情和构图。
- 为每个角色生成标准参考图、表情表和服装表。
