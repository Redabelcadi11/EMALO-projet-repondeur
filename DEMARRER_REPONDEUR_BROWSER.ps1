[CmdletBinding()]
param(
  [string]$ProjectRoot = 'L:\Public\EMALO-Achats\EMALO-Repondeur',
  [int]$WebPort = 8788,
  [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$ServerScript = Join-Path $ProjectRoot 'repondeur_web_server.py'
$LogDir = Join-Path $env:LOCALAPPDATA 'ProjetRepondeur\logs'
$ServerLog = Join-Path $LogDir 'repondeur-web.log'
$ServerErrLog = Join-Path $LogDir 'repondeur-web-error.log'

function Resolve-Python {
  $SharedRoot = Split-Path -Parent $ProjectRoot
  $candidates = @(
    (Join-Path $ProjectRoot '.venv-win\Scripts\python.exe'),
    (Join-Path $SharedRoot 'EMALO-Achats-TSE-Simple\.venv-win\Scripts\python.exe'),
    (Join-Path $SharedRoot 'Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    'C:\Program Files\Python312\python.exe',
    'C:\Program Files\Python311\python.exe'
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      return $candidate
    }
  }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }
  throw 'Python introuvable.'
}

function Test-WebPortListening {
  param([int]$Port)
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
    $connected = $async.AsyncWaitHandle.WaitOne(500)
    if ($connected -and $client.Connected) {
      $client.EndConnect($async) | Out-Null
      $client.Close()
      return $true
    }
    $client.Close()
    return $false
  } catch {
    return $false
  }
}

function Stop-WrongRepondeurServer {
  param([int]$Port)
  try {
    $expectedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\').ToLowerInvariant()
    $currentSessionId = (Get-Process -Id $PID).SessionId
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
      $_.SessionId -eq $currentSessionId -and
      $_.CommandLine -and
      $_.CommandLine.ToLowerInvariant().Contains('repondeur_web_server.py') -and
      $_.CommandLine.Contains([string]$Port)
    })
    foreach ($process in $processes) {
      if (-not $process.CommandLine.ToLowerInvariant().Contains($expectedRoot)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
  }
}

function Get-AppBrowser {
  $candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe')
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  if ($candidates.Count -gt 0) {
    return $candidates[0]
  }
  return $null
}

if (-not (Test-Path -LiteralPath $ServerScript)) {
  throw "Serveur Repondeur introuvable: $ServerScript"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$python = Resolve-Python

Stop-WrongRepondeurServer -Port $WebPort

if (-not (Test-WebPortListening -Port $WebPort)) {
  Start-Process -FilePath $python -ArgumentList @(
    '-B',
    $ServerScript,
    '--host',
    '127.0.0.1',
    '--port',
    ([string]$WebPort)
  ) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErrLog
  Start-Sleep -Seconds 2
  if (-not (Test-WebPortListening -Port $WebPort)) {
    $err = ''
    if (Test-Path -LiteralPath $ServerErrLog) {
      $err = (Get-Content -LiteralPath $ServerErrLog -Tail 20 -ErrorAction SilentlyContinue) -join ' '
    }
    if (-not $err) {
      $err = "Aucun detail dans $ServerErrLog"
    }
    throw "Serveur Repondeur non demarre sur 127.0.0.1:$WebPort. $err"
  }
}

$version = if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'app-desktop\renderer\prod.html')) {
  (Get-Item -LiteralPath (Join-Path $ProjectRoot 'app-desktop\renderer\prod.html')).LastWriteTimeUtc.Ticks
} else {
  [DateTime]::UtcNow.Ticks
}
$url = "http://127.0.0.1:$WebPort/prod.html?v=$version"
if ($NoBrowser) {
  Write-Host $url
  exit 0
}
$browser = Get-AppBrowser
if ($browser) {
  Start-Process -FilePath $browser -ArgumentList @("--app=$url", '--window-size=1440,960')
  exit 0
}

Start-Process $url
