[CmdletBinding()]
param(
  [string]$ProjectRoot = 'C:\ProjetRepondeurWorker',
  [int]$Port = 8787
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Server = Join-Path $ProjectRoot 'worker_transcription_server.py'
$LogDir = Join-Path $ProjectRoot 'logs'
$LogFile = Join-Path $LogDir 'worker.log'

if (-not (Test-Path -LiteralPath $Python)) {
  throw "Python worker introuvable: $Python"
}
if (-not (Test-Path -LiteralPath $Server)) {
  throw "Serveur worker introuvable: $Server"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:REPONDEUR_WHISPER_MODEL = if ($env:REPONDEUR_WHISPER_MODEL) { $env:REPONDEUR_WHISPER_MODEL } else { 'large-v3' }
$env:REPONDEUR_WHISPER_DEVICE = if ($env:REPONDEUR_WHISPER_DEVICE) { $env:REPONDEUR_WHISPER_DEVICE } else { 'cpu' }
$env:REPONDEUR_WHISPER_COMPUTE = if ($env:REPONDEUR_WHISPER_COMPUTE) { $env:REPONDEUR_WHISPER_COMPUTE } else { 'int8' }
$env:REPONDEUR_WHISPER_CPU_THREADS = if ($env:REPONDEUR_WHISPER_CPU_THREADS) { $env:REPONDEUR_WHISPER_CPU_THREADS } else { '4' }

& $Python $Server --host 0.0.0.0 --port $Port *>> $LogFile
