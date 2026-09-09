<#
.SYNOPSIS
    Export a clean, secret-free AI project context package for external AI review or session recovery.
.PARAMETER ProjectDir
    The root path of the project to export.
.PARAMETER OutputDir
    The destination directory for the zip archive.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectDir,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ProjectDir)) {
    Write-Error "Project directory does not exist: $ProjectDir"
}

$ProjectDir = (Resolve-Path $ProjectDir).Path
$ProjectName = Split-Path $ProjectDir -Leaf

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $ProjectDir "..\context-exports"
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
$OutputDir = (Resolve-Path $OutputDir).Path

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TempStage = Join-Path $env:TEMP "ctx-stage-$ProjectName-$Timestamp"
if (Test-Path $TempStage) { Remove-Item -Recurse -Force $TempStage }
New-Item -ItemType Directory -Path $TempStage -Force | Out-Null

try {
    Write-Host "[1/4] Capturing Git runtime state..."
    $GitSnapshotFile = Join-Path $TempStage "GIT-STATE-SNAPSHOT.txt"
    $GitSnapshot = @"
================================================================================
AI CONTEXT PACK - GIT RUNTIME SNAPSHOT
Timestamp: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Project Path: $ProjectDir
================================================================================

[Current Commit]
$(git -C $ProjectDir rev-parse HEAD 2>&1)

[Current Branch]
$(git -C $ProjectDir branch --show-current 2>&1)

[Remote Repositories]
$(git -C $ProjectDir remote -v 2>&1)

[Working Tree Status]
$(git -C $ProjectDir status --short 2>&1)

[Recent 5 Commits]
$(git -C $ProjectDir log -n 5 --oneline 2>&1)
"@
    Set-Content -Path $GitSnapshotFile -Value $GitSnapshot -Encoding UTF8

    Write-Host "[2/4] Copying project documentation and core files..."
    $Excludes = @(
        ".git", ".venv", "venv", "node_modules", "target", "dist", "build",
        "__pycache__", "logs", "tmp", "temp", "LocalConfig", "secrets",
        "*.key", "*.token", "*.pem", "*.pfx", "*.p12", ".env*", "*.db", "*.sqlite3"
    )

    # 1. Root README
    if (Test-Path (Join-Path $ProjectDir "README.md")) {
        Copy-Item (Join-Path $ProjectDir "README.md") (Join-Path $TempStage "README.md")
    }
    if (Test-Path (Join-Path $ProjectDir "AGENTS.md")) {
        Copy-Item (Join-Path $ProjectDir "AGENTS.md") (Join-Path $TempStage "AGENTS.md")
    }

    # 2. Docs directory (excluding archive)
    $DocsDir = Join-Path $ProjectDir "docs"
    if (Test-Path $DocsDir) {
        $StageDocs = Join-Path $TempStage "docs"
        New-Item -ItemType Directory -Path $StageDocs -Force | Out-Null
        
        Get-ChildItem -Path $DocsDir -Recurse -File | ForEach-Object {
            $RelPath = $_.FullName.Substring($DocsDir.Length + 1)
            # Skip archive, superseded, or hidden files
            if ($RelPath -like "archive\*" -or $RelPath -like "*SUPERSEDED*" -or $_.Name -like ".*" -or $_.Name -eq "desktop.ini") {
                return
            }
            $DestPath = Join-Path $StageDocs $RelPath
            $DestParent = Split-Path $DestPath -Parent
            if (-not (Test-Path $DestParent)) {
                New-Item -ItemType Directory -Path $DestParent -Force | Out-Null
            }
            Copy-Item $_.FullName $DestPath
        }
    }

    # 3. Scripts overview if exists
    $ScriptsDir = Join-Path $ProjectDir "scripts"
    if (Test-Path $ScriptsDir) {
        $StageScripts = Join-Path $TempStage "scripts"
        New-Item -ItemType Directory -Path $StageScripts -Force | Out-Null
        Get-ChildItem -Path $ScriptsDir -Filter "*gate*" -Recurse -File | ForEach-Object {
            $RelPath = $_.FullName.Substring($ScriptsDir.Length + 1)
            $DestPath = Join-Path $StageScripts $RelPath
            $DestParent = Split-Path $DestPath -Parent
            if (-not (Test-Path $DestParent)) {
                New-Item -ItemType Directory -Path $DestParent -Force | Out-Null
            }
            Copy-Item $_.FullName $DestPath
        }
    }

    Write-Host "[3/4] Creating zip archive..."
    $CommitShort = (git -C $ProjectDir rev-parse --short HEAD 2>$null)
    if ([string]::IsNullOrWhiteSpace($CommitShort)) { $CommitShort = "nocommit" }
    $ZipFilename = "$ProjectName-context-$Timestamp-$CommitShort.zip"
    $ZipPath = Join-Path $OutputDir $ZipFilename

    if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
    Compress-Archive -Path "$TempStage\*" -DestinationPath $ZipPath -Force

    Write-Host "[4/4] Verification & Cleanup..."
    Write-Host "Export completed successfully:"
    Write-Host "Output Archive: $ZipPath"
    Write-Host "Size: $((Get-Item $ZipPath).Length) bytes"
}
finally {
    if (Test-Path $TempStage) {
        Remove-Item -Recurse -Force $TempStage -ErrorAction SilentlyContinue
    }
}
