# Claude Unified Limit Monitor

**Real-time usage tracking across Claude.ai, Claude Code, and Cowork**

Monitor your Claude usage limits in a unified view. Get proactive notifications before hitting limits. Make informed decisions about which product to use based on current capacity.

---

## Why This Exists

Claude Pro, Max, and Team plans have **shared usage limits** across all products:
- Claude.ai (chat)
- Claude Code (terminal coding assistant)
- Cowork (desktop agent for file work)

All three consume from the **same rolling 5-hour window**. Different products have different weights:
- **Chat:** Baseline consumption (1x)
- **Claude Code:** ~5x heavier (large system prompts, file contexts)
- **Cowork:** ~10x heavier (multi-step tasks, extended execution)

Without monitoring, you might:
- Start a Cowork task and hit the limit mid-execution
- Use Claude Code heavily then have no capacity for chat
- Miss the reset window and wait unnecessarily

This monitor solves that.

---

## Features

✅ **Unified tracking** - Single view across all three products  
✅ **Weighted usage** - Accounts for different consumption rates  
✅ **Proactive notifications** - Alerts at 80%, 90%, 95% thresholds  
✅ **CLI stats tool** - Quick status checks from terminal  
✅ **Rolling window** - Accurate reset time predictions  
✅ **Cross-platform** - Linux, Windows, macOS support  
✅ **Lightweight** - ~8MB RAM, minimal CPU  
✅ **Persistent state** - Survives daemon restarts

---

## Installation

### Requirements

- Python 3.11+
- `psutil` package
- Claude Desktop and/or Claude Code installed

### 1. Install Dependencies

```bash
# Linux/macOS
pip3 install psutil --break-system-packages

# Windows
pip install psutil
```

### 2. Copy Scripts

```bash
cd /path/to/Claude  # or your CLAUDE_HOME
mkdir -p scripts
cp claude-limit-daemon.py scripts/
cp claude-stats scripts/
chmod +x scripts/claude-stats
```

### 3. Create Config

```bash
cp unified-limit-monitor.conf.example .claude/unified-limit-monitor.conf
# Edit to set your plan (pro, max_5x, max_20x)
nano .claude/unified-limit-monitor.conf
```

### 4. Test Manually

```bash
python3 scripts/claude-limit-daemon.py
# Should output:
# Claude Limit Monitor Started
# CLAUDE_HOME: /home/tallest/Claude
# Plan: pro
# ...
```

Press Ctrl+C to stop.

### 5. Install as Service

**Linux (systemd):**

See `services/linux/README.md` for full instructions.

```bash
sudo cp services/linux/claude-limit-monitor.service /etc/systemd/system/
# Edit paths if needed
sudo nano /etc/systemd/system/claude-limit-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable claude-limit-monitor
sudo systemctl start claude-limit-monitor
```

**Windows (NSSM):**

See `services/windows/README.md` for full instructions.

```powershell
# Run as Administrator
.\services\windows\install-limit-monitor.ps1
net start ClaudeLimitMonitor
```

---

## Usage

### CLI Tool

```bash
# Current status (default)
claude-stats

# Output:
# Claude Usage Monitor
# ────────────────────────────────────────
# 
# Plan: PRO
# Rolling Window (5hr): 32.0/45 (71%)
# │████████████████░░░░│
# 
# Breakdown:
#   Chat     12 events  (12.0 units)
#   Code      3 sessions (15.0 units)
#   Cowork    1 task     (5.0 units)
# ────────────────────────────────────────
# Total:              16 events  (32.0 units)
# 
# Next reset: 2h 15m

# JSON output (for scripting)
claude-stats json

# Reset time only
claude-stats reset
```

### Desktop Notifications

Automatic notifications at configured thresholds:

- **80% (Warning):** "🟡 Claude Usage Warning - 80% used (36/45)"
- **90% (Urgent):** "🟠 Claude Usage High - Consider waiting for reset"
- **95% (Critical):** "🔴 Claude Usage Critical - Limit reached soon!"

