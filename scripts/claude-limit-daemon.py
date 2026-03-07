#!/usr/bin/env python3
"""
claude-limit-daemon.py - Unified Claude usage limit monitor

Tracks usage across claude.ai, Claude Code, and Cowork in a unified pool.
Provides notifications at configurable thresholds.

Author: Vector
Created: 2026-03-07
"""

import os
import sys
import time
import json
import psutil
import configparser
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List


@dataclass
class UsageEvent:
    """Single usage event"""
    timestamp: str
    product: str  # 'chat', 'code', 'cowork'
    weight: float
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


class LimitTracker:
    """Tracks usage across rolling window"""
    
    def __init__(self, plan: str = 'pro', window_hours: int = 5):
        self.plan = plan
        self.window_hours = window_hours
        
        # Plan limits (messages/units per 5-hour window)
        self.limits = {
            'pro': 45,
            'max_5x': 225,   # 5x Pro
            'max_20x': 900   # 20x Pro
        }
        
        # Consumption weights (relative to chat)
        self.weights = {
            'chat': 1.0,
            'code': 5.0,     # Heavier usage
            'cowork': 10.0   # Heaviest usage
        }
        
        self.events: deque[UsageEvent] = deque()
    
    def add_event(self, product: str):
        """Record usage event"""
        event = UsageEvent(
            timestamp=datetime.now().isoformat(),
            product=product,
            weight=self.weights.get(product, 1.0)
        )
        self.events.append(event)
        self._cleanup_old()
    
    def _cleanup_old(self):
        """Remove events outside rolling window"""
        cutoff = datetime.now() - timedelta(hours=self.window_hours)
        
        while self.events:
            event_time = datetime.fromisoformat(self.events[0].timestamp)
            if event_time < cutoff:
                self.events.popleft()
            else:
                break
    
    def get_status(self) -> Dict:
        """Get current usage status"""
        self._cleanup_old()
        
        # Calculate weighted usage
        total_weight = sum(e.weight for e in self.events)
        
        # Breakdown by product
        by_product = {}
        for product in ['chat', 'code', 'cowork']:
            count = sum(1 for e in self.events if e.product == product)
            weight = sum(e.weight for e in self.events if e.product == product)
            by_product[product] = {
                'count': count,
                'weight': weight
            }
        
        # Calculate next reset time
        if self.events:
            oldest = datetime.fromisoformat(self.events[0].timestamp)
            next_reset = oldest + timedelta(hours=self.window_hours)
            time_to_reset = next_reset - datetime.now()
        else:
            time_to_reset = timedelta(0)
        
        limit = self.limits.get(self.plan, 45)
        remaining = max(0, limit - total_weight)
        percent = (total_weight / limit) * 100 if limit > 0 else 0
        
        return {
            'plan': self.plan,
            'window_hours': self.window_hours,
            'limit': limit,
            'used': total_weight,
            'remaining': remaining,
            'percent': percent,
            'by_product': by_product,
            'next_reset': next_reset.isoformat() if self.events else None,
            'time_to_reset_seconds': int(time_to_reset.total_seconds()),
            'event_count': len(self.events)
        }


class ProcessMonitor:
    """Monitors Claude processes"""
    
    def __init__(self):
        self.last_seen = {
            'chat': None,    # Claude Desktop (chat mode)
            'code': None,    # Claude Code CLI
            'cowork': None   # Claude Desktop (cowork mode)
        }
    
    def detect_activity(self) -> Optional[str]:
        """
        Detect which Claude product is currently active.
        Returns product name if new activity detected, None otherwise.
        """
        
        # Check for Claude Desktop
        desktop_active = self._check_process(['claude', 'Claude'])
        
        # Check for Claude Code (terminal)
        code_active = self._check_process(['claude-code', 'claude'], cmdline_contains='claude')
        
        # Heuristic: If Desktop active, check for Cowork indicators
        # (This is approximate - refine based on actual process details)
        if desktop_active:
            # For now, assume chat mode
            # TODO: Detect Cowork vs Chat mode more accurately
            product = 'chat'
        elif code_active:
            product = 'code'
        else:
            return None
        
        # Check if this is new activity (debounce)
        now = time.time()
        last = self.last_seen.get(product)
        
        # Only count as new activity if >1 minute since last detection
        if last is None or (now - last) > 60:
            self.last_seen[product] = now
            return product
        
        return None
    
    def _check_process(self, names: List[str], cmdline_contains: Optional[str] = None) -> bool:
        """Check if process with given name(s) is running"""
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                proc_name = proc.info['name'].lower()
                
                # Check name match
                if any(name.lower() in proc_name for name in names):
                    # If cmdline filter specified, check it
                    if cmdline_contains:
                        cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                        if cmdline_contains.lower() in cmdline:
                            return True
                    else:
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return False


