# FicFrame

FicFrame 是一套本地运行的小说配图工具集，目标是把二创小说、人物设定和人设参考图整理成可以持续迭代的图文生成流程。

它可以帮你完成：

- 解析小说章节，把正文切分成适合出图的剧情段落
- 从人物 Markdown 中抽取角色卡、人设特征和参考图信息
- 分析相似角色的混淆风险，自动生成角色差异约束
- 使用 VLM 提取参考图中的稳定视觉事实
- 生成可复用的角色 identity prompt 和外貌状态计划
- 按章节均衡生成分镜、图片 prompt 和连续性提示
- 在 Web 中绑定“角色 ↔ 参考图”，一个角色可以绑定多张图
- 管理多套 LLM / VLM / 图片 API 供应商
- 调用图片模型生成单张或批量图片
- 导出“已经插入配图的完整小说 Markdown”
- 从 Web 一键导出脱敏日志包，方便反馈 bug

FicFrame 适合想把长篇小说做成图文版、分镜版、视频前期素材或角色一致性生图素材的创作者。

## 预览

![预览](pic/image.png)

目前 Web 是一个本地工作台，主要包含：

- 左侧：小说、人物文件、人设参考图、参考图绑定表、分镜数量、图片尺寸
- 中间：分镜列表
- 右侧：当前分镜 prompt、图片预览、批量生成、导出小说 MD
- 顶部 API 管理：供应商列表、请求地址、API key、模型昵称、可达性测试

## 快速开始

### 方式一：Windows 双击启动

双击项目根目录下的：

```text
start.bat
```

脚本会自动：

- 进入项目目录
- 如果已安装 uv，则使用 uv 管理环境
- 如果没有 uv，则自动使用 Python venv + pip
- pip 和 uv 都默认使用清华 PyPI 镜像
- 如果没有 `.env`，从 `.env.example` 复制一份
- 安装或检查依赖
- 打开浏览器访问 `http://127.0.0.1:8787`
- 启动 FicFrame Web 服务

普通 Windows 用户优先使用 `start.bat`。如果 Windows 阻止运行 `.ps1`，也优先使用 `start.bat`。

### 方式二：PowerShell 启动

```powershell
.\start.ps1
```

指定端口：

```powershell
.\start.ps1 -Port 8788
```

### 方式三：macOS / Linux 启动

```bash
chmod +x ./start.sh
./start.sh
```

指定端口：

```bash
FICFRAME_PORT=8788 ./start.sh
```

`start.sh` 会优先使用 uv；如果没有 uv，会自动使用 Python venv + pip。

### 方式四：手动启动

使用 uv：

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
uv run ficframe serve --host 127.0.0.1 --port 8787
```

不使用 uv，只用 Python + pip：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m ficframe.cli serve --host 127.0.0.1 --port 8787
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

如果使用 `requirements.txt`，请在 pip 命令里加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，或自行配置 pip 全局镜像。

## Web 使用流程

1. 打开 Web 页面。
2. 点击顶部“API 管理”，配置 LLM、VLM 和图片供应商。
3. 上传小说 Markdown 或 TXT。
4. 上传人物 Markdown 或 TXT。
5. 上传人设参考图。
6. 在“参考图绑定”表里确认每张图对应哪个角色。
7. 设置分镜数量和图片尺寸。
8. 点击“生成分镜”。
9. 检查或修改每个分镜的 prompt。
10. 点击“生成图片”或“生成全部”。
11. 批量生成时可以勾选“跳过已有图片”，用于断点续跑。
12. 如果部分图片失败，调整“失败重试次数”后点击“重试失败”。
13. 点击“导出小说 MD”，得到插入图片后的完整小说 Markdown。
14. 遇到问题时点击顶部“导出日志”，把 zip 日志包附在 issue 里。

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

## 本地规则与 Token 控制

Web 左侧有“查看本地规则”按钮。整理输入时尽量符合这些规则，可以在不开 LLM 增强的情况下得到更稳定的角色识别、章节切分和基础 prompt，从而减少 token 消耗。

推荐策略：

- 首次整理新作品时，可以先关闭 LLM，按本地规则检查角色和分镜是否基本正确。
- 如果角色文档格式复杂、人物很多、章节场景很隐晦，再打开 LLM 增强。
- 如果只是补漏单个角色，优先用 Web 的“手动添加角色”，不必重新消耗 LLM token。
- 如果本地分镜已经覆盖均衡，只需要更精致的英文 prompt，可以只在必要分镜上手动编辑或重建 prompt。

本地规则主要依赖明确文本信号：

| 模块 | 本地规则偏好的输入 |
| --- | --- |
| 人物识别 | `## 角色名`、单独一行角色名、`角色名：本名/代号...`、`角色总览/人物总览` 后的角色简介 |
| 人物字段 | 身份、外貌、性格、固定、禁止变化、道具、关系、别名、代号 |
| 章节识别 | `# 第一章`、`第二章`、`第三卷`、`第四幕`、`Chapter 1` |
| 分镜角色 | 段落中直接出现角色名或别名 |
| 场景信息 | 段落中写清地点、时间、情绪、动作和关键道具 |
| 参考图 | 文件名包含角色名，或在“参考图绑定”表中手动选择角色 |

