param(
    [string]$Version = "",
    [switch]$RequireInstaller
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:UV_CACHE_DIR = Join-Path $RepoRoot ".uv-cache"

if (-not $Version) {
    $match = Select-String -Path (Join-Path $RepoRoot "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $match) { throw "无法从 pyproject.toml 读取版本。" }
    $Version = $match.Matches[0].Groups[1].Value
}

$BuildRoot = Join-Path $RepoRoot "build\package\windows"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "work"
$ArtifactRoot = Join-Path $RepoRoot "release"
$expectedPrefix = $RepoRoot.TrimEnd('\') + '\build\package\windows'
if (-not $BuildRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝清理工作区之外的目录：$BuildRoot"
}
if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot, $ArtifactRoot | Out-Null

uv run --extra build pyinstaller --noconfirm --clean `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    (Join-Path $RepoRoot "packaging\ficframe.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }

$PortableZip = Join-Path $ArtifactRoot "FicFrame-$Version-windows-x64-portable.zip"
if (Test-Path -LiteralPath $PortableZip) { Remove-Item -LiteralPath $PortableZip -Force }
Compress-Archive -Path (Join-Path $DistRoot "FicFrame\*") -DestinationPath $PortableZip -CompressionLevel Optimal

$IsccCandidates = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$Iscc = $IsccCandidates | Select-Object -First 1

if ($Iscc) {
    & $Iscc "/DAppVersion=$Version" "/DSourceDir=$(Join-Path $DistRoot 'FicFrame')" "/DArtifactDir=$ArtifactRoot" (Join-Path $RepoRoot "packaging\windows\FicFrame.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 构建失败。" }
} elseif ($RequireInstaller) {
    throw "未找到 Inno Setup 6（ISCC.exe），无法生成 Windows 安装器。"
} else {
    Write-Warning "未找到 Inno Setup 6；已生成便携 ZIP，但没有生成 Setup.exe。"
}

Write-Host "Windows 构建完成，产物目录：$ArtifactRoot"
