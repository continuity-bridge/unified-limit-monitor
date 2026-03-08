#!/usr/bin/env python3
"""
claude-limit-daemon.py - Unified Claude usage limit monitor v2

Changes from v1:
  - Real usage data from https://api.anthropic.com/api/oauth/usage
  - Cookie-based auth (reads from Claude Desktop Cookies SQLite — no decryption needed)
  - pystray + Pillow cross-platform system tray icon
  - 5-minute polling (respects Anthropic's rate limit on this endpoint)
  - State file written for claude-stats CLI consumption
  - Graceful degradation: tray optional, API errors use stale data

Author: Vector
Created: 2026-03-07
Updated: 2026-03-08 (v2 — real API, pystray tray)
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import threading
import configparser
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

# ── Optional deps — graceful degradation ──────────────────────────────────────

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("Note: pystray/Pillow not installed. Running headless (no tray icon).", file=sys.stderr)
    print("      Install with: pip install pystray Pillow --break-system-packages", file=sys.stderr)

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# ── Constants ─────────────────────────────────────────────────────────────────

API_ENDPOINT   = 'https://api.anthropic.com/api/oauth/usage'
COOKIE_DB_PATH = Path.home() / '.config/Claude/Cookies'
COOKIE_DB_TMP  = Path('/tmp/claude-cookies-monitor.db')

ICON_SIZE      = 64          # px
DEFAULT_POLL   = 300         # 5 minutes (seconds)

COLOR_GREEN    = (34, 197, 94)   # Tailwind green-500
COLOR_YELLOW   = (234, 179, 8)   # Tailwind yellow-500
COLOR_ORANGE   = (249, 115, 22)  # Tailwind orange-500
COLOR_RED      = (239, 68, 68)   # Tailwind red-500
COLOR_GRAY     = (107, 114, 128) # Tailwind gray-500 (unknown)


# ── Path detection ─────────────────────────────────────────────────────────────

def detect_claude_home() -> Optional[Path]:
    """Find CLAUDE_HOME across platforms."""
    if env_home := os.getenv('CLAUDE_HOME'):
        return Path(env_home)

    if sys.platform == 'win32':
        for drive in ['D:', 'C:']:
            candidate = Path(f"{drive}/Claude")
            if candidate.exists():
                return candidate

    unix_home = Path.home() / 'Claude'
    if unix_home.exists():
        return unix_home

    laptop_home = Path.home() / 'continuity-bridge_tallest-anchor'
    if laptop_home.exists():
        return laptop_home

    return None


def load_config(config_path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config['account']       = {'plan': 'pro'}
    config['api']           = {
        'poll_interval': str(DEFAULT_POLL),
        'timeout': '15',
        'retry_on_429': 'true',
    }
    config['notifications'] = {
        'threshold_warning':  '80',
        'threshold_urgent':   '90',
        'threshold_critical': '95',
        'cooldown_seconds':   '300',
    }
    config['tray']          = {
        'enabled': 'true',
        'show_percent_in_label': 'true',
    }
    if config_path.exists():
        config.read(config_path)
    return config


# ── Cookie reader ─────────────────────────────────────────────────────────────

class CookieReader:
    """
    Reads session cookie from Claude Desktop's SQLite Cookies file.

    Claude Desktop is an Electron / Chromium app. Most cookies are stored as
    plaintext in the SQLite Cookies database. The sessionKey cookie (which
    authenticates the claude.ai session) is NOT encrypted — it's stored in the
    `value` column, not `encrypted_value`.
    """

    def __init__(self, db_path: Path = COOKIE_DB_PATH, tmp: Path = COOKIE_DB_TMP):
        self.db_path = db_path
        self.tmp     = tmp
        self._cache: Dict[str, str] = {}
        self._cache_expires: float  = 0

    def _refresh(self):
        """Copy DB and read all plaintext claude.ai cookies."""
        if not self.db_path.exists():
            self._cache = {}
            return

        try:
            shutil.copy2(self.db_path, self.tmp)
            conn = sqlite3.connect(self.tmp)
            cur  = conn.cursor()
            cur.execute(
                "SELECT name, value FROM cookies "
                "WHERE host_key LIKE '%.claude.ai' AND length(value) > 0"
            )
            self._cache = {name: val for name, val in cur.fetchall()}
            conn.close()
        except Exception as e:
            print(f"Warning: Cookie read failed: {e}", file=sys.stderr)
            self._cache = {}

    def get_all(self, max_age: float = 3600) -> Dict[str, str]:
        """Return all plaintext cookies, refreshing if stale."""
        if time.time() > self._cache_expires:
            self._refresh()
            self._cache_expires = time.time() + max_age
        return self._cache

    def session_key(self) -> Optional[str]:
        return self.get_all().get('sessionKey')

    def cookie_header(self) -> str:
        return '; '.join(f'{k}={v}' for k, v in self.get_all().items())


# ── Usage data ────────────────────────────────────────────────────────────────

class UsageData:
    """Parsed API response + helpers for display."""

    def __init__(self):
        self.percent_5h:   float          = 0.0
        self.used_5h:      float          = 0.0
        self.limit_5h:     float          = 0.0
        self.reset_at:     Optional[str]  = None   # ISO-8601
        self.percent_week: float          = 0.0
        self.used_week:    float          = 0.0
        self.limit_week:   float          = 0.0
        self.source:       str            = 'unknown'
        self.last_updated: str            = ''
        self.raw:          Optional[Dict] = None   # full API response for debugging

    # ── Display helpers ───────────────────────────────────────────────────────

    @property
    def display_pct(self) -> int:
        return min(100, max(0, int(self.percent_5h)))

    @property
    def status_color(self) -> tuple:
        p = self.percent_5h
        if p >= 95: return COLOR_RED
        if p >= 80: return COLOR_ORANGE
        if p >= 60: return COLOR_YELLOW
        return COLOR_GREEN

    @property
    def time_to_reset(self) -> Optional[timedelta]:
        if not self.reset_at:
            return None
        try:
            ts = self.reset_at.replace('Z', '+00:00')
            reset = datetime.fromisoformat(ts)
            now   = datetime.now(timezone.utc)
            diff  = reset - now
            return diff if diff.total_seconds() > 0 else timedelta(0)
        except Exception:
            return None

    @property
    def reset_str(self) -> str:
        td = self.time_to_reset
        if td is None:
            return 'unknown'
        total = int(td.total_seconds())
        h, m  = divmod(total // 60, 60)
        return f'{h}h {m}m'

    # ── Serialisation (for state file / claude-stats) ─────────────────────────

    def to_dict(self) -> Dict:
        td = self.time_to_reset
        return {
            'source':       self.source,
            'last_updated': self.last_updated,
            'session': {
                'percent':  self.percent_5h,
                'used':     self.used_5h,
                'limit':    self.limit_5h,
                'reset_at': self.reset_at,
                'time_to_reset_seconds': int(td.total_seconds()) if td else 0,
            },
            'weekly': {
                'percent': self.percent_week,
                'used':    self.used_week,
                'limit':   self.limit_week,
            },
            # Backwards-compat fields for old claude-stats
            'plan':         'api',
            'used':         self.used_5h,
            'limit':        self.limit_5h,
            'percent':      self.percent_5h,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'UsageData':
        u = cls()
        s = d.get('session', {})
        w = d.get('weekly',  {})
        u.percent_5h   = float(s.get('percent', d.get('percent', 0)))
        u.used_5h      = float(s.get('used',    d.get('used',    0)))
        u.limit_5h     = float(s.get('limit',   d.get('limit',   0)))
        u.reset_at     = s.get('reset_at')
        u.percent_week = float(w.get('percent', 0))
        u.used_week    = float(w.get('used',    0))
        u.limit_week   = float(w.get('limit',   0))
        u.source       = d.get('source', 'file')
        u.last_updated = d.get('last_updated', '')
        return u


# ── API client ────────────────────────────────────────────────────────────────

class AnthropicUsageAPI:
    """
    Polls https://api.anthropic.com/api/oauth/usage using the Claude Desktop
    session cookie for auth.

    The response schema is adaptive — we log the raw response on first success
    so the format can be confirmed and the parser tuned.
    """

    def __init__(self, cookie_reader: CookieReader, timeout: int = 15):
        self.cookies   = cookie_reader
        self.timeout   = timeout
        self._stale:   Optional[UsageData] = None
        self._schema_logged = False

    def fetch(self) -> Optional[UsageData]:
        """Fetch usage. Returns None only if auth is broken; returns stale data on 429."""
        if not self.cookies.session_key():
            print("Warning: No sessionKey in Claude cookies — is Claude Desktop running?", file=sys.stderr)
            return None

        req = urllib.request.Request(
            API_ENDPOINT,
            headers={
                'Cookie':       self.cookies.cookie_header(),
                'Content-Type': 'application/json',
                'User-Agent':   'Claude-Desktop/2.1.51 Linux',
                'Origin':       'https://claude.ai',
                'Referer':      'https://claude.ai/',
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw  = json.loads(resp.read())
                data = self._parse(raw)

                if not self._schema_logged:
                    # Log actual schema once so we can verify/tune parser
                    print(f"[API] First successful response shape: {list(raw.keys())}", file=sys.stderr)
                    self._schema_logged = True

                self._stale = data
                return data

        except urllib.error.HTTPError as e:
            if e.code == 429:
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"[{ts}] Rate limited — returning stale data", file=sys.stderr)
                return self._stale
            print(f"HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
            return self._stale

        except Exception as e:
            print(f"Fetch error: {e}", file=sys.stderr)
            return self._stale

    def _parse(self, raw: Dict) -> UsageData:
        u              = UsageData()
        u.raw          = raw
        u.last_updated = datetime.now().isoformat()
        u.source       = 'api'

        # ── Shape A: {session: {used, limit, percent?, reset_at}, weekly: {...}} ──
        if 'session' in raw:
            s = raw['session']
            u.used_5h   = float(s.get('used',  0))
            u.limit_5h  = float(s.get('limit', 0))
            u.reset_at  = s.get('reset_at') or s.get('resetAt')
            u.percent_5h = (
                float(s['percent']) if 'percent' in s
                else (u.used_5h / u.limit_5h * 100 if u.limit_5h else 0)
            )

        if 'weekly' in raw or 'week' in raw:
            w = raw.get('weekly') or raw.get('week', {})
            u.used_week    = float(w.get('used',  0))
            u.limit_week   = float(w.get('limit', 0))
            u.percent_week = (
                float(w['percent']) if 'percent' in w
                else (u.used_week / u.limit_week * 100 if u.limit_week else 0)
            )

        # ── Shape B: flat {percent_5h, used_5h, limit_5h, reset_at, ...} ──────
        if 'percent_5h' in raw:
            u.percent_5h = float(raw['percent_5h'])
            u.used_5h    = float(raw.get('used_5h',   0))
            u.limit_5h   = float(raw.get('limit_5h',  0))
            u.reset_at   = raw.get('reset_at')

        if 'percent_week' in raw:
            u.percent_week = float(raw['percent_week'])
            u.used_week    = float(raw.get('used_week',  0))
            u.limit_week   = float(raw.get('limit_week', 0))

        # ── Shape C: nested {data: {session_usage_percentage, ...}} ─────────
        if 'data' in raw:
            d = raw['data']
            if 'session_usage_percentage' in d:
                u.percent_5h = float(d['session_usage_percentage'])
            if 'weekly_usage_percentage' in d:
                u.percent_week = float(d['weekly_usage_percentage'])
            if 'session_usage' in d:
                sess = d['session_usage']
                u.used_5h  = float(sess.get('used',  0))
                u.limit_5h = float(sess.get('limit', 0))
                u.reset_at = sess.get('reset_at')

        # ── Shape D: {message_usage: {used, limit, ...}} ──────────────────────
        if 'message_usage' in raw:
            m = raw['message_usage']
            u.used_5h  = float(m.get('used',  0))
            u.limit_5h = float(m.get('limit', 0))
            u.reset_at = m.get('reset_at')
            if u.limit_5h:
                u.percent_5h = u.used_5h / u.limit_5h * 100

        return u


# ── State file (for claude-stats CLI) ─────────────────────────────────────────

def write_state(state_file: Path, data: UsageData):
    tmp = state_file.with_suffix('.tmp')
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, 'w') as f:
        json.dump(data.to_dict(), f, indent=2)
    tmp.replace(state_file)


def read_state(state_file: Path) -> Optional[UsageData]:
    if not state_file.exists():
        return None
    try:
        with open(state_file) as f:
            return UsageData.from_dict(json.load(f))
    except Exception:
        return None


# ── Notifications ──────────────────────────────────────────────────────────────

class NotificationManager:

    def __init__(self, config: configparser.ConfigParser):
        self.warn_pct     = float(config.get('notifications', 'threshold_warning',  fallback='80'))
        self.urgent_pct   = float(config.get('notifications', 'threshold_urgent',   fallback='90'))
        self.critical_pct = float(config.get('notifications', 'threshold_critical', fallback='95'))
        self.cooldown     = float(config.get('notifications', 'cooldown_seconds',   fallback='300'))
        self._last: Dict[str, float] = {}

    def check(self, data: UsageData):
        p = data.percent_5h
        if p >= self.critical_pct:
            level, title, msg = 'critical', '🔴 Claude Usage Critical', f"{p:.0f}% — limit almost reached!"
        elif p >= self.urgent_pct:
            level, title, msg = 'urgent', '🟠 Claude Usage High', f"{p:.0f}% — consider pausing"
        elif p >= self.warn_pct:
            level, title, msg = 'warning', '🟡 Claude Usage Warning', f"{p:.0f}% used"
        else:
            return

        now = time.time()
        if now - self._last.get(level, 0) < self.cooldown:
            return

        self._send(title, msg)
        self._last[level] = now

    @staticmethod
    def _send(title: str, msg: str):
        if sys.platform == 'linux':
            os.system(f'notify-send "{title}" "{msg}"')
        elif sys.platform == 'win32':
            print(f'[NOTIFICATION] {title}: {msg}')
        elif sys.platform == 'darwin':
            os.system(f"osascript -e 'display notification \"{msg}\" with title \"{title}\"'")


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _make_icon_image(data: Optional[UsageData]) -> 'Image.Image':
    """Generate a 64×64 RGBA icon: colored ring + % text."""
    size  = ICON_SIZE
    img   = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)

    color = data.status_color if data else COLOR_GRAY
    pct   = data.display_pct  if data else 0

    # Filled background circle
    draw.ellipse([2, 2, size - 2, size - 2], fill=(*color, 220))

    # White text
    label = f'{pct}%'
    # Try to get a font; fall back to default
    font  = None
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                                  size=18 if pct < 100 else 15)
    except Exception:
        try:
            font = ImageFont.load_default()
        except Exception:
            pass

    if font:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        tx   = (size - tw) // 2
        ty   = (size - th) // 2
        draw.text((tx, ty), label, fill=(255, 255, 255, 255), font=font)

    return img


class TrayManager:
    """Manages the pystray tray icon. Runs in its own thread."""

    def __init__(self, config: configparser.ConfigParser, poll_callback):
        self._config   = config
        self._poll     = poll_callback   # callable: trigger immediate poll
        self._icon     = None
        self._data:    Optional[UsageData] = None
        self._lock     = threading.Lock()

    def update(self, data: Optional[UsageData]):
        """Called from polling thread with fresh data."""
        with self._lock:
            self._data = data

        if self._icon:
            self._icon.icon  = _make_icon_image(data)
            self._icon.title = self._tooltip(data)

    def _tooltip(self, data: Optional[UsageData]) -> str:
        if not data:
            return 'Claude Limit Monitor (no data)'
        lines = [f'Claude Usage: {data.display_pct}%']
        if data.used_5h and data.limit_5h:
            lines.append(f'{data.used_5h:.0f}/{data.limit_5h:.0f} messages (5h window)')
        if data.reset_at:
            lines.append(f'Resets in {data.reset_str}')
        if data.percent_week:
            lines.append(f'Weekly: {data.percent_week:.0f}%')
        return '\n'.join(lines)

    def _menu_items(self):
        if not TRAY_AVAILABLE:
            return []
        with self._lock:
            data = self._data

        items = []

        if data:
            items += [
                pystray.MenuItem(
                    f'{data.display_pct}%  (5h window)',
                    None, enabled=False
                ),
                pystray.MenuItem(
                    f'Resets in {data.reset_str}',
                    None, enabled=False
                ),
            ]
            if data.percent_week > 0:
                items.append(pystray.MenuItem(
                    f'Weekly: {data.percent_week:.0f}%',
                    None, enabled=False
                ))
        else:
            items.append(pystray.MenuItem('Waiting for data…', None, enabled=False))

        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Refresh Now', lambda icon, item: self._poll()),
            pystray.MenuItem('Quit', lambda icon, item: icon.stop()),
        ]
        return items

    def run(self):
        """Start the tray icon (blocks until quit)."""
        if not TRAY_AVAILABLE:
            return

        img = _make_icon_image(None)

        self._icon = pystray.Icon(
            name    = 'claude-limit-monitor',
            icon    = img,
            title   = 'Claude Limit Monitor (starting…)',
            menu    = pystray.Menu(lambda: self._menu_items()),
        )
        self._icon.run()


# ── Main daemon loop ───────────────────────────────────────────────────────────

def main():
    # ── Setup ────────────────────────────────────────────────────────────────
    claude_home = detect_claude_home()
    if not claude_home:
        print("ERROR: Cannot locate CLAUDE_HOME", file=sys.stderr)
        print("Set CLAUDE_HOME environment variable or ensure ~/Claude directory exists", file=sys.stderr)
        sys.exit(1)

    config_path = claude_home / '.claude' / 'unified-limit-monitor.conf'
    state_file  = claude_home / '.claude' / 'logs' / 'limit-tracker-state.json'

    config = load_config(config_path)

    poll_interval = config.getint('api', 'poll_interval', fallback=DEFAULT_POLL)
    timeout       = config.getint('api', 'timeout',       fallback=15)
    tray_enabled  = config.getboolean('tray', 'enabled',  fallback=True)

    cookies  = CookieReader()
    api      = AnthropicUsageAPI(cookies, timeout=timeout)
    notifier = NotificationManager(config)

    print(f'Claude Limit Monitor v2 (real API)')
    print(f'CLAUDE_HOME : {claude_home}')
    print(f'State file  : {state_file}')
    print(f'Poll interval: {poll_interval}s')
    print(f'Tray icon   : {"enabled" if tray_enabled and TRAY_AVAILABLE else "disabled"}')
    print(f'Ctrl-C to stop')
    print()

    # ── Tray setup (optional) ────────────────────────────────────────────────
    tray: Optional[TrayManager] = None
    if tray_enabled and TRAY_AVAILABLE:
        tray = TrayManager(config, poll_callback=lambda: None)  # callback wired below

    # ── Polling loop (runs in background thread) ──────────────────────────────
    last_poll    = 0.0
    force_poll   = threading.Event()

    def poll_loop():
        nonlocal last_poll
        while True:
            now = time.time()
            if now - last_poll >= poll_interval or force_poll.is_set():
                force_poll.clear()
                ts   = datetime.now().strftime('%H:%M:%S')
                data = api.fetch()

                if data:
                    write_state(state_file, data)
                    notifier.check(data)
                    if tray:
                        tray.update(data)
                    print(f'[{ts}] {data.display_pct}% | reset in {data.reset_str} '
                          f'| weekly {data.percent_week:.0f}%')
                else:
                    print(f'[{ts}] No data (check Claude Desktop is running)')

                last_poll = time.time()

            time.sleep(5)  # check force_poll frequently; real sleep handled above

    # Wire the force-poll callback
    if tray:
        tray._poll = lambda: force_poll.set()

    poll_thread = threading.Thread(target=poll_loop, daemon=True, name='poll')
    poll_thread.start()

    # ── Main thread: tray or block ────────────────────────────────────────────
    try:
        if tray and TRAY_AVAILABLE:
            tray.run()   # blocks until user quits from tray menu
        else:
            # Headless mode — just run until Ctrl-C
            while poll_thread.is_alive():
                poll_thread.join(timeout=1)
    except KeyboardInterrupt:
        pass

    print('\nClaude Limit Monitor stopped.')


if __name__ == '__main__':
    main()