class NotificationManager:
    """Handles desktop notifications"""
    
    def __init__(self, config: configparser.ConfigParser):
        self.config = config
        self.last_notification = {}
        self.notification_cooldown = 300  # 5 minutes
    
    def check_and_notify(self, status: Dict):
        """Check thresholds and send notifications if needed"""
        percent = status['percent']
        
        # Get thresholds from config
        warning = float(self.config.get('notifications', 'threshold_warning', fallback='80'))
        urgent = float(self.config.get('notifications', 'threshold_urgent', fallback='90'))
        critical = float(self.config.get('notifications', 'threshold_critical', fallback='95'))
        
        # Determine notification level
        if percent >= critical:
            level = 'critical'
            title = '🔴 Claude Usage Critical'
            message = f"{percent:.0f}% used ({status['used']:.0f}/{status['limit']})\nLimit reached soon!"
        elif percent >= urgent:
            level = 'urgent'
            title = '🟠 Claude Usage High'
            message = f"{percent:.0f}% used ({status['used']:.0f}/{status['limit']})\nConsider waiting for reset"
        elif percent >= warning:
            level = 'warning'
            title = '🟡 Claude Usage Warning'
            message = f"{percent:.0f}% used ({status['used']:.0f}/{status['limit']})"
        else:
            return  # No notification needed
        
        # Check cooldown
        now = time.time()
        last = self.last_notification.get(level, 0)
        if now - last < self.notification_cooldown:
            return  # Too soon since last notification
        
        # Send notification
        self._send_notification(title, message)
        self.last_notification[level] = now
    
    def _send_notification(self, title: str, message: str):
        """Send desktop notification"""
        if sys.platform == 'linux':
            # Use notify-send on Linux
            os.system(f'notify-send "{title}" "{message}"')
        elif sys.platform == 'win32':
            # TODO: Windows toast notification
            # For now, just print
            print(f"[NOTIFICATION] {title}: {message}")
        elif sys.platform == 'darwin':
            # macOS notification
            os.system(f'osascript -e \'display notification "{message}" with title "{title}"\'')


def detect_claude_home() -> Optional[Path]:
    """Detect CLAUDE_HOME directory"""
    
    # Check environment variable
    if env_home := os.getenv('CLAUDE_HOME'):
        return Path(env_home)
    
    # Platform-specific defaults
    if sys.platform == 'win32':
        for drive in ['D:', 'C:']:
            candidate = Path(f"{drive}/Claude")
            if candidate.exists():
                return candidate
    
    # Unix-like systems
    unix_home = Path.home() / "Claude"
    if unix_home.exists():
        return unix_home
    
    # Laptop location
    laptop_home = Path.home() / "continuity-bridge_tallest-anchor"
    if laptop_home.exists():
        return laptop_home
    
    return None


def load_config(config_path: Path) -> configparser.ConfigParser:
    """Load configuration file"""
    config = configparser.ConfigParser()
    
    # Defaults
    config['account'] = {'plan': 'pro'}
    config['limits'] = {
        'rolling_window_hours': '5',
        'rolling_window_limit': '45'
    }
    config['weights'] = {
        'chat': '1.0',
        'code': '5.0',
        'cowork': '10.0'
    }
    config['notifications'] = {
        'threshold_warning': '80',
        'threshold_urgent': '90',
        'threshold_critical': '95'
    }
    config['tracking'] = {
        'detect_chat': 'true',
        'detect_code': 'true',
        'detect_cowork': 'true',
        'update_interval': '60'
    }
    
    # Load from file if exists
    if config_path.exists():
        config.read(config_path)
    
    return config


def save_state(state_file: Path, tracker: LimitTracker):
    """Save tracker state to file"""
    state = {
        'plan': tracker.plan,
        'window_hours': tracker.window_hours,
        'events': [asdict(e) for e in tracker.events]
    }
    
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def load_state(state_file: Path, config: configparser.ConfigParser) -> LimitTracker:
    """Load tracker state from file"""
    plan = config.get('account', 'plan', fallback='pro')
    window_hours = config.getint('limits', 'rolling_window_hours', fallback=5)
    
    tracker = LimitTracker(plan=plan, window_hours=window_hours)
    
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
            
            # Restore events
            for event_data in state.get('events', []):
                tracker.events.append(UsageEvent.from_dict(event_data))
            
            # Cleanup old events
            tracker._cleanup_old()
        except Exception as e:
            print(f"Warning: Could not load state: {e}", file=sys.stderr)
    
    return tracker


def main():
    """Main daemon loop"""
    
    # Detect CLAUDE_HOME
    claude_home = detect_claude_home()
    if not claude_home:
        print("ERROR: Cannot locate CLAUDE_HOME", file=sys.stderr)
        print("Set CLAUDE_HOME environment variable or ensure Claude directory exists", file=sys.stderr)
        sys.exit(1)
    
    # Setup paths
    config_path = claude_home / '.claude' / 'unified-limit-monitor.conf'
    state_file = claude_home / '.claude' / 'logs' / 'limit-tracker-state.json'
    log_dir = claude_home / '.claude' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Load configuration
    config = load_config(config_path)
    
    # Initialize components
    tracker = load_state(state_file, config)
    monitor = ProcessMonitor()
    notifier = NotificationManager(config)
    
    update_interval = config.getint('tracking', 'update_interval', fallback=60)
    
    print(f"Claude Limit Monitor Started")
    print(f"CLAUDE_HOME: {claude_home}")
    print(f"Plan: {tracker.plan}")
    print(f"Limit: {tracker.limits[tracker.plan]} units per {tracker.window_hours}h")
    print(f"State file: {state_file}")
    print(f"Update interval: {update_interval}s")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    try:
        while True:
            # Detect activity
            product = monitor.detect_activity()
            if product:
                tracker.add_event(product)
                status = tracker.get_status()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Activity detected: {product} "
                      f"(usage: {status['used']:.1f}/{status['limit']} = {status['percent']:.0f}%)")
                
                # Check notification thresholds
                notifier.check_and_notify(status)
                
                # Save state
                save_state(state_file, tracker)
            
            time.sleep(update_interval)
    
    except KeyboardInterrupt:
        print("\nClaude Limit Monitor Stopped")
        save_state(state_file, tracker)
        sys.exit(0)
    
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        save_state(state_file, tracker)
        sys.exit(1)


if __name__ == '__main__':
    main()
