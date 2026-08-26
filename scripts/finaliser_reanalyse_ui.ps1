param(
    [string]$ProjectRoot = "L:\Public\EMALO-Achats\EMALO-Repondeur",
    [string]$RemoteHost = "ubuntu@51.210.2.253",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\whisper_vm_ed25519"
)

$ErrorActionPreference = "Stop"
$remotePrediction = "/opt/emalo-repondeur-worker/evaluation/predictions/reanalyse-ui-lot-20260825-v18-ui-llama.json"
$localPrediction = Join-Path $ProjectRoot "evaluation\predictions\reanalyse-ui-lot-20260825-v18-ui-llama.json"
$report = Join-Path $ProjectRoot "resultats\rapports\reanalyse-ui-lot-20260825-v18-ui-llama.md"

while ($true) {
    & ssh -i $KeyPath $RemoteHost "test -f $remotePrediction"
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 20
}

& scp -i $KeyPath "$RemoteHost`:$remotePrediction" $localPrediction
if ($LASTEXITCODE -ne 0) { throw "Copie de la prediction impossible." }

& python (Join-Path $ProjectRoot "scripts\exporter_rapport_commandes_reanalyse.py") `
    --predictions $localPrediction `
    --output $report
if ($LASTEXITCODE -ne 0) { throw "Export du rapport impossible." }
