# FicFrame 常见问题

- [返回 README](../README.md)
- [Windows 与 Linux 发布包](distribution.md)
- [ComfyUI 使用指南](comfyui.md)

## 启动与环境

### 安装版需要 Python 或 uv 吗？

不需要。Windows `Setup.exe`、Windows 便携 ZIP、Linux `.run` 和 Linux `.tar.gz` 都已经内置 Python 与运行依赖。Python/uv 只用于从源码开发和构建发布包。

### 安装版的数据保存在哪里？

所有持续增长的数据都保存在用户选择的安装目录：

```text
<安装目录>/data/
├── .env
├── .ficframe/
└── outputs/
```

因此可以把 FicFrame 安装在其他磁盘。Windows 仍会为安装临时文件、快捷方式和卸载登记使用少量系统盘空间，但程序主体、日志和生成结果都留在目标目录。

### 如何升级、迁移或卸载？

- 升级：新版本安装到原目录即可，安装器不会主动覆盖 `data/`。
- 迁移：关闭 FicFrame 后复制整个安装目录，或至少复制 `data/`。
- 卸载：Windows 卸载器默认保留非空的 `data/`；确认不再需要后可手动删除。Linux 关闭程序后直接删除安装目录即可。
- 便携 ZIP / tar.gz：解压新版本时保留原来的 `data/`，不要把旧程序运行中的目录直接覆盖。

API key 保存在 `data/.env` 和 `data/.ficframe/providers.json`，迁移文件时请按敏感信息处理。

### Windows 提示 SmartScreen 怎么办？

未签名的测试安装包可能触发 SmartScreen。应确认安装包来自项目的正式 Releases 页面；如果发布者提供了校验值，也应一并核对。公开分发版本建议使用代码签名证书。

### Linux 安装后无法运行

先确认执行权限：

```bash
chmod +x FicFrame-<版本>-linux-x86_64.run
chmod +x /目标目录/FicFrame
```

Linux 构建依赖 glibc。若系统版本明显早于构建环境，建议在兼容的发行版上重新构建，或使用项目 CI 基于 Ubuntu 22.04 生成的包。

### Linux 压缩包里为什么是 EXE？

先区分文件类型：Linux 主程序本身也是“可执行文件”，文件管理器可能把它显示为 executable，这是正常的。正确文件名是 `FicFrame`，没有 `.exe` 后缀，执行以下命令应看到 `ELF 64-bit`：

```bash
file FicFrame
```

如果文件名是 `FicFrame.exe`，或者 `file` 显示 `PE32` / `PE32+`，说明压缩包是在 Windows、Git Bash 或 Windows Python 环境中错误构建的。PyInstaller 不支持交叉编译。请使用 GitHub Actions 的 Linux artifact，或在原生 Linux/Linux 虚拟机中重新运行 `bash scripts/build_linux.sh`。新版构建脚本会拒绝产生这种误标包。

### 从源码运行但没有 uv 怎么办？

直接运行 `start.bat`。脚本检测不到 `uv` 时，会自动使用 Python `venv + pip`。

手动安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 端口 8787 被占用

安装版会从 8787 开始自动寻找可用端口，并打开实际地址，一般不需要手动处理。源码运行时可以换一个端口：

```powershell
.\start.ps1 -Port 8788
```

查看占用进程：

```powershell
netstat -ano | Select-String ':8787'
```

确认 PID 后再停止对应进程：

```powershell
Stop-Process -Id <PID> -Force
```

### 页面能打开，但健康检查失败

检查后端终端和错误日志：

- 安装版：`<安装目录>/data/outputs/logs/errors.log`
- 源码运行：`outputs/logs/errors.log`

如果刚修改了 `.env` 或供应商配置，重新启动 FicFrame 后再测试。

### 如何关闭 FicFrame？

关闭 FicFrame 启动窗口，或在窗口内按 `Ctrl+C`。只关闭浏览器标签页不会停止本地后端。

## LLM 与 API

### DeepSeek 为什么没有显示思考过程？

这是预期行为。FicFrame 会让 DeepSeek 使用高强度思考，但解析时只保留最终回答，主动过滤 Responses 格式的 `reasoning` / `reasoning_text` 和 Chat 格式的 `reasoning_content`，避免它们混入结构化 JSON。

