# FicFrame ComfyUI 使用指南

本文介绍如何把 FicFrame 接入本地 ComfyUI，包括基础 SDXL 文生图、IP-Adapter 角色一致性、多角色布局和自定义 API 工作流。

- [返回 README](../README.md)
- [查看常见问题](faq.md)

## 适用范围

FicFrame 的 ComfyUI 适配会完成以下工作：

1. 上传当前分镜涉及的角色参考图。
2. 将分镜 Prompt、尺寸、模型、Steps、CFG 和随机种子写入 API 工作流。
3. 提交工作流并轮询 ComfyUI 队列。
4. 下载指定 `SaveImage` 节点的输出。

普通云端图片供应商不会读取 ComfyUI 的工作流或遮罩字段。

## 准备工作

1. 启动 ComfyUI，确认浏览器可以访问，例如 `http://127.0.0.1:8188`。
2. 把 checkpoint 放入 `ComfyUI/models/checkpoints/`。
3. 在 FicFrame 的 `API 管理` 中新增图片供应商，选择 `ComfyUI 本地`。
4. 请求地址填写 ComfyUI 根地址；本地默认实例通常不需要 API key。
5. 模型 ID 填写 ComfyUI 中显示的 checkpoint 完整文件名。

建议先点击 `测试可达性`，确认 FicFrame 能读取 ComfyUI 状态和模型列表。

## 案例一：基础 SDXL 文生图

仓库提供只使用 ComfyUI 原生节点的 API 工作流：

```text
examples/comfyui/ficframe_sdxl_api.json
```

可直接在 FicFrame 的 `API 管理` 中导入，不需要先在 ComfyUI 中转换。

推荐起步配置：

| 配置 | 建议值 |
| --- | --- |
| 请求地址 | `http://127.0.0.1:8188` |
| 模型 ID | checkpoint 完整文件名，例如 `Illustrious-XL-v0.1.safetensors` |
| Steps | `20-24` |
| Guidance | `6` |
| 输出节点 ID | `9` |
| 轮询间隔 | `1` 秒 |
| 图片尺寸 | `1024x1024`、`832x1216` 或 `1216x832` |

操作步骤：

1. 导入 `ficframe_sdxl_api.json`。
2. 将输出节点填写为 `9`。
3. 保存并设为当前图片供应商。
4. 先生成一张 `1024x1024` 图片验证链路。

这个模板不使用角色参考图，适合验证 checkpoint、Prompt、队列和图片下载是否正常。

## 案例二：IP-Adapter 角色一致性

动态角色工作流位于：

```text
examples/comfyui/ficframe_sdxl_ipadapter_api.json
```

需要安装：

```text
ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/
ComfyUI/models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors
ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors
```

导入后，FicFrame 会按当前分镜动态生成节点：

| 输入情况 | 处理方式 |
| --- | --- |
| 没有参考图 | 使用基础 SDXL 文生图 |
| 单角色、单张参考图 | 创建一个 IP-Adapter 图像编码与身份约束 |
| 单角色、多张参考图 | 编码全部图片并合并 embedding |
| 多角色 | 为每名有参考图的角色创建独立身份约束 |

同一角色的多张参考图会以 `add` 合并正负 embedding，并按图片数量平分该角色的总权重。参考图越多不会自动造成约束成倍增强。

默认设置：

```text
preset: PLUS (high strength)
每名角色总权重: 0.3
生效区间: 0.0-0.65
embeds scaling: V only
输出节点: 9
```

角色数量和每名角色的参考图数量没有代码层面的硬上限，实际容量由显存、内存、分辨率和 ComfyUI 配置决定。

## LLM 分镜布局

完整 LLM 模式会在原有 `camera`、`composition` 和 Prompt 之外，同步生成：

```json
{
  "regional_guidance": true,
  "character_layout": [
    {
      "character": "林默",
      "position": "foreground left",
      "depth": "foreground",
      "region": [0.0, 0.0, 0.6, 1.0]
    },
    {
      "character": "苏遥",
      "position": "background right",
      "depth": "background",
      "region": [0.45, 0.1, 1.0, 0.9]
    }
  ]
}
```

`region` 是 `[left, top, right, bottom]` 格式的 `0-1` 归一化坐标。区域可以不同大小、互相重叠，用于表达前后景、对角构图和人物遮挡。

布局优先级：

1. LLM 返回有效布局：使用不等宽、可重叠的二维软 attention mask。
2. LLM 设置 `regional_guidance=false`：保留角色身份 embedding，由生图模型自由构图。
3. 未配置 LLM、快速模式或布局无效：回退为从左到右平均分区。

这部分复用原有分镜精修请求，不会额外增加一次 LLM 调用。旧分镜没有布局字段时会自动使用回退方案。

## 自定义 ComfyUI 工作流

在 ComfyUI 中完成工作流后，使用 `导出（API）` 保存 JSON。普通界面工作流 JSON 不能直接提交。

FicFrame 支持下列占位符：

| 占位符 | 注入内容 |
| --- | --- |
| `{{prompt}}` | 当前分镜正向 Prompt |
| `{{negative_prompt}}` | 当前分镜负向 Prompt 与图片供应商默认负向 Prompt 的合并结果 |
| `{{width}}` / `{{height}}` | Web 中选择的图片宽高 |
| `{{seed}}` | 每次生成的随机种子 |
| `{{steps}}` / `{{cfg}}` | Steps / Guidance |
| `{{model}}` | 当前模型 ID |
| `{{reference_image}}` | 第一张上传到 ComfyUI 的参考图 |
| `{{reference_image_1}}`、`{{reference_image_2}}` ... | 按顺序上传的多张参考图 |

如果工作流有多个图片输出节点，请在供应商配置中填写目标 `SaveImage` 节点 ID；留空时使用历史结果中的第一个图片输出。

动态 IP-Adapter 示例不是普通的 ComfyUI 单工作流，而是 FicFrame 识别的动态描述文件。自定义普通工作流仍按原始 API JSON 执行，不会自动增加 IP-Adapter 节点。

## 性能建议

性能建议不是功能限制：

- 8GB 显存可从单人 `768x1024`、双人 `1024x768`、20 Steps 开始。
- 参考图、角色和分辨率增加时，IP-Adapter 编码和采样都会占用更多资源。
- 首次生成通常包含 checkpoint、CLIP Vision 和 VAE 加载时间。
- 显存不足时优先降低分辨率，其次减少同时参与分镜的参考图。
- 不建议在尚未验证基础链路时直接使用 `2K` 或 `4K`。

## 配置保存位置

ComfyUI 地址和工作流保存在：

```text
.ficframe/providers.json
.ficframe/comfyui_workflow.json
```

激活供应商后也会同步必要配置到 `.env`。这些文件默认不会提交到仓库。

遇到模型找不到、节点缺失、显存不足或参考图不生效时，参阅 [常见问题](faq.md)。
