# FicFrame

FicFrame 是一套本地运行的小说配图工具集，目标是把二创小说、人物设定和人设参考图整理成可以持续迭代的图文生成流程。

它可以帮你完成：

- 解析小说章节，把正文切分成适合出图的剧情段落
- 从人物 Markdown 中抽取角色卡、人设特征和参考图信息
- 生成分镜、图片 prompt 和连续性提示
- 在 Web 中绑定“角色 ↔ 参考图”，一个角色可以绑定多张图
- 管理多套 LLM / 图片 / VLM API 供应商
- 调用图片模型生成单张或批量图片
- 使用 VLM 对生成图做基础质检
- 导出“已经插入配图的完整小说 Markdown”
- 从 Web 一键导出脱敏日志包，方便反馈 bug

FicFrame 适合想把长篇小说做成图文版、分镜版、视频前期素材或角色一致性生图素材的创作者。

## 预览

目前 Web 是一个本地工作台，主要包含：

- 左侧：小说、人物文件、人设参考图、参考图绑定表、分镜数量、图片尺寸
- 中间：分镜列表
- 右侧：当前分镜 prompt、图片预览、批量生成、VLM 质检、导出小说 MD
- 顶部 API 管理：供应商列表、请求地址、API key、模型昵称、可达性测试

## 快速开始

### 方式一：Windows 双击启动

