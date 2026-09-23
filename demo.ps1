# Double-click or run .\demo.ps1 to show the agent working.
#
#   .\demo.ps1              five cases, pauses between each
#   .\demo.ps1 -Fast        no pauses
#   .\demo.ps1 -Only 3      one case
#   .\demo.ps1 -Chat        drop into a conversation instead
#   .\demo.ps1 -OpenRouterKey sk-or-... -TavilyKey tvly-...   keys instead of .env

param(
    [switch]$Fast,
    [switch]$Chat,
    [ValidateRange(1, 5)][int]$Only,
    [string]$OpenRouterKey,
    [string]$TavilyKey
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is not installed. Get it from https://docs.astral.sh/uv/" -ForegroundColor Red
    exit $OpenRouterKey -and -not (Test-Path .env)) {
    Write-Host "No OpenRouter key. Pass -OpenRouterKey, or copy .env.example to .env and fill it in." -ForegroundColor Red
    exit 1
}

# Keys are passed as environment variables rather than arguments so they do not show up in
# the process list.
if ($OpenRouterKey) { $env:OPENROUTER_API_KEY = $OpenRouterKey }
if ($TavilyKey) { $env:TAVILY_API_KEY = $TavilyKey if (-not (Test-Path .env)) {
    Write-Host ".env is missing. Copy .env.example to .env and add your OPENROUTER_API_KEY." -ForegroundColor Red
    exit 1
}

# Answers contain arrows and accented characters; a cp1252 console mangles them.
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

Write-Host "Syncing dependencies..." -ForegroundColor DarkGray
uv sync --quiet

if ($Chat) {
    uv run pv chat
    exit $LASTEXITCODE
}

$args = @('run', 'pv', 'demo')
if ($Fast) { $args += '--no-pause' }
if ($Only) { $args += @('--only', $Only) }
& uv @args
exit $LASTEXITCODE
