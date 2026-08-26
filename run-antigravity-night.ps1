$ErrorActionPreference = "Continue"

$Project = "L:\Public\EMALO-Achats\EMALO-Repondeur"
$PromptFile = Join-Path $Project "ANTIGRAVITY_NIGHT_PROMPT.txt"
$StateFile = Join-Path $Project "ANTIGRAVITY_NIGHT_STATE.json"
$LogDir = Join-Path $Project ".antigravity-night"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Project

$Run = 0

while ($true) {

    $Run++

    Write-Host ""
    Write-Host "========================================"
    Write-Host " ANTIGRAVITY NIGHT RUN $Run"
    Write-Host " $(Get-Date)"
    Write-Host "========================================"

    $State = $null

    if (Test-Path $StateFile) {
        try {
            $State = Get-Content $StateFile -Raw | ConvertFrom-Json
        }
        catch {
            Write-Host "State JSON illisible, poursuite."
        }
    }

    # Objectif atteint
    if ($State -and $State.status -eq "GOAL_REACHED") {
        Write-Host "OBJECTIF >= 90 % ATTEINT."
        break
    }

    # Blocage méthodologique ou technique
    if ($State -and $State.status -eq "BLOCKED") {
        Write-Host "Agent bloque proprement. Voir ANTIGRAVITY_NIGHT_STATE.json"
        break
    }

    # Flash fait le marathon.
    # Pro intervient lorsqu'un plateau a été déclaré.
    if ($State -and $State.status -eq "PLATEAU") {
        $Model = "gemini-3.1-pro-high"
        Write-Host "Plateau detecte -> Gemini 3.1 Pro High"
    }
    elseif ($State -and $State.status -eq "READY_FOR_FINAL_HOLDOUT") {
        $Model = "gemini-3.1-pro-high"
        Write-Host "Gate finale -> Gemini 3.1 Pro High"
    }
    else {
        $Model = "gemini-3.7-flash-high"
    }

    $Prompt = Get-Content $PromptFile -Raw

    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutFile = Join-Path $LogDir "run-$Run-$Timestamp.json"
    $ErrFile = Join-Path $LogDir "run-$Run-$Timestamp.stderr.txt"

    $Args = @(
        "-p", $Prompt,
        "--continue",
        "--model", $Model,
        "--effort", "high",
        "--output-format", "json",
        "--print-timeout", "240m"
    )

    Write-Host "Modele : $Model"
    Write-Host "Lancement..."

    $Raw = (& agy @Args 2>> $ErrFile | Out-String)
    $ExitCode = $LASTEXITCODE

    $Raw | Set-Content -Path $OutFile -Encoding UTF8

    $AgyStatus = $null

    try {
        $Obj = $Raw | ConvertFrom-Json
        $AgyStatus = $Obj.status
        Write-Host "Status AGY : $AgyStatus"
    }
    catch {
        Write-Host "Sortie AGY non JSON."
    }

    # Si Antigravity a ete interrompu, rate-limite, quota epuise,
    # timeout, erreur d'auth ou erreur transitoire :
    # on attend 15 minutes puis on retente.
    if ($ExitCode -ne 0 -or $AgyStatus -ne "SUCCESS") {

        Write-Host ""
        Write-Host "Run interrompu ou quota/erreur."
        Write-Host "Nouvel essai dans 15 minutes."
        Write-Host "Les fichiers d'etat seront relus au prochain lancement."

        Start-Sleep -Seconds 900
        continue
    }

    # Relire l'etat ecrit par Gemini
    if (Test-Path $StateFile) {
        try {
            $State = Get-Content $StateFile -Raw | ConvertFrom-Json

            Write-Host "Etat projet : $($State.status)"
            Write-Host "Best strict : $($State.best_dev_strict)"

            if ($State.status -eq "GOAL_REACHED") {
                Write-Host ""
                Write-Host "========================================"
                Write-Host " OBJECTIF >= 90 % ATTEINT"
                Write-Host "========================================"
                break
            }

            if ($State.status -eq "BLOCKED") {
                Write-Host "Blocage propre detecte."
                break
            }
        }
        catch {
            Write-Host "Impossible de relire l'etat, poursuite."
        }
    }

    # Un run s'est termine normalement mais le travail n'est pas fini.
    # On redonne presque immediatement la main a un nouvel agent.
    Write-Host "Nouvelle passe dans 30 secondes..."
    Start-Sleep -Seconds 30
}