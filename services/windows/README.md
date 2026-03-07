# Windows Installation - Claude Limit Monitor

## Requirements

- Python 3.11+
- `psutil` package
- NSSM (Non-Sucking Service Manager) for service management

## Installation Steps

### 1. Install NSSM

Download NSSM from: https://nssm.cc/download

Extract to `C:\nssm\` (or another location)

### 2. Install Python Dependencies

```powershell
pip install psutil
```

### 3. Copy Scripts to CLAUDE_HOME

```powershell
cd D:\Claude  # or your CLAUDE_HOME path
mkdir scripts -ErrorAction SilentlyContinue

# Copy files
copy claude-limit-daemon.py scripts\
copy claude-stats scripts\
```

### 4. Create Configuration

```powershell
# Create .claude directory if needed
mkdir .claude\logs -ErrorAction SilentlyContinue

# Copy example config
copy unified-limit-monitor.conf.example .claude\unified-limit-monitor.conf

# Edit config - set your plan
notepad .claude\unified-limit-monitor.conf
```

Set your plan in `[account]` section:
```ini
[account]
plan = pro  # or max_5x, max_20x
```

### 5. Test the Daemon

```powershell
python scripts\claude-limit-daemon.py
# Should output:
# Claude Limit Monitor Started
# CLAUDE_HOME: D:\Claude
# Plan: pro
# Limit: 45 units per 5h
# ...
```

Open Claude Desktop or Claude Code to trigger detection.  
Press Ctrl+C to stop the test.

### 6. Install Service (PowerShell as Administrator)

```powershell
# Run installation script
.\install-limit-monitor.ps1

# Or specify custom paths
.\install-limit-monitor.ps1 -ClaudeHome "D:\Claude" -NssmPath "C:\nssm\nssm.exe"
```

### 7. Start Service

```powershell
net start ClaudeLimitMonitor
```

### 8. Verify Service

```powershell
# Check status
sc query ClaudeLimitMonitor

# View logs
type D:\Claude\.claude\logs\limit-monitor.log

# Check usage stats
python scripts\claude-stats
```

### 9. Add to PATH (optional)

Add `D:\Claude\scripts` to your PATH environment variable so you can run `claude-stats` from anywhere.

---

## Service Management

```powershell
# Start service
net start ClaudeLimitMonitor

# Stop service
net stop ClaudeLimitMonitor

# View status
sc query ClaudeLimitMonitor

# View logs
type D:\Claude\.claude\logs\limit-monitor.log

# View errors
type D:\Claude\.claude\logs\limit-monitor-error.log
```

---

## Manual Installation (if script fails)

```powershell
# Install service
nssm install ClaudeLimitMonitor "C:\Python\python.exe" "D:\Claude\scripts\claude-limit-daemon.py"

# Configure
nssm set ClaudeLimitMonitor AppDirectory "D:\Claude"
nssm set ClaudeLimitMonitor AppEnvironmentExtra CLAUDE_HOME=D:\Claude
nssm set ClaudeLimitMonitor DisplayName "Claude Unified Limit Monitor"
nssm set ClaudeLimitMonitor Start SERVICE_AUTO_START
nssm set ClaudeLimitMonitor AppStdout "D:\Claude\.claude\logs\limit-monitor.log"
nssm set ClaudeLimitMonitor AppStderr "D:\Claude\.claude\logs\limit-monitor-error.log"

# Start
net start ClaudeLimitMonitor
```

---

## Troubleshooting

**Service won't start:**
```powershell
# Check logs
type D:\Claude\.claude\logs\limit-monitor-error.log

# Test script manually
python D:\Claude\scripts\claude-limit-daemon.py
```

**Permission errors:**
- Ensure running PowerShell as Administrator
- Ensure service has access to D:\Claude

**Import errors:**
```powershell
pip install psutil
```

**No activity detected:**
- Verify Claude Desktop or Code is running
- Check Task Manager for Claude processes
- Daemon may need refinement for Windows process names

**Notifications:**
Windows Toast notifications are in development. For now, daemon logs activity without desktop notifications.

---

## Uninstall

```powershell
# Stop service
net stop ClaudeLimitMonitor

# Remove service
nssm remove ClaudeLimitMonitor confirm
```

---

## Advanced: Multiple Machines

If you use Claude on multiple Windows machines, each machine should run its own daemon. Usage is tracked per-machine, not globally.
