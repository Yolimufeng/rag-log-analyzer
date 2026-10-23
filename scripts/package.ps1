# Build a clean zip for GitHub upload.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\package.ps1
param(
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Output) {
    $Output = Join-Path (Split-Path -Parent $root) "rag-log-analyzer.zip"
}
$Output = [System.IO.Path]::GetFullPath($Output)

$stage = Join-Path $env:TEMP ("rag-log-analyzer-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null

try {
    $excludeDirs = @(
        ".venv", "venv", "storage", ".pytest_cache", "__pycache__",
        "build", "dist", ".git"
    ) | ForEach-Object { Join-Path $root $_ }
    $excludeDirs += Join-Path $root "data\pending"

    # robocopy exit codes 0-7 mean success; 8 or higher is a real failure.
    & robocopy $root $stage /E /XD $excludeDirs /XF ".env" "*.pyc" "*.zip" | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }

    # Remove nested caches that may survive the top-level exclusions.
    Get-ChildItem $stage -Recurse -Directory -Force |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    if (Test-Path $Output) {
        Remove-Item $Output -Force
    }
    $outputDir = Split-Path -Parent $Output
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $Output)

    $size = [math]::Round((Get-Item $Output).Length / 1KB, 1)
    Write-Host "Created: $Output ($size KB)"
    Write-Host "Check that .env, storage/ and data/pending/ are not in the zip."
}
finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
