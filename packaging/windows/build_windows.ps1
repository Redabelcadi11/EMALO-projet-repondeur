param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$DistRoot = Join-Path $ProjectRoot "dist\windows"
$BuildRoot = Join-Path $ProjectRoot "build\windows"
$SpecPath = Join-Path $ProjectRoot "packaging\windows\ProjetRepondeur.spec"
$LauncherSource = Join-Path $ProjectRoot "packaging\windows\launchers\*"
$AppDist = Join-Path $DistRoot "ProjetRepondeur"
$BrowserCacheRoot = Join-Path $ProjectRoot "packaging\windows\cache\ms-playwright"
$VendoredFfmpegRoot = Join-Path $ProjectRoot "packaging\windows\vendor\ffmpeg"

function Copy-BundledRuntime {
    if (Test-Path $BrowserCacheRoot) {
        $Target = Join-Path $AppDist "ms-playwright"
        if (Test-Path $Target) {
            Remove-Item $Target -Recurse -Force
        }
        Copy-Item $BrowserCacheRoot $Target -Recurse -Force
        Write-Host "Chromium Playwright copié dans le package."
    } else {
        Write-Warning "Runtime Playwright introuvable dans le cache de build."
    }
}

function Copy-FfmpegBundle {
    $TargetRoot = Join-Path $AppDist "ffmpeg\bin"
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

    if (Test-Path $VendoredFfmpegRoot) {
        Copy-Item (Join-Path $VendoredFfmpegRoot "*") (Join-Path $AppDist "ffmpeg") -Recurse -Force
        Write-Host "FFmpeg vendorisé copié dans le package."
        return
    }

    $ffmpegCmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($ffmpegCmd) {
        $ffmpegDir = Split-Path -Parent $ffmpegCmd.Source
        Get-ChildItem $ffmpegDir -File | Where-Object {
            $_.Name -match '^(ffmpeg|ffprobe).*\.exe$' -or $_.Extension -eq '.dll'
        } | Copy-Item -Destination $TargetRoot -Force
        Write-Host "FFmpeg copié depuis le système de build."
        return
    }

    Remove-Item (Join-Path $AppDist "ffmpeg") -Recurse -Force -ErrorAction SilentlyContinue
    Write-Warning "FFmpeg non trouvé. Le package sera livré sans FFmpeg."
}

Set-Location $ProjectRoot

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

New-Item -ItemType Directory -Force -Path $BrowserCacheRoot | Out-Null
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCacheRoot
python -m playwright install chromium

if (-not $SkipTests) {
    $env:PYTHONPATH = $ProjectRoot
    pytest -q tests
}

if (Test-Path $DistRoot) {
    Remove-Item $DistRoot -Recurse -Force
}
if (Test-Path $BuildRoot) {
    Remove-Item $BuildRoot -Recurse -Force
}

python -m PyInstaller `
    $SpecPath `
    --noconfirm `
    --clean `
    --distpath $DistRoot `
    --workpath $BuildRoot `
    --specpath (Join-Path $ProjectRoot "packaging\windows")

Copy-Item $LauncherSource $AppDist -Force
Copy-BundledRuntime
Copy-FfmpegBundle

$ZipPath = Join-Path $DistRoot "ProjetRepondeur-windows.zip"
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}
Compress-Archive -Path (Join-Path $AppDist "*") -DestinationPath $ZipPath -Force

if (-not $SkipInstaller) {
    $iscc = Get-ChildItem "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $iscc = Get-ChildItem "C:\Program Files\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue
    }
    if ($iscc) {
        & $iscc.FullName (Join-Path $ProjectRoot "packaging\windows\ProjetRepondeur.iss")
    } else {
        Write-Host "Inno Setup non trouvé : installateur .exe non généré."
    }
}

Write-Host ""
Write-Host "Build terminé."
Write-Host "Dossier app : $AppDist"
Write-Host "Archive zip : $ZipPath"