## API 供应商配置

FicFrame 把 LLM、VLM 和图片模型分开配置。它们可以使用完全不同的请求地址、API key 和模型。

Web 中的“API 管理”支持：

- 添加多个供应商
- 删除供应商
- 切换当前使用的 LLM / VLM / 图片供应商
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
FICFRAME_TIMEOUT=300
FICFRAME_IMAGE_TIMEOUT=900

FICFRAME_VLM_API_KEY=sk-your-vlm-key
FICFRAME_VLM_BASE_URL=https://api.openai.com/v1
FICFRAME_VLM_PROVIDER=openai
FICFRAME_VLM_MODEL=gpt-5-mini

FICFRAME_IMAGE_API_KEY=sk-your-image-key
FICFRAME_IMAGE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
FICFRAME_IMAGE_PROVIDER=ark
FICFRAME_IMAGE_MODEL=doubao-seedream-5-0-260128

```

没有配置 API key 时，Web 仍然可以生成本地分镜和 prompt；LLM 增强、VLM 参考图分析和生图会分别使用各自配置。VLM 没有配置时会跳过参考图视觉提取，不影响普通流程。

`FICFRAME_TIMEOUT` 是普通第三方 API 请求超时时间，单位为秒。`FICFRAME_IMAGE_TIMEOUT` 是图片生成和图片下载的超时时间，默认更长，因为图片模型经常需要排队。图片模型排队较久时可以调大，例如 `1200`。

## 示例

仓库提供两组示例：

| 路径 | 用途 |
| --- | --- |
| `examples/minimal/` | 极短 demo，适合首次验证安装和分镜流程 |

快速跑最小示例：

```powershell
uv run ficframe run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/minimal-demo" --max-shots 3
```

不使用 uv：

```powershell
.\.venv\Scripts\python.exe -m ficframe.cli run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/minimal-demo" --max-shots 3
```

Web 中也可以直接上传 `examples/minimal/novel.md` 和 `examples/minimal/characters.md`。

## 失败重试与断点续跑

批量生图容易受到网络、限流、尺寸参数或供应商状态影响。FicFrame 做了几件事来减少重复工作：

- “跳过已有图片”：再次批量生成时，已经存在的 `images/<shot_id>.png` 不会重复请求模型。
- “失败重试次数”：每张失败图片会按设置自动重试。
- “重试失败”：只对当前没有图片的分镜重新发起请求。
- Web 的“生成全部”会逐张请求、逐张返回；每完成一张图片就会立刻刷新预览和分镜状态。
- `image_results.json`：每次批量生成结果会写入 run 目录，方便查看失败原因。

## 刷新恢复

Web 会尽量避免因为误刷新丢失慢生成出来的分镜和 prompt：

- 分镜、角色 Prompt Bank、用户手动修改过的 prompt、图片状态会自动保存到浏览器 `localStorage`。
- 刷新页面后会优先恢复浏览器草稿，并回到刷新前选中的分镜。
- 如果浏览器草稿不存在，顶部“恢复最近”会从 `outputs/web-runs/<run_id>/pipeline.json` 读取最近一次 Web 运行结果。
- 每次 Web 生成分镜都会写入 `pipeline.json`，即使后续图片还没全部完成，也可以从该文件恢复分镜。

注意：浏览器草稿只保存在当前浏览器和当前站点地址下。换浏览器、清理站点数据或更换端口后，可以使用“恢复最近”从后端输出目录恢复。

## 分镜规则

FicFrame 会先识别小说里已有的章节标题，再把每章正文切成适合生图的剧情段落。

当前支持的章节标题包括：

- Markdown 标题：`# 第一章`、`## 第二章`
- 中文章节：`第一章`、`第十二节`、`第三卷`、`第四幕`
- 英文章节：`Chapter 1`、`CHAPTER 2`