DeepSeek 会优先请求 `/responses`。只有服务端返回明确的接口错误时才回退 `/chat/completions`；超时、连接失败、鉴权失败或限流不会回退，避免同一任务被重复提交。

结构化任务会使用 DeepSeek Responses API 的 `text.format=json_object` 模式。由于 `max_output_tokens` 同时计算推理与最终回答，FicFrame 会为长 JSON 设置独立上限；服务端返回 `incomplete` 时会保留本地结果并显示明确原因。

### 为什么恢复分镜或 Prompt 后没有新增历史版本？

分镜历史按不含图片字段的完整文本快照去重。恢复前的当前内容尚未出现在历史中时，系统会先归档，便于之后撤销；如果相同内容已经存在，则复用已有历史，不再制造一模一样的版本。图片和图片版本不参与文本快照比较，也不会因恢复操作被覆盖。

## 发布

### PR 合并后为什么没有自动创建 Release？

这是预期行为。PR 和合并到 `main` 都不会自动发布，以免每次合并都创建新版本。正式发布需要进入 Actions 页面手动运行 `Build release packages`，选择 `main` 并输入不带 `v` 的版本号。

发布失败时检查：

1. `pyproject.toml`、`ficframe/__init__.py` 和 `uv.lock` 的版本是否一致。
2. Actions 中输入的版本是否与项目版本完全一致。
3. 运行工作流时选择的分支是否为 `main`。
4. 远端是否已经存在同名 `v<版本>` 标签。
5. 仓库 Actions 是否允许工作流使用 `contents: write` 创建标签和 Release。
6. `Build release packages` 的 `prepare`、`windows`、`linux` 和 `release` 四个 job 是否全部成功。

