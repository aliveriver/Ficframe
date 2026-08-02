# Minimal Example

这是一个极短示例，用来快速验证 FicFrame 是否能正常切段、抽取角色和生成分镜。

## Web 使用

1. 启动 FicFrame。
2. 上传 `novel.md` 作为小说文件。
3. 上传 `characters.md` 作为人物文件。
4. 分镜数量设置为 `3`。
5. 点击“生成分镜”。

没有配置 API key 时，也可以生成本地分镜和 prompt。

## CLI 使用

```powershell
uv run ficframe run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/minimal-demo" --max-shots 3
```

不使用 uv：

```powershell
.\.venv\Scripts\python.exe -m ficframe.cli run --novel "examples/minimal/novel.md" --characters "examples/minimal/characters.md" --out "outputs/minimal-demo" --max-shots 3
```