生成分镜时不会简单地从全文前面开始取，也不会只按“画面优先级”全局排序。它会先按章节数量和每章段落数量分配镜头额度，再在每个章节内部按剧情位置分桶，优先选择更适合画面的段落。这样长篇小说的前、中、后段都会有镜头覆盖。

结果文件位置：

```text
outputs/web-runs/<run_id>/image_results.json
```

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

更多隐私和内容边界说明见 [SECURITY.md](SECURITY.md)。

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
examples/minimal/characters.md
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

### 角色识别方式

FicFrame 会先用本地规则识别人物 Markdown。规则支持 Markdown 标题、`角色名：本名/代号...`、单独一行角色名加简介，以及 `角色总览/人物总览` 后的长人设写法。

如果勾选“LLM 增强”，FicFrame 会让 LLM 阅读整份人设文档，辅助拆分多个人物并提取角色卡。LLM 会尽量避免把“能力设定”“人际关系”“事件经历”“创作建议”等小节误当成新角色。

Web 左侧把这几类动作拆开了：

- `识别角色`：只走本地规则。
- `LLM拆分人设`：只做人设拆分。
- `LLM增强人设`：在当前角色上做语义增强。
- `生成Prompt Bank`：只生成或刷新角色的 identity prompt 和外貌状态计划。
- `LLM差异分析`：只分析角色差异。

如果 LLM 未配置或调用失败，界面会显示回落状态。

Web 左侧还提供“手动添加角色”按钮。当自动识别漏掉角色时，点击按钮展开表单，填写角色名和描述手动补充；手动角色会参与参考图绑定、分镜角色识别、Prompt Bank 生成和后续生图。

## 角色差异分析器

人物预览和生成分镜时，FicFrame 会自动分析角色之间的混淆风险。它会比较角色的身份、气质、外观、道具和关系信息，找出容易被生图模型画混的角色组合。

分析结果会用于两处：

- Web 左侧“角色差异分析”：显示高风险角色对、共享特征和各自需要强化的差异点。
- 分镜 prompt：自动加入角色差异约束，例如不同发型、眼神、姿态、道具、情绪功能，以及对应的负面词。

这对双胞胎、姐妹、同职业、同服装、同阵营角色尤其有用。建议在人物 Markdown 中明确写出每个角色的“不能被混同的差异”，例如：

```text
林澈：妹妹，机械工程师，行动派，锐利眼神，短发，数据板，工程工具。
林岚：姐姐，天文研究者，优雅温柔，长发，咖啡，安静观察。
```

如果启用了 LLM 增强，角色差异分析器会优先让 LLM 阅读人设文档并提取语义差异；如果未配置 LLM 或调用失败，则回落到本地规则分析。

## Prompt Bank 与 VLM

生成分镜时，FicFrame 会为每个角色生成一份可复用的 Prompt Bank：

- `identity_prompt`：角色固定身份、外貌、体型、核心气质和参考图视觉事实。
- `negative_identity_prompt`：防止角色漂移、同脸、错服装、错身份的负面词。
- `appearance_states`：外貌状态计划，例如默认服装、任务后疲惫、受伤、换装、携带特定道具等。

如果配置了 VLM，并且上传了参考图，VLM 只负责提取参考图中的稳定视觉事实，例如发型、发色、眼睛、服装轮廓、标志物和不确定项。它不会直接决定最终 prompt，也不会替代人设文档。

如果同时启用了 LLM 增强，LLM 会合并人设文档、VLM 提取的参考图视觉事实，以及小说场景中的外貌变化线索，判断角色外貌状态是否需要变化、变化几次，并生成更短、更稳定的生图 prompt。没有明确变化时，每张图会复用同一个 `identity_prompt`，只替换当前分镜的动作、表情、道具和场景。

Web 右侧可以直接编辑当前角色的 `identity_prompt`、`appearance_states` 和 `negative_identity_prompt`。这些修改不会因为切换分镜丢失；也可以点击“恢复角色原文”回到本次生成后的初始文本。

