param([string]$Destination = "")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Destination) {
    $Destination = Join-Path $projectRoot ('target/publish-source-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (Test-Path -LiteralPath $Destination) {
    throw 'Destination already exists. Choose a new directory.'
}
$destinationRoot = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Path $destinationRoot | Out-Null
$directories = @('app', 'tests', 'docs', 'scripts', 'skills', 'models')
$rootFiles = @('README.md', 'requirements.txt', 'requirements-ragas.txt', '.gitignore', '.env.example', 'LICENSE', 'LICENSE.md', 'NOTICE')
$sourceFiles = foreach ($directory in $directories) {
    $path = Join-Path $projectRoot $directory
    if (Test-Path -LiteralPath $path) {
        Get-ChildItem -LiteralPath $path -Recurse -File |
            Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
                ($_.Extension -in @('.py', '.md', '.json', '.html', '.css', '.js', '.sh', '.ps1', '.txt', '.yaml', '.yml') -or $_.Name -eq 'Modelfile') }
    }
}
foreach ($name in $rootFiles) {
    $path = Join-Path $projectRoot $name
    if (Test-Path -LiteralPath $path) { $sourceFiles += Get-Item -LiteralPath $path }
}
$blocked = @()
foreach ($file in $sourceFiles) {
    $relative = $file.FullName.Substring($projectRoot.Length + 1)
    $body = [IO.File]::ReadAllText($file.FullName)
    # Report paths only; never print candidate secrets.
    if ($body -match '(?i)\bsk-[a-z0-9_-]{20,}|\bgh[pousr]_[a-z0-9]{20,}|\bgithub_pat_[a-z0-9_]{20,}|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----') {
        $blocked += $relative
        continue
    }
    $target = Join-Path $destinationRoot $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}
if ($blocked.Count) {
    throw ('Potential credentials found. Release not ready; inspect: ' + ($blocked -join ', '))
}
Write-Output ('Prepared source release: ' + $destinationRoot)
Write-Output ('Files: ' + $sourceFiles.Count)