工作流成功后会自动创建标签，不需要手动执行 `git tag`。完整操作见 [自动发布](distribution.md#自动发布)。

### 打包时下载依赖出现 403

如果日志显示从 PyPI 镜像下载 `anyio` 等依赖时返回 `403 Forbidden`，说明依赖源拒绝了 GitHub runner 的请求，并不表示 PyInstaller 构建逻辑或输入的版本号有错。

当前发布工作流会在 GitHub 的临时 runner 中使用官方 PyPI，同时保留 `uv.lock` 锁定的版本和哈希；本地源码环境仍可使用项目配置的清华镜像。工作流修复必须提交并推送后，从对应的新 commit 发起新运行；重新运行旧 job 不会加载后来修改的工作流。

## 图片生成

### 图片尺寸不支持

不同供应商支持的尺寸不同。可以选择 Web 预设，或填写供应商支持的自定义尺寸：

```text
2048x2048
2K
```

ComfyUI API 工作流通常要求 `宽x高`，例如 `1024x1024`。云端供应商是否支持 `2K` 取决于对应 API。

### 生成图片超时

图片模型排队或本地首次加载较久时，可在安装版的 `data/.env` 或源码根目录的 `.env` 中调大：

```env
FICFRAME_IMAGE_TIMEOUT=1200
```

ComfyUI 用户还应检查队列是否仍在运行，以及终端中是否有显存不足或节点错误。

### 参考图没有生效

依次检查：

1. 参考图是否在 Web 中绑定到正确角色。
2. 当前分镜的 `characters` 是否包含该角色。
3. 当前图片供应商和模型是否支持参考图。
4. ComfyUI 是否导入了 IP-Adapter 动态工作流，而不是基础文生图工作流。
5. IP-Adapter 和 CLIP Vision 权重是否放在正确目录。
6. 权重是否过低，或生效区间是否太短。

基础 `ficframe_sdxl_api.json` 不使用参考图，这是预期行为。

### 多名角色的脸或服装互相污染

使用 [动态 IP-Adapter 工作流](comfyui.md#案例二ip-adapter-角色一致性)。完整 LLM 模式会优先生成角色区域；没有布局时使用平均分区回退。

参考图应尽量满足：

- 每张图主体明确，少用多人合照。
- 同一角色的多张图保持发型、年龄和基础服装逻辑一致。
- 避免把风格差异极大的图片绑定到同一个角色。

### 重新生成后为什么没有替换当前图片？

已有当前图时，新图会保存为候选版本。请在 Web 的图片版本区域点击 `设为当前`。这是为了避免重生成直接覆盖满意结果。

## ComfyUI

### Desktop 用户应该填写 E 盘目录还是 URL？

最终保存的必须是 HTTP URL。可以先把 Desktop 安装向导中选择的数据目录（包含 `models`、`input`、`output`、`user`）临时填入 `服务地址（HTTP）`，然后点击 `测试可达性`。FicFrame 检测成功后会把输入框替换为 Desktop 当前使用的地址，再保存供应商。

Desktop 默认从 `8000` 开始寻找空闲端口，所以实际地址可能是 `http://127.0.0.1:8000`、`8001` 或其他后续端口。不要直接保存 `E:\ComfyUI`，也不要把 checkpoint 的磁盘路径填入模型 ID。

详细步骤见 [ComfyUI Desktop 操作步骤](comfyui.md#comfyui-desktop-操作步骤)。

### FicFrame 无法连接 ComfyUI

确认：

- ComfyUI 已启动，并且其 HTTP 地址能在浏览器中打开。CLI 默认使用 `http://127.0.0.1:8188`；Desktop 默认从 `8000` 开始，端口被占用时会自动递增选择。
- FicFrame 中填写的是根地址，不要附加 `/prompt`。
- `E:\ComfyUI`、`G:\ComfyUI` 等 Desktop 数据目录只能临时用于自动探测，最终保存值必须是探测后回填的 HTTP 地址。
- ComfyUI 和 FicFrame 不在同一台机器时，ComfyUI 已监听局域网地址且防火墙允许访问。
- HTTPS 代理或鉴权代理配置正确。

Desktop 用户还应保持 Desktop 窗口运行，并检查 `%APPDATA%\ComfyUI\logs\comfyui_*.log` 中的实际监听地址和启动错误。

### 导入工作流后提示“不是 API 格式”

需要在 ComfyUI 中使用 `导出（API）`，不是普通的 `保存`。API JSON 顶层通常是节点 ID 到节点输入的映射。

仓库自带的 `examples/comfyui/*.json` 已经可以直接导入 FicFrame。

### 提示 checkpoint 或模型不存在

FicFrame 的模型 ID 必须与 ComfyUI 中显示的完整文件名一致，包括子目录和扩展名，例如：

```text
Illustrious-XL-v0.1.safetensors
```

放入 `models/checkpoints/` 后刷新 ComfyUI 模型列表，必要时重启 ComfyUI。

### 提示 IPAdapter、Encoder 或 FeatherMask 节点不存在

确认已安装 `ComfyUI_IPAdapter_plus`，然后重启 ComfyUI。动态示例需要以下节点：

```text
IPAdapterUnifiedLoader
IPAdapterEncoder
IPAdapterCombineEmbeds
IPAdapterEmbeds
SolidMask
MaskComposite
FeatherMask
```

节点版本太旧时，请更新插件并重新启动。

### IP-Adapter 权重或 CLIP Vision 模型找不到

检查文件位置：

```text
ComfyUI/models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors
ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors
```

文件名和模型架构必须匹配当前工作流。SDXL checkpoint 应使用对应的 SDXL IP-Adapter 权重。

### ComfyUI 显存不足

按以下顺序降低负载：

1. 降低图片分辨率。
2. 减少当前分镜参与约束的参考图数量。
3. 降低批量生成并发。
4. 关闭其他占用显存的程序。
5. 使用 ComfyUI 的低显存启动参数或更适合本机的模型。

FicFrame 不限制角色和参考图数量，但机器的实际资源仍然构成运行上限。

### LLM 布局会影响其他图片 API 吗？

不会。`character_layout` 和 `regional_guidance` 只供动态 ComfyUI IP-Adapter 工作流使用。OpenAI、Ark、SiliconFlow、Grsai 和普通 ComfyUI API 工作流继续使用原来的 Prompt、尺寸和参考图接口。

### 没有配置 LLM 时，多角色怎么布局？

动态 IP-Adapter 工作流会按分镜角色顺序从左到右平均分区。LLM 返回有效布局时才使用不等宽、可重叠区域；LLM 明确选择自由构图时不添加区域遮罩。

## 导出与日志

### 导出的 Markdown 图片打不开

请保持 `illustrated_novel.md` 和同目录下 `images/` 文件夹的相对位置不变。

### 如何反馈问题？

点击 Web 顶部的 `导出日志`，生成脱敏日志包。公开提交前仍应检查其中是否包含不希望公开的小说正文、人设或 Prompt。安全说明见 [SECURITY.md](../SECURITY.md)。
