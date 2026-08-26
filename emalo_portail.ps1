[CmdletBinding()]
param(
  [string]$PortalRoot = $PSScriptRoot,
  [int]$Port = 8764
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$PortalRoot = (Resolve-Path $PortalRoot).Path
$ServerScript = Join-Path $PortalRoot 'portal_server.py'
$LogDir = Join-Path $env:LOCALAPPDATA 'ProjetRepondeur\logs'
$ServerLog = Join-Path $LogDir 'emalo-portail-web.log'
$ServerErrLog = Join-Path $LogDir 'emalo-portail-web-error.log'

function Resolve-Python {
  $candidates = @(
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
  param([int]$CheckPort)
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $async = $client.BeginConnect('127.0.0.1', $CheckPort, $null, $null)
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
  throw "Serveur portail introuvable: $ServerScript"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$python = Resolve-Python

if (-not (Test-WebPortListening -CheckPort $Port)) {
  Start-Process -FilePath $python -ArgumentList @(
    '-B',
    $ServerScript
  ) -WorkingDirectory $PortalRoot -WindowStyle Hidden -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErrLog
  Start-Sleep -Seconds 2
}

$version = if (Test-Path -LiteralPath $ServerScript) {
  (Get-Item -LiteralPath $ServerScript).LastWriteTimeUtc.Ticks
} else {
  [DateTime]::UtcNow.Ticks
}
$url = "http://127.0.0.1:$Port/?v=$version"
$browser = Get-AppBrowser
if ($browser) {
  Start-Process -FilePath $browser -ArgumentList @("--app=$url", '--window-size=1120,760')
  exit 0
}

Start-Process $url
