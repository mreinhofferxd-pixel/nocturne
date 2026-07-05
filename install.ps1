# nocturne installer: copies the skill into ~\.claude\skills so /nocturne
# works in every repo. Safe to re-run; overwrites a previous install.
$ErrorActionPreference = 'Stop'

$zipUrl = 'https://github.com/mreinhofferxd-pixel/nocturne/archive/refs/heads/master.zip'
$claudeHome = $env:CLAUDE_HOME
if (-not $claudeHome) { $claudeHome = Join-Path $env:USERPROFILE '.claude' }
$dest = Join-Path $claudeHome 'skills\nocturne'
$tmp = Join-Path $env:TEMP ('nocturne-install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null

try {
    Write-Host 'Downloading nocturne...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $zip = Join-Path $tmp 'nocturne.zip'
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp

    $src = Join-Path $tmp 'nocturne-master\.claude\skills\nocturne'
    if (-not (Test-Path $src)) { throw 'skill folder missing in download' }

    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse $src $dest

    Write-Host "Installed: $dest"
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Write-Host 'note: Claude Code CLI not found on PATH' }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host 'note: python 3.10+ not found on PATH (the harness needs it)' }
    Write-Host 'Next: open Claude Code in the repo you want looped and run /nocturne'
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
