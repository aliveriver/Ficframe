# FicFrame 常见问题

- [返回 README](../README.md)
- [ComfyUI 使用指南](comfyui.md)

## 启动与环境

### 没有 uv 怎么办？

直接运行 `start.bat`。脚本检测不到 `uv` 时，会自动使用 Python `venv + pip`。

手动安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 端口 8787 被占用

换一个端口启动：

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

检查后端终端和 `outputs/logs/errors.log`。如果刚修改了 `.env` 或供应商配置，重新启动 FicFrame 后再测试。

## 图片生成

### 图片尺寸不支持

不同供应商支持的尺寸不同。可以选择 Web 预设，或填写供应商支持的自定义尺寸：

```text
2048x2048
2K
```

ComfyUI API 工作流通常要求 `宽x高`，例如 `1024x1024`。云端供应商是否支持 `2K` 取决于对应 API。

### 生成图片超时

图片模型排队或本地首次加载较久时，可在 `.env` 中调大：

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

### FicFrame 无法连接 ComfyUI

确认：

- ComfyUI 已启动并能访问 `http://127.0.0.1:8188`。
- FicFrame 中填写的是根地址，不要附加 `/prompt`。
- ComfyUI 和 FicFrame 不在同一台机器时，ComfyUI 已监听局域网地址且防火墙允许访问。
- HTTPS 代理或鉴权代理配置正确。

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
