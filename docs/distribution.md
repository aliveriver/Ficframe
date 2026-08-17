# Windows 与 Linux 发布包

FicFrame 的发布包内置 Python 解释器和全部运行依赖。最终用户不需要安装 Python、uv 或 pip。

当前发布目标：

- Windows x64：安装器与便携 ZIP
- Linux x86_64：`.run` 安装器与便携 `.tar.gz`

macOS 不在当前发布范围内。

## 最终用户安装

### Windows 安装器

运行 `FicFrame-<版本>-windows-x64-setup.exe`，在安装向导的目录页面选择目标磁盘和目录。安装完成后可从开始菜单、可选的桌面快捷方式或安装目录中的 `FicFrame.exe` 启动。

安装器也支持命令行指定目录：

```powershell
FicFrame-0.1.0-windows-x64-setup.exe /DIR="D:\Apps\FicFrame"
```

### Windows 便携 ZIP

将 `FicFrame-<版本>-windows-x64-portable.zip` 解压到任意有写权限的目录，直接运行 `FicFrame.exe`。不要只把 EXE 单独复制出来，旁边的 `_internal/` 是必要运行文件。

### Linux 安装器

Linux `.run` 安装包要求明确给出目录或在交互提示中输入：

```bash
chmod +x FicFrame-0.1.0-linux-x86_64.run
./FicFrame-0.1.0-linux-x86_64.run --target /mnt/data/apps/FicFrame --launch
```

也可以下载 `.tar.gz`，解压到任意有写权限的目录后直接运行 `FicFrame`。

应用默认启动本机 `127.0.0.1:8787`；如果端口被占用，会向后寻找可用端口并自动打开浏览器。关闭启动窗口或按 `Ctrl+C` 即可停止后端。

## 数据位置

发布版使用便携数据模式：

```text
用户选择的安装目录/
├── FicFrame.exe 或 FicFrame
├── _internal/               # 内置 Python 与程序依赖
└── data/
    ├── .env                 # API 配置
    ├── .ficframe/           # 供应商与 ComfyUI 配置
    └── outputs/             # 日志、分镜、图片和导出结果
```

更新或卸载程序时，安装器不会主动删除 `data/`。备份或迁移应用时，可以直接复制整个安装目录。

Windows 仍会为快捷方式、卸载登记和安装期间的临时解压使用少量系统空间；程序主体和持续增长的用户数据位于所选目录。

## 更新、备份与卸载

- 更新 Windows 安装版时选择原安装目录；程序文件会更新，已有 `data/` 会保留。
- 更新便携版前先关闭 FicFrame，备份 `data/`，然后替换 EXE 和 `_internal/`。
- Linux `.run` 可以再次安装到原目录，归档中不包含 `data/`，因此不会覆盖用户数据。
- Windows 卸载器不会主动删除非空的 `data/`；Linux 可在关闭程序后删除整个安装目录。
- 迁移到其他磁盘时，关闭 FicFrame 后复制整个安装目录即可。

`data/.env` 与 `data/.ficframe/providers.json` 可能包含 API key，不要把完整数据目录公开上传。

## 构建 Windows 包

要求：

- Windows x64
- `uv`
- Inno Setup 6（只生成便携 ZIP 时可以不安装）

```powershell
.\scripts\build_windows.ps1 -RequireInstaller
```

产物写入 `release/`：

- `FicFrame-<版本>-windows-x64-setup.exe`
- `FicFrame-<版本>-windows-x64-portable.zip`

## 构建 Linux 包

要求：

- Linux x86_64 或 aarch64
- `uv`
- `tar`
- `file`（用于拒绝 Windows PE/EXE 误标为 Linux 包）

```bash
chmod +x scripts/build_linux.sh
./scripts/build_linux.sh
```

产物写入 `release/`：

- `FicFrame-<版本>-linux-<架构>.run`
- `FicFrame-<版本>-linux-<架构>.tar.gz`

PyInstaller 不是交叉编译器：Windows 包必须在 Windows 构建，Linux 包必须在原生 Linux、Linux 虚拟机、WSL 的 Linux Python 环境或 Linux CI 中构建。不能在 Windows PowerShell、CMD 或 Git Bash 中运行 `build_linux.sh` 来生成 Linux 包。构建脚本会检查系统类型，并在归档前用 `file` 确认主程序是 ELF；发现 `.exe` 或 Windows PE 文件会立即失败。

正确的 Linux 解压结果中，主程序名为 `FicFrame`，没有 `.exe` 后缀。可以这样检查：

```bash
file FicFrame
# 正确结果应包含：ELF 64-bit ... executable
```

## 签名与兼容性

- 未签名的 Windows 安装器可能触发 SmartScreen。公开发布时建议配置代码签名证书。
- Linux 包应在仍受支持且相对较旧的发行版上构建，以获得更好的 glibc 向后兼容性；CI 使用 Ubuntu 22.04。
- 当前自动发布覆盖 Windows x64 与 Linux x86_64。Linux aarch64 可以在对应机器上运行同一构建脚本生成。

## 自动发布

推送形如 `v0.1.0` 的 Git 标签会触发 `.github/workflows/release.yml`。工作流分别在 Windows 和 Ubuntu runner 上构建，然后把四种产物附加到同一个 GitHub Release。也可以在 Actions 页面手动运行工作流，只生成构建产物而不创建 Release。
