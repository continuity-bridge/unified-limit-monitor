# Linux Installation - Claude Limit Monitor

## Requirements

- Python 3.11+
- `psutil` package
- systemd (for service management)
- `notify-send` (for desktop notifications)

## Installation Steps

### 1. Install Dependencies

```bash
# Install psutil
pip3 install psutil --break-system-packages

# Verify notify-send available (usually pre-installed)
which notify-send
```

### 2. Copy Scripts to CLAUDE_HOME

```bash
cd /home/tallest/Claude  # or your CLAUDE_HOME path
mkdir -p scripts

# Copy daemon and CLI tool
cp claude-limit-daemon.py scripts/
cp claude-stats scripts/
chmod +x scripts/claude-stats
```

### 3. Create Configuration

```bash
# Create .claude directory if needed
mkdir -p .claude/logs

# Copy example config
cp unified-limit-monitor.conf.example .claude/unified-limit-monitor.conf

# Edit config - set your plan
nano .claude/unified-limit-monitor.conf
```

Set your plan in `[account]` section:
```ini
[account]
plan = pro  # or max_5x, max_20x
```

### 4. Test the Daemon

```bash
python3 scripts/claude-limit-daemon.py
# Should output:
# Claude Limit Monitor Started
# CLAUDE_HOME: /home/tallest/Claude
# Plan: pro
# Limit: 45 units per 5h
# ...
```

Open Claude Desktop or Claude Code to trigger detection.  
Press Ctrl+C to stop the test.

### 5. Install systemd Service

```bash
# Copy service file
sudo cp claude-limit-monitor.service /etc/systemd/system/

# Edit if your paths differ
sudo nano /etc/systemd/system/claude-limit-monitor.service
# Update User, WorkingDirectory, Environment, ExecStart paths

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable claude-limit-monitor

# Start service
sudo systemctl start claude-limit-monitor
```

### 6. Verify Service

```bash
# Check status
sudo systemctl status claude-limit-monitor

# View logs
sudo journalctl -u claude-limit-monitor -f

# Check usage stats
claude-stats
```

### 7. Add to PATH (optional)

```bash
# Add scripts directory to PATH
echo 'export PATH="$HOME/Claude/scripts:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Now you can run from anywhere
claude-stats
```

---

## Service Management

```bash
# Start service
sudo systemctl start claude-limit-monitor

# Stop service
sudo systemctl stop claude-limit-monitor

# Restart service
sudo systemctl restart claude-limit-monitor

# Disable (don't start on boot)
sudo systemctl disable claude-limit-monitor

# View logs
sudo journalctl -u claude-limit-monitor -n 50

# Follow logs in real-time
sudo journalctl -u claude-limit-monitor -f
```

---

## Testing Notifications

```bash
# Test native notifications
notify-send "Claude Limit Warning" "80% used (36/45)"

# If this works, daemon notifications will work too
```

---

## Troubleshooting

**Service won't start:**
```bash
# Check logs for errors
sudo journalctl -u claude-limit-monitor -n 50

# Test script manually
python3 /home/tallest/Claude/scripts/claude-limit-daemon.py
```

**Permission errors:**
- Ensure User in service file matches your username
- Ensure CLAUDE_HOME path is correct and accessible

**Import errors:**
```bash
# Install psutil
pip3 install psutil --break-system-packages
```

**No activity detected:**
- Verify Claude Desktop or Code is running
- Check process names: `ps aux | grep -i claude`
- Daemon may need refinement for your system

**Notifications not showing:**
```bash
# Test notify-send
notify-send "Test" "Message"

# Check if notification daemon running
ps aux | grep notification
```

---

## Uninstall

```bash
sudo systemctl stop claude-limit-monitor
sudo systemctl disable claude-limit-monitor
sudo rm /etc/systemd/system/claude-limit-monitor.service
sudo systemctl daemon-reload
```

---

## Advanced: Multiple Machines

If you use Claude on multiple machines, each machine should run its own daemon. Usage is tracked per-machine, not globally.

To see combined usage, you would need to aggregate state files manually (future feature).