确保电脑已经安装 [uv](https://docs.astral.sh/uv/)。

然后双击项目根目录下的：

```text
start.bat
```

脚本会自动：

- 进入项目目录
- 使用项目内 `.uv-cache` 作为 uv 缓存目录
- 如果没有 `.env`，从 `.env.example` 复制一份
- 执行 `uv sync` 安装依赖
- 打开浏览器访问 `http://127.0.0.1:8787`
- 启动 FicFrame Web 服务

如果 Windows 阻止运行 `.ps1`，优先使用 `start.bat`。

### 方式二：PowerShell 启动

```powershell
.\start.ps1
```

指定端口：

```powershell
.\start.ps1 -Port 8788
```

### 方式三：手动启动

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
uv run ficframe serve --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787
```

依赖源已经在 `pyproject.toml` 中配置为清华 PyPI 镜像：

```toml
[[tool.uv.index]]
name = "tuna"
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

## Web 使用流程

1. 打开 Web 页面。
2. 点击顶部“API 管理”，配置 LLM、图片、VLM 供应商。
3. 上传小说 Markdown 或 TXT。
4. 上传人物 Markdown 或 TXT。
5. 上传人设参考图。
6. 在“参考图绑定”表里确认每张图对应哪个角色。
7. 设置分镜数量和图片尺寸。
8. 点击“生成分镜”。
9. 检查或修改每个分镜的 prompt。
10. 点击“生成图片”或“生成全部”。
11. 可选：上传生成图做 VLM 质检。
12. 点击“导出小说 MD”，得到插入图片后的完整小说 Markdown。
13. 遇到问题时点击顶部“导出日志”，把 zip 日志包附在 issue 里。

导出的文件会保存到：

```text
outputs/web-runs/<run_id>/illustrated_novel.md
```

图片会保存到：

```text
outputs/web-runs/<run_id>/images/
```

导出的 Markdown 使用相对图片路径，例如：

```markdown
![shot_01](images/shot_01.png)
```

## API 供应商配置

FicFrame 把 LLM、图片模型和 VLM 分开配置。它们可以使用完全不同的请求地址、API key 和模型。

Web 中的“API 管理”支持：

- 添加多个供应商
- 删除供应商
- 切换当前使用的 LLM / 图片 / VLM
- 为每个供应商维护多个“模型昵称”
- 测试供应商是否可达
- 为图片供应商设置 steps、guidance、batch、watermark 等参数

供应商配置会保存到：

```text
.ficframe/providers.json
```

这个文件可能包含 API key，已经被 `.gitignore` 忽略。请不要把 `.env` 或 `.ficframe/providers.json` 提交到公开仓库。

保存当前供应商后，FicFrame 也会同步写入 `.env`，以保证命令行和旧接口继续可用。

### `.env` 示例

复制 `.env.example` 为 `.env`，也可以直接在 Web 中配置。

```env
FICFRAME_LLM_API_KEY=sk-your-llm-key
FICFRAME_LLM_BASE_URL=https://api.openai.com/v1
FICFRAME_LLM_MODEL=gpt-5-mini

FICFRAME_IMAGE_API_KEY=sk-your-image-key
FICFRAME_IMAGE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
FICFRAME_IMAGE_PROVIDER=ark
FICFRAME_IMAGE_MODEL=doubao-seedream-5-0-260128

FICFRAME_VLM_API_KEY=sk-your-vlm-key
FICFRAME_VLM_BASE_URL=https://api.openai.com/v1
FICFRAME_VLM_MODEL=gpt-5-mini
```

没有配置 API key 时，Web 仍然可以生成本地分镜和 prompt；LLM 增强、生图、VLM 质检会分别提示缺少对应 key。

## 日志与问题反馈

FicFrame 会把服务端日志写入：

```text
outputs/logs/
```

主要文件：

| 文件 | 说明 |
| --- | --- |
| `ficframe.log` | 普通运行日志，请求状态、分镜流程、生图流程 |
| `errors.log` | 警告和异常日志，适合排查失败原因 |
| `ficframe-logs-*.zip` | 从 Web 导出的日志包 |

Web 顶部有“导出日志”按钮。日志包中包含：

- 脱敏后的诊断信息
- 最近日志文件
- 当前 run 的 `pipeline.json`、`storyboard.md`、`prompts.md`、`continuity.json`

日志会尽量避免记录 API key 和完整 prompt。公开反馈前仍建议快速检查 zip 内容，确认没有你不想公开的小说正文或设定细节。

### 支持的图片供应商类型

| 类型 | 用途 | 说明 |
| --- | --- | --- |
| `openai` | OpenAI 兼容图片接口 | 适合兼容 `/images/generations` 或 `/images/edits` 的网关 |
| `ark` | 火山 Ark / 豆包图片接口 | 使用 `/images/generations`，支持 `size=2K` 等参数 |
| `siliconflow` | 硅基流动图片接口 | 使用 `image_size`、`num_inference_steps`、`guidance_scale` |
| `grsai` | Grsai 图片接口 | 参考图会作为 data URL 放入 `images` 字段 |

如果供应商是 OpenAI 兼容网关，通常只需要替换请求地址、API key 和模型名。

## 人物文件和参考图

人物 Markdown 可以写角色简介、外貌、服装、固定标志物、禁止变化项等信息。示例见：

```text
人物示例.md
```

人设参考图有两种使用方式：

1. 在 Web 上传图片，并在“参考图绑定”表中选择角色。
2. 在人物 Markdown 中写图片链接。

Markdown 示例：

```markdown
## 多萝西

- 身份：主角
- 外貌：银白长发，红色眼睛，黑色斗篷
- 禁止变化：发色不能变，眼睛必须是红色

![多萝西参考图](references/dorothy_front.png)
```

Web 上传参考图时，FicFrame 会根据文件名尝试自动匹配角色。例如：

```text
多萝西_正面.png
多萝西_服装.png
艾琳_表情.png
```

最终以“参考图绑定”表里的选择为准。

## 命令行用法

跑完整流水线：

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run ficframe run --novel "小说示例.md" --characters "人物示例.md" --out "outputs/demo"
```

启用 LLM 增强：

```powershell
uv run ficframe run --novel "小说示例.md" --characters "人物示例.md" --out "outputs/demo" --use-llm
```

只分析小说场景：

```powershell
uv run ficframe segment --novel "小说示例.md" --characters "人物示例.md"
```

只抽取角色卡：

```powershell
uv run ficframe characters --characters "人物示例.md"
```

启动 Web：

```powershell
uv run ficframe serve --host 127.0.0.1 --port 8787
```

命令行输出目录通常包含：

| 文件 | 说明 |
| --- | --- |
| `pipeline.json` | 完整结构化结果 |
| `storyboard.md` | 分镜表 |
| `prompts.md` | 每张图的正向 / 负向 prompt |
| `continuity.json` | 角色和场景连续性记忆 |

## 项目目录

```text
.
├─ ficframe/                  # Python 后端和核心流水线
│  ├─ api.py                  # FastAPI Web API
│  ├─ characters.py           # 人物 Markdown 解析
│  ├─ cli.py                  # 命令行入口
│  ├─ config_store.py         # .env 和供应商配置读写
│  ├─ continuity.py           # 连续性状态
│  ├─ llm_pipeline.py         # LLM 增强分镜和 prompt
│  ├─ models.py               # 数据模型
│  ├─ pipeline.py             # 命令行完整流水线
│  ├─ providers.py            # LLM / 图片 / VLM API 适配
│  ├─ render.py               # Markdown 导出
│  ├─ segmenter.py            # 小说切段
│  └─ storyboard.py           # 分镜生成
├─ web/                       # Web 前端
│  ├─ index.html              # 页面结构
│  ├─ app.js                  # 前端交互逻辑
│  ├─ styles.css              # 页面样式
│  └─ tokens.css              # 设计变量
├─ outputs/                   # 运行输出，默认不提交
│  ├─ logs/                    # 应用日志和导出的日志包
│  └─ web-runs/                # Web 每次运行的分镜、图片和导出小说
├─ .ficframe/                 # 本地供应商配置，默认不提交
├─ .env                       # 本地 API key，默认不提交
├─ .env.example               # 环境变量示例
├─ pyproject.toml             # 项目和 uv 配置
├─ uv.lock                    # 依赖锁定文件
├─ start.bat                  # Windows 一键启动脚本
├─ start.ps1                  # PowerShell 启动脚本
├─ 小说示例.md                # 小说输入示例
└─ 人物示例.md                # 人物输入示例
```

## 常见问题

### 1. `uv` 命令不存在

需要先安装 uv。安装方式见 uv 官方文档：

```text
https://docs.astral.sh/uv/
```

安装后重新打开终端，再运行 `start.bat`。

### 2. 端口 `8787` 被占用

PowerShell 启动时可以换端口：

```powershell
.\start.ps1 -Port 8788
```

也可以手动停止占用端口的进程：

```powershell
netstat -ano | Select-String ':8787'
Stop-Process -Id <PID> -Force
```

### 3. 图片生成失败，提示图片尺寸不支持

不同供应商支持的尺寸不同。比如部分 Ark 图片模型要求至少 2K。可以在 Web 左侧“图片尺寸”里选择 `2K`，或填写自定义尺寸，例如：

```text
2048x2048
```

### 4. 人设参考图没有生效

请检查：

- 参考图是否已经上传
- “参考图绑定”表里是否绑定到了正确角色
- 当前分镜中是否出现了该角色
- 当前图片供应商是否支持参考图输入

目前 `grsai`、`ark` 和 OpenAI 兼容的编辑接口会尝试发送参考图。某些供应商虽然接口兼容，但模型本身可能不强遵循参考图。

### 5. 导出的 Markdown 里图片打不开

导出的小说 Markdown 位于：

```text
outputs/web-runs/<run_id>/illustrated_novel.md
```

请保持它和同目录下的 `images/` 文件夹相对位置不变。

## 开发

安装依赖：

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
```

编译检查：

```powershell
uv run python -m compileall ficframe
node --check web/app.js
```

开发模式启动：

```powershell
uv run ficframe serve --host 127.0.0.1 --port 8787 --reload
```

## 安全说明

FicFrame 是本地应用，但当你启用 LLM、生图或 VLM 功能时，小说正文、人物设定、prompt、参考图或生成图可能会被发送到你配置的第三方 API。请确认你使用的供应商和模型符合自己的隐私要求。

默认不会提交以下本地文件：

```text
.env
.ficframe/
outputs/
.venv/
.uv-cache/
```

## License

开源前请在仓库中补充你选择的许可证文件，例如 MIT、Apache-2.0 或其他许可证。