Notifications repeat every 5 minutes if threshold still exceeded.

---

## Configuration

Edit `{CLAUDE_HOME}/.claude/unified-limit-monitor.conf`:

```ini
[account]
plan = pro  # Change to: pro, max_5x, max_20x

[weights]
# Adjust based on your actual usage patterns
chat = 1.0
code = 5.0
cowork = 10.0

[notifications]
threshold_warning = 80
threshold_urgent = 90
threshold_critical = 95
```

Restart daemon after config changes:
```bash
sudo systemctl restart claude-limit-monitor  # Linux
net restart ClaudeLimitMonitor                # Windows
```

---

## How It Works

### Process Monitoring

Daemon watches for Claude processes:
- **Claude Desktop** → Classified as `chat` or `cowork`
- **Claude Code** → Terminal/CLI process
- **Browser** → claude.ai tabs (future enhancement)

### Activity Detection

When activity detected (process running):
- Record event with timestamp and product type
- Apply consumption weight (chat: 1x, code: 5x, cowork: 10x)
- Clean up events outside 5-hour window
- Calculate current usage percentage
- Check notification thresholds
- Save state to persistent JSON file

### Rolling Window

Events older than 5 hours automatically removed. Next reset time calculated from oldest event in window. When window resets, capacity returns.

---

## Smart Usage Strategies

**When near limit:**

1. **Use chat instead of Code/Cowork** - Chat is 5-10x cheaper
2. **Wait for reset** - Check `claude-stats reset` for timing
3. **Batch Cowork tasks** - Do multiple file operations in one session
4. **Schedule heavy work** - Plan Code/Cowork sessions right after reset

**Monitoring during work:**

```bash
# Check before starting Cowork task
claude-stats

# If >80% used, consider:
# - Using chat for lighter tasks
# - Waiting for reset
# - Batching multiple tasks together
```

---

## Troubleshooting

**Daemon not detecting activity:**
```bash
# Check if daemon running
sudo systemctl status claude-limit-monitor  # Linux
sc query ClaudeLimitMonitor                # Windows

# Check logs
sudo journalctl -u claude-limit-monitor -f  # Linux
type D:\Claude\.claude\logs\limit-monitor.log  # Windows
```

**Inaccurate usage tracking:**
- Weights are estimates - adjust in config based on your patterns
- Process detection is heuristic - may miss some activity
- Manual override option coming in future version

**No notifications:**
```bash
# Linux: Check notify-send installed
notify-send "Test" "Message"

# Windows: Feature in development
```

---

## Roadmap

**Phase 2:**
- [ ] System tray icon with live count
- [ ] Browser extension to detect claude.ai usage
- [ ] More accurate Cowork vs Chat detection
- [ ] Usage predictions ("limit in ~45 min at current rate")

**Phase 3:**
- [ ] Weekly limit tracking
- [ ] Usage analytics and reports
- [ ] Smart recommendations ("use chat, save Cowork for later")
- [ ] Integration with temporal-awareness-protocol

---

## Files and Directories

```
{CLAUDE_HOME}/
├── scripts/
│   ├── claude-limit-daemon.py    # Main daemon
│   └── claude-stats               # CLI query tool
├── .claude/
│   ├── unified-limit-monitor.conf # Configuration
│   └── logs/
│       ├── limit-tracker-state.json  # Persistent state
│       ├── limit-monitor.log         # Daemon stdout
│       └── limit-monitor-error.log   # Daemon stderr
```

---

## Contributing

Part of the [Continuity Bridge](https://github.com/continuity-bridge/continuity-bridge_tallest-anchor) project. See main repository for contribution guidelines.

---

## License

Apache 2.0

---

## Links

- **Continuity Bridge:** https://github.com/continuity-bridge/continuity-bridge_tallest-anchor
- **Temporal Awareness Protocol:** https://github.com/continuity-bridge/temporal-awareness-protocol
- **Claude Documentation:** https://support.claude.com

---

**Remember:** Limits exist to share resources fairly. Monitor proactively, use strategically, and respect the system.