## 命令行用法

跑完整流水线：

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv run ficframe run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/demo"
```

启用 LLM 增强：

```powershell
uv run ficframe run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/demo" --use-llm
```

只分析小说场景：

```powershell
uv run ficframe segment --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md"
```

只抽取角色卡：

```powershell
uv run ficframe characters --characters "examples/minimal/characters.md"
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
│  ├─ prompt_bank.py          # 角色 identity prompt 和外貌状态计划
│  ├─ providers.py            # LLM / VLM / 图片 API 适配
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
├─ examples/                  # 可公开运行的示例输入
├─ docs/screenshots/          # README 和发布页截图
├─ LICENSE                    # MIT License
├─ SECURITY.md                # 隐私、日志和内容边界说明
├─ pyproject.toml             # 项目配置和 uv 依赖入口
├─ requirements.txt           # pip / conda / 其他环境管理器可用的运行依赖
├─ uv.lock                    # 依赖锁定文件
├─ start.bat                  # Windows 一键启动脚本
├─ start.ps1                  # PowerShell 启动脚本
└─ start.sh                   # macOS / Linux 启动脚本
```

## 常见问题

### 1. `uv` 命令不存在

先直接运行 `start.bat`。启动脚本会检查 uv 是否存在；如果没有，会自动改用 Python venv + pip。

如果你想安装 uv，可以用：

```powershell
winget install --id astral-sh.uv -e
```

如果系统没有 winget，或自动安装失败，再按 uv 官方文档手动安装：

```text
https://docs.astral.sh/uv/
```

安装后重新打开终端，再运行 `start.bat`。

### 2. 没有 uv，也不想安装 uv

可以，只要有 Python 3.10+ 即可：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m ficframe.cli serve --host 127.0.0.1 --port 8787
```

### 3. 端口 `8787` 被占用

PowerShell 启动时可以换端口：

```powershell
.\start.ps1 -Port 8788
```

也可以手动停止占用端口的进程：

```powershell
netstat -ano | Select-String ':8787'
Stop-Process -Id <PID> -Force
```

### 4. 图片生成失败，提示图片尺寸不支持

不同供应商支持的尺寸不同。比如部分 Ark 图片模型要求至少 2K。可以在 Web 左侧“图片尺寸”里选择 `2K`，或填写自定义尺寸，例如：

```text
2048x2048
```

### 5. 图片生成失败，提示请求超时

生图服务排队、网络代理或模型响应慢时，可能出现请求超时。可以在 `.env` 中调大：

```env
FICFRAME_IMAGE_TIMEOUT=1200
```

批量生图时，超时会记录为单张图片失败，不会让整个批量接口变成 500。可以稍后点击“重试失败”继续。

### 6. 人设参考图没有生效

请检查：

- 参考图是否已经上传
- “参考图绑定”表里是否绑定到了正确角色
- 当前分镜中是否出现了该角色
- 当前图片供应商是否支持参考图输入

目前 `grsai`、`ark` 和 OpenAI 兼容的编辑接口会尝试发送参考图。某些供应商虽然接口兼容，但模型本身可能不强遵循参考图。

### 7. 导出的 Markdown 里图片打不开

导出的小说 Markdown 位于：

```text
outputs/web-runs/<run_id>/illustrated_novel.md
```

请保持它和同目录下的 `images/` 文件夹相对位置不变。

## 开发

推荐使用 uv 安装依赖：

```powershell
$env:UV_CACHE_DIR=".uv-cache"
uv sync
```

也可以使用 pip：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

编译检查：

```powershell
uv run python -m compileall ficframe
node --check web/app.js
```

如果使用 pip 环境：

```powershell
.\.venv\Scripts\python.exe -m compileall ficframe
node --check web/app.js
```

开发模式启动：

```powershell
uv run ficframe serve --host 127.0.0.1 --port 8787 --reload
```

## 安全说明

FicFrame 是本地应用，但当你启用 LLM 或生图功能时，小说正文、人物设定、prompt、参考图或生成图可能会被发送到你配置的第三方 API。请确认你使用的供应商和模型符合自己的隐私要求。详见 [SECURITY.md](SECURITY.md)。

默认不会提交以下本地文件：

```text
.env
.ficframe/
outputs/
.venv/
.uv-cache/
```

## License

FicFrame is released under the MIT License. See [LICENSE](LICENSE).
