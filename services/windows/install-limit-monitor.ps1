# install-limit-monitor.ps1
# Install Claude Limit Monitor service on Windows using NSSM

param(
    [string]$ClaudeHome = "D:\Claude",
    [string]$NssmPath = "C:\nssm\nssm.exe"
)

# Check if running as Administrator
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "This script requires Administrator privileges. Please run as Administrator."
    exit 1
}

# Check if NSSM exists
if (-not (Test-Path $NssmPath)) {
    Write-Error "NSSM not found at: $NssmPath"
    Write-Host "Download NSSM from: https://nssm.cc/download"
    Write-Host "Extract to C:\nssm\ or specify path with -NssmPath parameter"
    exit 1
}

# Check if Claude directory exists
if (-not (Test-Path $ClaudeHome)) {
    Write-Error "Claude directory not found: $ClaudeHome"
    Write-Host "Specify correct path with -ClaudeHome parameter"
    exit 1
}

# Paths
$ScriptPath = Join-Path $ClaudeHome "scripts\claude-limit-daemon.py"
$PythonPath = (Get-Command python).Source

if (-not $PythonPath) {
    Write-Error "Python not found in PATH"
    exit 1
}

Write-Host "Installing Claude Limit Monitor Service..."
Write-Host "CLAUDE_HOME: $ClaudeHome"
Write-Host "Python: $PythonPath"
Write-Host "Script: $ScriptPath"
Write-Host ""

# Install service
& $NssmPath install ClaudeLimitMonitor $PythonPath $ScriptPath

# Configure service
& $NssmPath set ClaudeLimitMonitor AppDirectory $ClaudeHome
& $NssmPath set ClaudeLimitMonitor AppEnvironmentExtra CLAUDE_HOME=$ClaudeHome
& $NssmPath set ClaudeLimitMonitor DisplayName "Claude Unified Limit Monitor"
& $NssmPath set ClaudeLimitMonitor Description "Monitors Claude usage limits across chat, code, and cowork"
& $NssmPath set ClaudeLimitMonitor Start SERVICE_AUTO_START
& $NssmPath set ClaudeLimitMonitor AppStdout "$ClaudeHome\.claude\logs\limit-monitor.log"
& $NssmPath set ClaudeLimitMonitor AppStderr "$ClaudeHome\.claude\logs\limit-monitor-error.log"

Write-Host ""
Write-Host "Service installed successfully!"
Write-Host ""
Write-Host "To start service:"
Write-Host "  net start ClaudeLimitMonitor"
Write-Host ""
Write-Host "To view status:"
Write-Host "  sc query ClaudeLimitMonitor"
Write-Host ""
Write-Host "To check usage:"
Write-Host "  claude-stats"
Write-Host ""
Write-Host "To stop service:"
Write-Host "  net stop ClaudeLimitMonitor"
Write-Host ""
Write-Host "To uninstall service:"
Write-Host "  nssm remove ClaudeLimitMonitor confirm"
