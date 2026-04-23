#!/usr/bin/env python3
"""
TokioAI Interactive CLI v4.0 — Pro Terminal Interface.

Inspired by Claude Code CLI architecture:
- Robust terminal cleanup (signal handlers + atexit + cleanup registry)
- Safe stdout/stdin (EPIPE handling, destroyed stream checks)
- Proper escape sequence handling (drain stdin after every tool)
- Cleanup registry pattern for guaranteed resource release
- Session cost persistence across restarts
- Failsafe terminal restore on ANY exit (crash, signal, normal)

Features:
- Rich markdown rendering (headers, bold, code blocks, tables, lists)
- Gradient banner with system info
- Styled tool calls with icons & progress
- Status bar with token/tool/time/cost tracking
- Streaming responses (token by token)
- Escape to cancel running requests
- readline history & session persistence
- 14 slash commands (instant, no LLM)
- Tab completion for commands, tools, slash commands
- Multi-line input with backslash continuation
- Cross-platform: Linux, macOS, Windows
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import platform
import re
import signal
import sys
import time
import warnings
import json as _json
import subprocess as _sp
from typing import Optional, Set, Callable

_IS_WINDOWS = platform.system() == "Windows"

# Cross-platform readline
if _IS_WINDOWS:
    try:
        import pyreadline3 as readline  # type: ignore
    except ImportError:
        import readline  # type: ignore
else:
    import readline

# Cross-platform terminal modules
if _IS_WINDOWS:
    import msvcrt
    select = None  # type: ignore
    termios = None  # type: ignore
    tty = None  # type: ignore
else:
    import select
    import termios
    import tty

# Suppress asyncio warnings
warnings.filterwarnings("ignore", message="child process pid.*exit status already read")
logging.getLogger("asyncio").setLevel(logging.ERROR)

# ═══════════════════════════════════════════════════════
# CLEANUP REGISTRY — Inspired by Claude Code
# Guarantees cleanup runs on ANY exit (crash, signal, normal)
# ═══════════════════════════════════════════════════════

_cleanup_functions: Set[Callable] = set()
_terminal_saved_state = None
_shutting_down = False


def register_cleanup(fn: Callable) -> Callable:
    """Register a cleanup function. Returns unregister function."""
    _cleanup_functions.add(fn)
    return lambda: _cleanup_functions.discard(fn)


def _run_all_cleanups():
    """Run all registered cleanup functions. Safe to call multiple times."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    for fn in list(_cleanup_functions):
        try:
            fn()
        except Exception:
            pass


def _restore_terminal_sync():
    """
    Synchronous terminal restore — the most critical cleanup.
    Inspired by Claude Code's cleanupTerminalModes() which uses writeSync.
    Must work even if Python is half-dead (signal handler, atexit).
    """
    if _IS_WINDOWS:
        return
    try:
        fd = sys.stdin.fileno()
        if _terminal_saved_state and os.isatty(fd):
            termios.tcsetattr(fd, termios.TCSANOW, _terminal_saved_state)
    except Exception:
        pass
    # Failsafe: stty sane always works even if termios state is corrupted
    try:
        os.system("stty sane 2>/dev/null")
    except Exception:
        pass
    # Show cursor (in case we hid it)
    try:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    except Exception:
        pass


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM — restore terminal first, then exit."""
    _restore_terminal_sync()
    _run_all_cleanups()
    # Re-raise with default handler
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


# Register signal handlers and atexit EARLY
if not _IS_WINDOWS:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    try:
        signal.signal(signal.SIGHUP, _signal_handler)
    except (AttributeError, OSError):
        pass

atexit.register(_restore_terminal_sync)
atexit.register(_run_all_cleanups)


# ═══════════════════════════════════════════════════════
# SAFE I/O — Inspired by Claude Code's process.ts
# Handles EPIPE, destroyed streams, encoding errors
# ═══════════════════════════════════════════════════════

def _safe_write(data: str):
    """Write to stdout safely. Handles EPIPE and encoding errors."""
    try:
        if sys.stdout.closed:
            return
        sys.stdout.write(data)
        sys.stdout.flush()
    except (BrokenPipeError, IOError, OSError):
        # Pipe broken (e.g., output piped to head)
        try:
            sys.stdout.close()
        except Exception:
            pass
    except UnicodeEncodeError:
        # Terminal doesn't support the character
        try:
            sys.stdout.write(data.encode('ascii', errors='replace').decode('ascii'))
            sys.stdout.flush()
        except Exception:
            pass


def _safe_print(data: str = "", end: str = "\n"):
    """Print safely."""
    _safe_write(data + end)


# ═══════════════════════════════════════════════════════
# STDIN MANAGEMENT — Inspired by Claude Code
# Proper flush, drain, and keypress detection
# ═══════════════════════════════════════════════════════

def _flush_stdin():
    """Flush any pending stdin data. Critical after cbreak mode."""
    if not sys.stdin.isatty():
        return
    try:
        if _IS_WINDOWS:
            while msvcrt.kbhit():
                msvcrt.getch()
        else:
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        pass


def _drain_stdin():
    """
    Drain stdin completely — read and discard all pending bytes.
    More thorough than tcflush for edge cases where bytes arrive
    between tcflush and the next read.
    """
    if _IS_WINDOWS or not sys.stdin.isatty():
        return
    try:
        fd = sys.stdin.fileno()
        while True:
            rlist, _, _ = select.select([fd], [], [], 0)
            if not rlist:
                break
            os.read(fd, 4096)  # read and discard
    except Exception:
        pass


def _check_escape() -> bool:
    """Check if ESC key was pressed without blocking."""
    if not sys.stdin.isatty():
        return False
    try:
        if _IS_WINDOWS:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                return ch == b'\x1b'
        else:
            fd = sys.stdin.fileno()
            rlist, _, _ = select.select([fd], [], [], 0)
            if rlist:
                data = os.read(fd, 16)  # Read up to 16 bytes to consume full escape sequences
                if not data:
                    return False
                # Check if any byte is ESC (0x1b)
                if b'\x1b' in data:
                    # But ignore if it's part of a longer escape sequence that's NOT just ESC
                    # (e.g., arrow keys send ESC [ A)
                    # Pure ESC press: just the single byte 0x1b
                    if data == b'\x1b':
                        return True
                    # Or ESC followed by more — could be user rapidly pressing ESC
                    if data[0:1] == b'\x1b' and len(data) == 1:
                        return True
                    # Multiple ESCs means user is hammering escape
                    if data.count(b'\x1b'[0]) > 1:
                        return True
    except (OSError, IOError, ValueError):
        pass
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════
# TERMINAL MANAGEMENT — cbreak enter/exit
# ═══════════════════════════════════════════════════════

class TerminalManager:
    """
    Manages terminal mode transitions safely.
    Inspired by Claude Code's approach of saving/restoring terminal state
    with multiple fallback layers.
    """
    def __init__(self):
        self._saved_state = None
        self._cbreak_active = False

    def enter_cbreak(self):
        """Enter cbreak mode for escape key detection during streaming."""
        if self._cbreak_active or _IS_WINDOWS:
            return
        try:
            fd = sys.stdin.fileno()
            if os.isatty(fd):
                self._saved_state = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                self._cbreak_active = True
        except Exception:
            pass

    def exit_cbreak(self):
        """Exit cbreak mode and restore terminal."""
        if not self._cbreak_active or _IS_WINDOWS:
            return
        self._cbreak_active = False  # Set first to prevent re-entry

        # Layer 1: Restore saved state
        try:
            fd = sys.stdin.fileno()
            if self._saved_state and os.isatty(fd):
                termios.tcsetattr(fd, termios.TCSADRAIN, self._saved_state)
        except Exception:
            pass

        # Layer 2: stty sane as failsafe
        try:
            os.system("stty sane 2>/dev/null")
        except Exception:
            pass

        # Layer 3: Drain any garbage from stdin
        _drain_stdin()

    @property
    def is_active(self) -> bool:
        return self._cbreak_active



# ═══════════════════════════════════════════════════════
# ANSI Colors
# ═══════════════════════════════════════════════════════

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_ITALIC = "\033[3m"
C_UNDERLINE = "\033[4m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"
C_GRAY = "\033[90m"
C_BRIGHT_RED = "\033[91m"
C_BRIGHT_GREEN = "\033[92m"
C_BRIGHT_YELLOW = "\033[93m"
C_BRIGHT_BLUE = "\033[94m"
C_BRIGHT_MAGENTA = "\033[95m"
C_BRIGHT_CYAN = "\033[96m"
C_BRIGHT_WHITE = "\033[97m"
C_CLEAR_LINE = "\033[2K\033[G"
C_BG_GRAY = "\033[48;5;236m"
C_BG_DARK = "\033[48;5;233m"
C_BG_BLUE = "\033[48;5;24m"
C_BG_GREEN = "\033[48;5;22m"
C_BG_RED = "\033[48;5;52m"

def c256(n: int) -> str:
    return f"\033[38;5;{n}m"


# ═══════════════════════════════════════════════════════
# Terminal Width
# ═══════════════════════════════════════════════════════

def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


# ═══════════════════════════════════════════════════════
# History & Session Persistence
# ═══════════════════════════════════════════════════════

HISTORY_FILE = os.path.expanduser("~/.tokio_cli_history")
SESSION_FILE = os.path.expanduser("~/.tokio_cli_session.json")
COST_FILE = os.path.expanduser("~/.tokio_cli_costs.json")


# ═══════════════════════════════════════════════════════
# Tab Completion
# ═══════════════════════════════════════════════════════

_CLI_COMMANDS = [
    "exit", "quit", "help", "reset", "stats", "tools", "model", "clear",
    "unlimited", "persistent", "stop", "config",
    "/status", "/waf", "/health", "/drone", "/threats", "/entity",
    "/sitrep", "/see", "/containers", "/wifi", "/coffee", "/logs", "/ha", "/picar",
    "/gcp",
]

_TOOL_NAMES: list[str] = []


def _completer(text: str, state: int):
    candidates = _CLI_COMMANDS + _TOOL_NAMES
    matches = [c for c in candidates if c.lower().startswith(text.lower())]
    return matches[state] if state < len(matches) else None


def _load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
        readline.set_completer(_completer)
        readline.parse_and_bind('tab: complete')
        readline.set_completer_delims(' \t\n')
        readline.parse_and_bind('set horizontal-scroll-mode off')
        readline.parse_and_bind('set enable-bracketed-paste on')
        readline.parse_and_bind('set bell-style none')
        readline.parse_and_bind('set show-all-if-ambiguous on')
    except Exception:
        pass


def _save_history():
    try:
        readline.set_history_length(1000)
        readline.write_history_file(HISTORY_FILE)
    except Exception:
        pass


def _save_session_state(sid: str, last_messages: list):
    try:
        recent = last_messages[-20:] if last_messages else []
        state = {
            "session_id": sid,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": recent,
        }
        with open(SESSION_FILE, "w") as f:
            _json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _load_session_state():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as f:
                state = _json.load(f)
            ts = state.get("timestamp", "")
            if ts:
                from datetime import datetime, timedelta
                saved = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - saved > timedelta(days=7):
                    return None
            return state
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════
# COST PERSISTENCE — Inspired by Claude Code's cost-tracker.ts
# Saves/restores costs across CLI restarts
# ═══════════════════════════════════════════════════════

class CostTracker:
    """Track costs per model with session persistence."""

    # Costs per 1M tokens (USD) — updated June 2025
    MODEL_COSTS = {
        "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
        "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
        "claude-3-haiku": {"input": 0.25, "output": 1.25, "cache_read": 0.03, "cache_write": 0.3},
    }

    def __init__(self):
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cache_read = 0
        self.session_cache_write = 0
        self.session_cost_usd = 0.0
        self.model_usage: dict = {}
        self._model_key = "claude-sonnet-4"

    def add_usage(self, model: str, input_tokens: int, output_tokens: int,
                  cache_read: int = 0, cache_write: int = 0):
        """Record token usage."""
        self.session_input_tokens += input_tokens
        self.session_output_tokens += output_tokens
        self.session_cache_read += cache_read
        self.session_cache_write += cache_write

        # Find cost rates
        costs = None
        for key, val in self.MODEL_COSTS.items():
            if key in model.lower():
                costs = val
                self._model_key = key
                break
        if not costs:
            costs = self.MODEL_COSTS["claude-sonnet-4"]

        cost = (
            input_tokens * costs["input"] +
            output_tokens * costs["output"] +
            cache_read * costs.get("cache_read", 0) +
            cache_write * costs.get("cache_write", 0)
        ) / 1_000_000
        self.session_cost_usd += cost

        # Track per-model
        if model not in self.model_usage:
            self.model_usage[model] = {"input": 0, "output": 0, "cost": 0.0}
        self.model_usage[model]["input"] += input_tokens
        self.model_usage[model]["output"] += output_tokens
        self.model_usage[model]["cost"] += cost

    def format_cost(self) -> str:
        if self.session_cost_usd < 0.01:
            return f"${self.session_cost_usd:.4f}"
        return f"${self.session_cost_usd:.2f}"

    def estimate_single(self, model: str, input_tokens: int, output_tokens: int) -> str:
        """Estimate cost for a single response."""
        costs = None
        for key, val in self.MODEL_COSTS.items():
            if key in model.lower():
                costs = val
                break
        if not costs:
            costs = self.MODEL_COSTS["claude-sonnet-4"]
        cost = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
        if cost < 0.01:
            return f"${cost:.4f}"
        return f"${cost:.2f}"

    def save(self, session_id: str):
        """Persist costs to disk."""
        try:
            data = {
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "input_tokens": self.session_input_tokens,
                "output_tokens": self.session_output_tokens,
                "cache_read": self.session_cache_read,
                "cache_write": self.session_cache_write,
                "cost_usd": self.session_cost_usd,
                "model_usage": self.model_usage,
            }
            with open(COST_FILE, "w") as f:
                _json.dump(data, f, indent=2)
        except Exception:
            pass

    def restore(self, session_id: str) -> bool:
        """Restore costs from disk if same session."""
        try:
            if not os.path.exists(COST_FILE):
                return False
            with open(COST_FILE) as f:
                data = _json.load(f)
            if data.get("session_id") != session_id:
                return False
            self.session_input_tokens = data.get("input_tokens", 0)
            self.session_output_tokens = data.get("output_tokens", 0)
            self.session_cache_read = data.get("cache_read", 0)
            self.session_cache_write = data.get("cache_write", 0)
            self.session_cost_usd = data.get("cost_usd", 0.0)
            self.model_usage = data.get("model_usage", {})
            return True
        except Exception:
            return False



# ═══════════════════════════════════════════════════════
# Markdown Renderer
# ═══════════════════════════════════════════════════════

class MarkdownRenderer:
    """Renders markdown-like text with ANSI colors for terminal."""

    _BOLD = re.compile(r'\*\*(.+?)\*\*')
    _ITALIC = re.compile(r'(?<!\*)\*([^*]+?)\*(?!\*)')
    _INLINE_CODE = re.compile(r'`([^`\n]+?)`')
    _LINK = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    _STRIKETHROUGH = re.compile(r'~~(.+?)~~')

    @classmethod
    def render(cls, text: str) -> str:
        lines = text.split('\n')
        result = []
        in_code_block = False
        code_lang = ""

        for line in lines:
            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    code_lang = line.strip()[3:].strip()
                    lang_label = f" {code_lang}" if code_lang else ""
                    result.append(f"  {C_DIM}┌─{lang_label}{'─' * max(1, 40 - len(lang_label))}{C_RESET}")
                else:
                    in_code_block = False
                    result.append(f"  {C_DIM}└{'─' * 42}{C_RESET}")
                continue

            if in_code_block:
                result.append(f"  {C_DIM}│{C_RESET} {C_BRIGHT_GREEN}{line}{C_RESET}")
                continue

            # Headers
            if line.startswith('### '):
                result.append(f"  {C_BOLD}{C_CYAN}   {line[4:]}{C_RESET}")
                continue
            if line.startswith('## '):
                result.append(f"  {C_BOLD}{C_BRIGHT_CYAN}  {line[3:]}{C_RESET}")
                continue
            if line.startswith('# '):
                result.append(f"  {C_BOLD}{C_BRIGHT_WHITE}━━ {line[2:]} ━━{C_RESET}")
                continue

            # HR
            if re.match(r'^-{3,}$', line.strip()) or re.match(r'^\*{3,}$', line.strip()):
                w = min(_term_width() - 4, 60)
                result.append(f"  {C_DIM}{'─' * w}{C_RESET}")
                continue

            # Unordered list
            m = re.match(r'^(\s*)([-*+])\s+(.+)', line)
            if m:
                indent, _, content = m.groups()
                depth = len(indent) // 2
                bullets = ['●', '○', '▸', '▹']
                bullet = bullets[depth % len(bullets)]
                color = [C_BRIGHT_CYAN, C_CYAN, C_BLUE, C_DIM][depth % 4]
                rendered = cls._render_inline(content)
                result.append(f"  {' ' * (depth * 2)}{color}{bullet}{C_RESET} {rendered}")
                continue

            # Ordered list
            m = re.match(r'^(\s*)(\d+)\.\s+(.+)', line)
            if m:
                indent, num, content = m.groups()
                rendered = cls._render_inline(content)
                result.append(f"  {indent}{C_BRIGHT_CYAN}{num}.{C_RESET} {rendered}")
                continue

            # Checkbox
            m = re.match(r'^(\s*)[-*]\s+\[([ xX])\]\s+(.+)', line)
            if m:
                indent, check, content = m.groups()
                icon = f"{C_BRIGHT_GREEN}✓{C_RESET}" if check.lower() == 'x' else f"{C_DIM}○{C_RESET}"
                rendered = cls._render_inline(content)
                result.append(f"  {indent}{icon} {rendered}")
                continue

            # Blockquote
            if line.startswith('> '):
                rendered = cls._render_inline(line[2:])
                result.append(f"  {C_DIM}▌{C_RESET} {C_ITALIC}{rendered}{C_RESET}")
                continue

            # Table row
            if '|' in line and not line.strip().startswith('```'):
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if all(re.match(r'^[-:]+$', c) for c in cells if c):
                    w = min(_term_width() - 4, 60)
                    result.append(f"  {C_DIM}{'─' * w}{C_RESET}")
                    continue
                row_parts = []
                for cell in cells:
                    rendered = cls._render_inline(cell)
                    row_parts.append(rendered)
                result.append(f"  {f' {C_DIM}│{C_RESET} '.join(row_parts)}")
                continue

            # Normal text
            rendered = cls._render_inline(line)
            result.append(f"  {rendered}" if rendered.strip() else "")

        return '\n'.join(result)

    @classmethod
    def _render_inline(cls, text: str) -> str:
        text = cls._LINK.sub(f'{C_UNDERLINE}{C_BRIGHT_BLUE}\\1{C_RESET}{C_DIM} (\\2){C_RESET}', text)
        text = cls._BOLD.sub(f'{C_BOLD}\\1{C_RESET}', text)
        text = cls._ITALIC.sub(f'{C_ITALIC}\\1{C_RESET}', text)
        text = cls._INLINE_CODE.sub(f'{C_BG_GRAY}{C_BRIGHT_GREEN} \\1 {C_RESET}', text)
        text = cls._STRIKETHROUGH.sub(f'{C_DIM}\\1{C_RESET}', text)
        return text


# ═══════════════════════════════════════════════════════
# Spinner
# ═══════════════════════════════════════════════════════

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    def __init__(self, message: str = "thinking"):
        self._message = message
        self._task: Optional[asyncio.Task] = None
        self._active = False
        self._start_time = 0.0

    def start(self, message: Optional[str] = None):
        if message:
            self._message = message
        self._active = True
        self._start_time = time.time()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.ensure_future(self._spin())

    def stop(self):
        self._active = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        _safe_write(C_CLEAR_LINE)

    def update(self, message: str):
        self._message = message

    async def _spin(self):
        i = 0
        try:
            while self._active:
                frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
                elapsed = time.time() - self._start_time
                timer = f" {C_GRAY}({elapsed:.0f}s){C_RESET}" if elapsed >= 2 else ""
                _safe_write(f"{C_CLEAR_LINE}  {C_BRIGHT_CYAN}{frame}{C_RESET} {C_GRAY}{self._message}{C_RESET}{timer}")
                i += 1
                await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            pass


# ═══════════════════════════════════════════════════════
# Sensitive Data Masking
# ═══════════════════════════════════════════════════════

_SENSITIVE_PATTERNS = [
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'ghp_[A-Za-z0-9]{36,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'gho_[A-Za-z0-9]{36,}'), '[GITHUB_TOKEN]'),
    (re.compile(r'sk-[A-Za-z0-9]{20,}'), '[API_KEY]'),
    (re.compile(r'AIza[A-Za-z0-9_-]{35}'), '[GOOGLE_API_KEY]'),
    (re.compile(r'AKIA[A-Z0-9]{16}'), '[AWS_KEY]'),
    (re.compile(r'TELEGRAM_BOT_TOKEN=\S+'), 'TELEGRAM_BOT_TOKEN=[REDACTED]'),
    (re.compile(r'POSTGRES_PASSWORD=\S+'), 'POSTGRES_PASSWORD=[REDACTED]'),
    (re.compile(r'ANTHROPIC_API_KEY=\S+'), 'ANTHROPIC_API_KEY=[REDACTED]'),
    (re.compile(r'OPENAI_API_KEY=\S+'), 'OPENAI_API_KEY=[REDACTED]'),
    (re.compile(r'GOOGLE_API_KEY=\S+'), 'GOOGLE_API_KEY=[REDACTED]'),
    (re.compile(r'TOKEN=\S+'), 'TOKEN=[REDACTED]'),
    (re.compile(r'password["\s:=]+\S+', re.IGNORECASE), 'password=[REDACTED]'),
]


def _mask_sensitive(text: str) -> str:
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ═══════════════════════════════════════════════════════
# Tool Icons
# ═══════════════════════════════════════════════════════

TOOL_ICONS = {
    "bash": "⚡", "python": "🐍", "read_file": "📖",
    "write_file": "✏️", "edit_file": "📝", "search_code": "🔍",
    "find_files": "📂", "list_files": "📁", "subagent": "🤖",
    "docker": "🐳", "raspi_vision": "👁️", "postgres_query": "🗃️",
    "curl": "🌐", "wget": "⬇️", "gcp_compute": "☁️",
    "gcp_waf": "🛡️", "gcp_waf_deploy": "🚀", "gcp_waf_destroy": "💥",
    "host_control": "🖥️", "router_control": "📡", "infra": "🏗️",
    "coffee": "☕", "drone": "🚁", "iot_control": "🏠",
    "picar": "🚗",
    "security": "🔐", "prompt_guard": "🛡️", "self_heal": "💊",
    "cloudflare": "🌩️", "hostinger": "🌍", "tunnel": "🔗", "tenant": "🏢",
    "document": "📄", "calendar": "📅",
    "user_preferences": "⚙️", "task_orchestrator": "📋",
    "sitrep": "📊",
}


def _format_tool_start(name: str, args: dict, tool_num: int) -> str:
    icon = TOOL_ICONS.get(name, "🔧")
    detail = ""

    if "command" in args:
        cmd = _mask_sensitive(str(args["command"])[:100])
        detail = f" {C_GRAY}{cmd}{C_RESET}"
    elif "path" in args:
        detail = f" {C_GRAY}{args['path']}{C_RESET}"
    elif "pattern" in args and "include" not in args:
        detail = f" {C_GRAY}'{args['pattern']}'{C_RESET}"
    elif "pattern" in args and "include" in args:
        detail = f" {C_GRAY}'{args['pattern']}' in {args['include']}{C_RESET}"
    elif "action" in args:
        extra = ""
        if "params" in args and isinstance(args["params"], dict):
            p = args["params"]
            hints = [f"{k}={v}" for k, v in list(p.items())[:2] if isinstance(v, (str, int, float, bool))]
            if hints:
                extra = f" ({', '.join(hints)})"
        detail = f" {C_GRAY}{args['action']}{extra}{C_RESET}"
    elif "query" in args:
        q = _mask_sensitive(str(args["query"])[:80])
        detail = f" {C_GRAY}{q}{C_RESET}"
    elif "url" in args:
        detail = f" {C_GRAY}{args['url'][:80]}{C_RESET}"
    elif "code" in args:
        lines = str(args["code"]).count('\n') + 1
        detail = f" {C_GRAY}({lines} lines){C_RESET}"

    return f"  {icon} {C_BOLD}{C_BRIGHT_CYAN}{name}{C_RESET}{detail}"


def _format_tool_result(name: str, output: str, success: bool = True) -> str:
    if not output or not output.strip():
        return f"    {C_GREEN}✓{C_RESET} {C_DIM}(ok){C_RESET}"

    out = _mask_sensitive(output.strip())
    lines = out.split('\n')

    # Compact: 3 lines or fewer inline
    if len(lines) <= 3 and len(out) <= 200:
        color = C_GREEN if success else C_BRIGHT_RED
        icon = "✓" if success else "✗"
        preview = out.replace('\n', ' ↵ ')[:150]
        return f"    {color}{icon}{C_RESET} {C_DIM}{preview}{C_RESET}"

    # Larger: show summary
    total = len(lines)
    size = len(out)
    if size > 10000:
        size_str = f"{size/1024:.0f}KB"
    else:
        size_str = f"{size}B"

    color = C_GREEN if success else C_BRIGHT_RED
    icon = "✓" if success else "✗"
    preview_lines = lines[:2]
    preview = '\n'.join(f"    {C_DIM}│ {l[:100]}{C_RESET}" for l in preview_lines)
    more = f"    {C_DIM}  ... +{total - 2} lines ({size_str}){C_RESET}" if total > 2 else ""

    return f"    {color}{icon}{C_RESET} {C_DIM}{total} lines{C_RESET}\n{preview}\n{more}" if more else f"    {color}{icon}{C_RESET} {C_DIM}{total} lines{C_RESET}\n{preview}"



# ═══════════════════════════════════════════════════════
# SSH & Curl helpers for Slash Commands
# ═══════════════════════════════════════════════════════

_RASPI_IP = os.getenv("TOKIOAI_RASPI_IP", "192.168.8.161")
_RASPI_TS = os.getenv("TOKIOAI_RASPI_TS", "100.100.80.12")
_GCP_IP = os.getenv("TOKIOAI_GCP_IP", "35.225.133.230")
_PICAR_IP = os.getenv("TOKIOAI_PICAR_IP", "192.168.8.107")
_PICAR_TS = os.getenv("TOKIOAI_PICAR_TS", "100.76.145.124")
_SSH_RASPI = os.path.expanduser("~/.ssh/id_rsa_raspberry")
_SSH_GCP = os.path.expanduser("~/.ssh/google_compute_engine")


def _quick_ssh(host: str, key: str, user: str, cmd: str, timeout: int = 8) -> str:
    try:
        r = _sp.run(
            ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
             "-o", f"ConnectTimeout={timeout}", "-o", "BatchMode=yes",
             f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=timeout + 5
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _quick_curl(url: str, timeout: int = 5) -> dict:
    try:
        r = _sp.run(["curl", "-s", "--connect-timeout", str(timeout), url],
                     capture_output=True, text=True, timeout=timeout + 3)
        if r.returncode == 0 and r.stdout.strip():
            return _json.loads(r.stdout)
    except Exception:
        pass
    return {}


# ═══════════════════════════════════════════════════════
# Slash Commands (instant, no LLM)
# ═══════════════════════════════════════════════════════

def _slash_status():
    """Quick system overview."""
    _safe_print(f"\n  {C_BOLD}🏠 System Status{C_RESET}\n")

    # Entity
    data = _quick_curl(f"http://{_RASPI_TS}:5000/status")
    if data:
        fps = data.get("fps", 0)
        cam = "✅" if data.get("camera_open") else "❌"
        hailo = "✅" if data.get("hailo_available") else "❌"
        persons = data.get("persons_detected", 0)
        _safe_print(f"  {C_BRIGHT_GREEN}✅ Entity{C_RESET}     FPS:{fps:.0f} Cam:{cam} Hailo:{hailo} Persons:{persons}")
    else:
        _safe_print(f"  {C_BRIGHT_RED}❌ Entity{C_RESET}     offline")

    # GCP
    out = _quick_ssh(_GCP_IP, _SSH_GCP, "osboxes",
        "sudo docker ps --format '{{.Names}}' 2>/dev/null | wc -l")
    if out and out.strip().isdigit():
        count = int(out.strip())
        _safe_print(f"  {C_BRIGHT_GREEN}✅ GCP{C_RESET}        {count} containers running")
    else:
        _safe_print(f"  {C_BRIGHT_RED}❌ GCP{C_RESET}        unreachable")

    # PiCar
    picar_data = _quick_curl(f"http://{_PICAR_IP}:5002/status")
    if not picar_data:
        picar_data = _quick_curl(f"http://{_PICAR_TS}:5002/status")
    if picar_data:
        bat = picar_data.get("battery_voltage", "?")
        _safe_print(f"  {C_BRIGHT_GREEN}✅ PiCar-X{C_RESET}   Battery: {bat}V")
    else:
        _safe_print(f"  {C_DIM}⬚ PiCar-X{C_RESET}   offline")

    # Drone
    drone_data = _quick_curl(f"http://{_RASPI_TS}:5001/drone/status")
    if drone_data:
        connected = drone_data.get("connected", False)
        bat = drone_data.get("battery", "?")
        status = f"{C_BRIGHT_GREEN}connected ⚡{bat}%{C_RESET}" if connected else f"{C_DIM}standby{C_RESET}"
        _safe_print(f"  {C_BRIGHT_GREEN}✅ Drone{C_RESET}      {status}")
    else:
        _safe_print(f"  {C_DIM}⬚ Drone{C_RESET}      proxy offline")

    _safe_print()


def _slash_waf():
    """Quick WAF stats."""
    _safe_print(f"\n  {C_BOLD}🔥 WAF Defense{C_RESET}\n")
    out = _quick_ssh(_GCP_IP, _SSH_GCP, "osboxes",
        'curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" '
        '-d \'{"username":"admin","password":"' + _os.getenv("WAF_DASHBOARD_PASS", "") + '"}\' 2>/dev/null')
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF API unreachable{C_RESET}\n")
        return
    try:
        token = _json.loads(out).get("token", "")
    except Exception:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF auth failed{C_RESET}\n")
        return
    out = _quick_ssh(_GCP_IP, _SSH_GCP, "osboxes",
        f'curl -s http://127.0.0.1:8000/api/summary -H "Authorization: Bearer {token}" 2>/dev/null')
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ WAF summary failed{C_RESET}\n")
        return
    try:
        d = _json.loads(out)
        total = d.get('total', 0)
        blocked = d.get('blocked', 0)
        block_rate = (blocked / total * 100) if total > 0 else 0
        _safe_print(f"  Total attacks:   {C_BOLD}{total:,}{C_RESET}")
        _safe_print(f"  Blocked:         {C_BOLD}{blocked:,}{C_RESET} ({block_rate:.1f}%)")
        _safe_print(f"  Active IP bans:  {C_BOLD}{d.get('active_blocks', 0)}{C_RESET}")
        _safe_print(f"  Unique IPs:      {d.get('unique_ips', 0):,}")
        _safe_print(f"  {C_BRIGHT_RED}Critical{C_RESET}:        {d.get('critical', 0):,}")
        _safe_print(f"  {C_BRIGHT_YELLOW}High{C_RESET}:            {d.get('high', 0):,}")
        _safe_print(f"  Medium:          {d.get('medium', 0):,}")
        _safe_print(f"  Low:             {d.get('low', 0):,}")
    except Exception:
        _safe_print(f"  {C_BRIGHT_RED}❌ Parse error{C_RESET}")
    _safe_print()


def _slash_health():
    """Quick health vitals."""
    _safe_print(f"\n  {C_BOLD}❤️ Health Vitals{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/health/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Health monitor offline{C_RESET}\n")
        return
    hr = data.get("heart_rate", "?")
    spo2 = data.get("spo2", "?")
    bp_sys = data.get("bp_sys", data.get("blood_pressure", {}).get("systolic", 0))
    bp_dia = data.get("bp_dia", data.get("blood_pressure", {}).get("diastolic", 0))
    connected = data.get("connected", False)
    steps = data.get("steps", 0)
    calories = data.get("calories", 0)
    battery = data.get("battery", "?")

    status = f"{C_BRIGHT_GREEN}✅ connected{C_RESET}" if connected else f"{C_BRIGHT_YELLOW}⏳ waiting{C_RESET}"
    _safe_print(f"  Watch:       {status} ({data.get('watch', '?')}) 🔋{battery}%")
    hr_color = C_BRIGHT_RED if isinstance(hr, (int, float)) and (hr > 120 or hr < 45) else C_BOLD
    hr_str = str(hr) if hr else "waiting..."
    _safe_print(f"  Heart Rate:  {hr_color}{hr_str}{C_RESET} bpm")
    spo2_color = C_BRIGHT_RED if isinstance(spo2, (int, float)) and spo2 < 92 else C_BOLD
    spo2_str = str(spo2) if spo2 else "waiting..."
    _safe_print(f"  SpO2:        {spo2_color}{spo2_str}{C_RESET}%")
    if bp_sys and bp_dia:
        bp_color = C_BRIGHT_RED if bp_sys > 140 else C_BOLD
        _safe_print(f"  Blood Press: {bp_color}{bp_sys}/{bp_dia}{C_RESET} mmHg")
    _safe_print(f"  Steps:       {steps:,} | Calories: {calories}")

    # Lab data (iSaw)
    lab = _quick_curl(f"http://{_RASPI_TS}:5000/health/db/latest")
    if lab:
        _safe_print(f"\n  {C_BOLD}🔬 Lab (iSaw){C_RESET}")
        for metric, info in lab.items():
            if isinstance(info, dict):
                val = info.get("value", "?")
                unit = info.get("unit", "")
                ts = info.get("timestamp", "")[:10]
                _safe_print(f"  {metric:14s} {C_BOLD}{val}{C_RESET} {unit} {C_DIM}({ts}){C_RESET}")
    _safe_print()


def _slash_threats():
    """Quick threat level."""
    _safe_print(f"\n  {C_BOLD}⚠️ Threat Level{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/threat/status")
    if not data:
        _safe_print(f"  {C_DIM}Threat engine not responding{C_RESET}\n")
        return
    defcon = data.get("level", data.get("defcon", "?"))
    colors = {"1": C_BRIGHT_RED, "2": C_BRIGHT_RED, "3": C_BRIGHT_YELLOW, "4": C_BRIGHT_BLUE, "5": C_BRIGHT_GREEN}
    c = colors.get(str(defcon), C_DIM)
    level_name = data.get("level_name", "?")
    _safe_print(f"  DEFCON:  {c}{C_BOLD}{defcon}{C_RESET} — {level_name}")
    _safe_print(f"  Score:   {data.get('overall_score', data.get('score', '?'))}")

    corr = data.get("active_correlations", [])
    if corr:
        _safe_print(f"  {C_BRIGHT_RED}⚡ Active Correlations:{C_RESET}")
        for cr in corr[:3]:
            _safe_print(f"    → {cr}")

    vecs = data.get("vectors", data.get("threat_vectors", {}))
    if vecs:
        _safe_print(f"  Vectors:")
        vec_icons = {"waf": "🛡️", "wifi": "📡", "ble": "📱", "vision": "👁️"}
        for v, info in vecs.items():
            icon = vec_icons.get(v, "•")
            name = info.get("name", v)
            score = info.get("score", "?")
            evts = info.get("events_1h", 0)
            detail = info.get("last_detail", "")
            line = f"    {icon} {name}: score {score}"
            if evts:
                line += f" ({evts} events/1h)"
            if detail:
                line += f" — {detail[:50]}"
            _safe_print(line)
    _safe_print()


def _slash_drone():
    """Quick drone status."""
    _safe_print(f"\n  {C_BOLD}🚁 Drone Status{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5001/drone/status")
    if not data:
        _safe_print(f"  {C_DIM}Drone proxy offline — Raspi may be down{C_RESET}\n")
        return
    connected = data.get("connected", False)
    flying = data.get("is_flying", False)
    bat = data.get("battery", "?")
    safety = data.get("safety_level", "?")
    geo = data.get("geofence", {})
    wifi = data.get("wifi_connected", False)

    if flying:
        _safe_print(f"  Status:    {C_BRIGHT_GREEN}✈️ FLYING{C_RESET}")
    elif connected:
        _safe_print(f"  Status:    {C_BRIGHT_GREEN}✅ connected{C_RESET}")
    elif wifi:
        _safe_print(f"  Status:    {C_BRIGHT_YELLOW}📶 WiFi connected, SDK pending{C_RESET}")
    else:
        _safe_print(f"  Status:    {C_DIM}❌ disconnected{C_RESET}")
    _safe_print(f"  Battery:   {bat}%")
    _safe_print(f"  Safety:    {safety}")
    if geo:
        _safe_print(f"  Geofence:  {geo.get('max_height', '?')}cm H × {geo.get('max_distance', '?')}cm D")
    fpv = data.get("fpv", {})
    if fpv:
        _safe_print(f"  FPV:       {'✅ active' if fpv.get('active') else '❌ off'}")
    _safe_print()


def _slash_containers():
    """Quick GCP container list."""
    _safe_print(f"\n  {C_BOLD}🐳 GCP Containers{C_RESET}\n")
    out = _quick_ssh(_GCP_IP, _SSH_GCP, "osboxes",
        "sudo docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}' 2>/dev/null")
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ Cannot reach GCP{C_RESET}\n")
        return
    for line in out.strip().split('\n'):
        parts = line.split('|')
        if len(parts) >= 2:
            name = parts[0]
            status = parts[1]
            icon = "🟢" if "Up" in status else "🔴"
            status_clean = status.replace("(healthy)", f"{C_BRIGHT_GREEN}(healthy){C_RESET}")
            _safe_print(f"  {icon} {C_BRIGHT_CYAN}{name:<28}{C_RESET} {status_clean}")
    _safe_print()


def _slash_entity():
    """Quick entity status."""
    _safe_print(f"\n  {C_BOLD}👁️ Entity Status{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Entity offline{C_RESET}\n")
        return
    fps = data.get("fps", 0)
    cam = data.get("camera_open", False)
    hailo = data.get("hailo_available", False)
    persons = data.get("persons_detected", 0)
    emotion = data.get("emotion", "?")
    uptime = data.get("uptime_seconds", 0)
    uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m" if uptime > 3600 else f"{uptime//60}m"

    _safe_print(f"  FPS:       {C_BOLD}{fps:.1f}{C_RESET}")
    _safe_print(f"  Camera:    {'✅' if cam else '❌'}")
    _safe_print(f"  Hailo AI:  {'✅' if hailo else '❌'}")
    _safe_print(f"  Persons:   {persons}")
    _safe_print(f"  Emotion:   {emotion}")
    _safe_print(f"  Uptime:    {uptime_str}")

    ai = data.get("ai_brain", {})
    if ai:
        analysis = ai.get("last_analysis", "")
        if analysis:
            _safe_print(f"  AI sees:   {C_ITALIC}{analysis[:150]}{C_RESET}")

    active = data.get("active_features", [])
    if active:
        _safe_print(f"  Features:  {', '.join(active[:6])}")
    _safe_print()


def _slash_wifi():
    """Quick WiFi defense status."""
    _safe_print(f"\n  {C_BOLD}📡 WiFi Defense{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/wifi/status")
    if not data:
        _safe_print(f"  {C_DIM}WiFi defense not responding{C_RESET}\n")
        return
    monitoring = data.get("monitoring", data.get("active", False))
    status = f"{C_BRIGHT_GREEN}✅ active{C_RESET}" if monitoring else f"{C_BRIGHT_RED}❌ inactive{C_RESET}"
    _safe_print(f"  Monitor:    {status}")
    counter = data.get("counter_deauth", False)
    _safe_print(f"  Counter:    {'✅ ON' if counter else '❌ OFF'}")
    networks = data.get("networks_seen", data.get("networks", 0))
    _safe_print(f"  Networks:   {networks}")
    deauths = data.get("deauth_detected", data.get("deauth_count", 0))
    if deauths:
        _safe_print(f"  {C_BRIGHT_RED}Deauths:{C_RESET}     {deauths}")
    alerts = data.get("alerts", [])
    if alerts:
        _safe_print(f"  Alerts:")
        for a in alerts[:3]:
            _safe_print(f"    ⚠️ {a[:80]}")
    _safe_print()


def _slash_coffee():
    """Quick coffee machine status."""
    _safe_print(f"\n  {C_BOLD}☕ Coffee Machine{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/coffee/status")
    if not data:
        _safe_print(f"  {C_DIM}Coffee machine not responding{C_RESET}\n")
        return
    status = data.get("status", "unknown")
    icon = "✅" if status == "ready" else ("⏳" if status == "brewing" else "❌")
    _safe_print(f"  Status:    {icon} {status}")
    last = data.get("last_brew", {})
    if last:
        recipe = last.get("recipe", "?")
        when = last.get("timestamp", "?")
        _safe_print(f"  Last brew: {recipe} ({when})")
    _safe_print()


def _slash_ha():
    """Quick Home Assistant status."""
    _safe_print(f"\n  {C_BOLD}🏠 Home Assistant{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/ha/status")
    if not data:
        _safe_print(f"  {C_DIM}HA integration not responding{C_RESET}\n")
        return
    connected = data.get("connected", False)
    entities = data.get("entity_count", data.get("entities", 0))
    status = f"{C_BRIGHT_GREEN}✅ connected{C_RESET}" if connected else f"{C_BRIGHT_RED}❌ disconnected{C_RESET}"
    _safe_print(f"  Status:    {status}")
    _safe_print(f"  Entities:  {entities}")
    uptime = data.get("uptime", "?")
    if uptime != "?":
        _safe_print(f"  Uptime:    {uptime}")
    _safe_print()


def _slash_picar():
    """Quick PiCar-X status."""
    _safe_print(f"\n  {C_BOLD}🚗 PiCar-X Status{C_RESET}\n")
    data = _quick_curl(f"http://{_PICAR_IP}:5002/status")
    if not data:
        data = _quick_curl(f"http://{_PICAR_TS}:5002/status")
    if not data:
        _safe_print(f"  {C_DIM}PiCar-X offline (charging?){C_RESET}\n")
        return
    bat = data.get("battery_voltage", "?")
    hw_ok = data.get("hardware", {})
    obstacle = data.get("ultrasonic_cm", data.get("obstacle_cm", "?"))
    mode = data.get("autonomous_mode", "manual")
    _safe_print(f"  Battery:   {C_BOLD}{bat}V{C_RESET}")
    _safe_print(f"  Obstacle:  {obstacle}cm")
    _safe_print(f"  Mode:      {mode}")
    _safe_print(f"  Hardware:  {'✅ OK' if hw_ok else '⚠️ check'}")
    _safe_print()


def _slash_logs():
    """Quick Entity logs."""
    _safe_print(f"\n  {C_BOLD}📋 Entity Logs (last 15){C_RESET}\n")
    out = _quick_ssh(_RASPI_IP, _SSH_RASPI, "mrmoz",
        "journalctl -u tokio-entity --no-pager -n 15 --output=short-iso 2>/dev/null", timeout=10)
    if not out:
        out = _quick_ssh(_RASPI_TS, _SSH_RASPI, "mrmoz",
            "journalctl -u tokio-entity --no-pager -n 15 --output=short-iso 2>/dev/null", timeout=10)
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ Cannot reach Raspi{C_RESET}\n")
        return
    for line in out.strip().split('\n')[-15:]:
        if 'error' in line.lower() or 'exception' in line.lower():
            _safe_print(f"  {C_BRIGHT_RED}{line[:120]}{C_RESET}")
        elif 'warning' in line.lower():
            _safe_print(f"  {C_BRIGHT_YELLOW}{line[:120]}{C_RESET}")
        else:
            _safe_print(f"  {C_DIM}{line[:120]}{C_RESET}")
    _safe_print()


def _slash_see():
    """Quick snapshot from Entity camera."""
    _safe_print(f"\n  {C_BOLD}📸 Camera Snapshot{C_RESET}\n")
    data = _quick_curl(f"http://{_RASPI_TS}:5000/status")
    if not data:
        _safe_print(f"  {C_BRIGHT_RED}❌ Entity offline{C_RESET}\n")
        return
    persons = data.get('persons_detected', 0)
    emotion = data.get('emotion', '?')
    ai = data.get("ai_brain", {})
    last_analysis = ai.get("last_analysis", "")
    _safe_print(f"  Persons:   {persons}")
    _safe_print(f"  Emotion:   {emotion}")
    if last_analysis:
        if len(last_analysis) > 200:
            last_analysis = last_analysis[:200] + "..."
        _safe_print(f"  AI sees:   {C_ITALIC}{last_analysis}{C_RESET}")
    _safe_print(f"\n  {C_DIM}Use 'que ves?' for full AI analysis{C_RESET}")
    _safe_print()


def _slash_gcp():
    """Quick GCP agent health."""
    _safe_print(f"\n  {C_BOLD}☁️ GCP Agent{C_RESET}\n")
    out = _quick_ssh(_GCP_IP, _SSH_GCP, "osboxes",
        "curl -s http://127.0.0.1:8000/health 2>/dev/null")
    if not out:
        _safe_print(f"  {C_BRIGHT_RED}❌ GCP agent unreachable{C_RESET}\n")
        return
    try:
        d = _json.loads(out)
        _safe_print(f"  Status:    {C_BRIGHT_GREEN}✅ {d.get('status', 'healthy')}{C_RESET}")
        _safe_print(f"  Version:   {d.get('version', '?')}")
        _safe_print(f"  Tools:     {d.get('tools_count', '?')}")
        _safe_print(f"  Uptime:    {d.get('uptime', '?')}")
    except Exception:
        _safe_print(f"  {C_BRIGHT_RED}❌ Parse error{C_RESET}")
    _safe_print()


def _slash_sitrep():
    """Full SITREP — calls all slash commands."""
    _safe_print(f"\n  {C_BOLD}{C_BRIGHT_WHITE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}")
    _safe_print(f"  {C_BOLD}{C_BRIGHT_WHITE}  SITREP — Full Situation Report{C_RESET}")
    _safe_print(f"  {C_BOLD}{C_BRIGHT_WHITE}  {time.strftime('%Y-%m-%d %H:%M:%S')}{C_RESET}")
    _safe_print(f"  {C_BOLD}{C_BRIGHT_WHITE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}")
    _slash_status()
    _slash_threats()
    _slash_waf()
    _slash_health()
    _slash_wifi()


_SLASH_COMMANDS = {
    "/status": _slash_status,
    "/waf": _slash_waf,
    "/health": _slash_health,
    "/threats": _slash_threats,
    "/drone": _slash_drone,
    "/containers": _slash_containers,
    "/entity": _slash_entity,
    "/sitrep": _slash_sitrep,
    "/wifi": _slash_wifi,
    "/coffee": _slash_coffee,
    "/ha": _slash_ha,
    "/logs": _slash_logs,
    "/see": _slash_see,
    "/picar": _slash_picar,
    "/gcp": _slash_gcp,
}



# ═══════════════════════════════════════════════════════
# Agent Factory
# ═══════════════════════════════════════════════════════

def create_agent():
    from tokio_agent.engine.agent import TokioAgent
    from tokio_agent.engine.memory.workspace import Workspace
    from tokio_agent.engine.llm import create_llm
    workspace = Workspace()
    llm = create_llm()
    agent = TokioAgent(llm=llm, workspace=workspace)
    return agent


# ═══════════════════════════════════════════════════════
# Status Bar
# ═══════════════════════════════════════════════════════

_cost_tracker = CostTracker()


def format_status(agent, elapsed: float, tool_count: int = 0) -> str:
    stats = agent.get_stats()
    parts = []

    if elapsed >= 60:
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        parts.append(f"⏱ {mins}m{secs}s")
    else:
        parts.append(f"⏱ {elapsed:.1f}s")

    total_tokens = stats.get("total_tokens", 0)
    input_tokens = stats.get("input_tokens", 0)
    output_tokens = stats.get("output_tokens", 0)
    if total_tokens > 1_000_000:
        parts.append(f"📊 {total_tokens/1_000_000:.1f}M tokens")
    elif total_tokens > 1000:
        parts.append(f"📊 {total_tokens/1000:.0f}K tokens")

    tools_used = tool_count or stats.get("tools_executed", 0)
    if tools_used > 0:
        parts.append(f"🔧 {tools_used} tools")

    compactions = stats.get("compactions", 0)
    if compactions > 0:
        parts.append(f"📦 {compactions} compactions")

    mem = stats.get("auto_memory", {})
    if mem.get("total_memories_saved", 0) > 0:
        parts.append(f"🧠 {mem['total_memories_saved']} memories")

    # Cost: use session cumulative
    model = stats.get("llm", "")
    if input_tokens > 0 or output_tokens > 0:
        this_cost = _cost_tracker.estimate_single(model, input_tokens, output_tokens)
        parts.append(f"💰 ~{this_cost} (session: {_cost_tracker.format_cost()})")

    return " │ ".join(parts)


# ═══════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════

def show_help(agent):
    w = min(_term_width() - 4, 60)
    _safe_print(f"""
{C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}
{C_BOLD} TokioAI CLI v4.0 — Help{C_RESET}
{C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}

{C_BOLD}Commands:{C_RESET}
  {C_BRIGHT_CYAN}exit{C_RESET}, {C_BRIGHT_CYAN}quit{C_RESET}       Exit CLI
  {C_BRIGHT_CYAN}reset{C_RESET}             New session
  {C_BRIGHT_CYAN}stats{C_RESET}             Show statistics
  {C_BRIGHT_CYAN}tools{C_RESET}             List available tools
  {C_BRIGHT_CYAN}model{C_RESET}             Show current LLM
  {C_BRIGHT_CYAN}clear{C_RESET}             Clear screen
  {C_BRIGHT_CYAN}unlimited{C_RESET}         Toggle unlimited mode
  {C_BRIGHT_CYAN}persistent{C_RESET}        Toggle persistent mode
  {C_BRIGHT_CYAN}config{C_RESET}            Show configuration

{C_BOLD}Quick Commands (instant, no LLM):{C_RESET}
  {C_BRIGHT_GREEN}/status{C_RESET}           System overview
  {C_BRIGHT_GREEN}/sitrep{C_RESET}           Full situation report
  {C_BRIGHT_GREEN}/waf{C_RESET}              WAF attack stats
  {C_BRIGHT_GREEN}/health{C_RESET}           Health vitals + Lab data
  {C_BRIGHT_GREEN}/threats{C_RESET}          DEFCON threat level
  {C_BRIGHT_GREEN}/drone{C_RESET}            Drone status
  {C_BRIGHT_GREEN}/entity{C_RESET}           Entity vision status
  {C_BRIGHT_GREEN}/containers{C_RESET}       GCP Docker containers
  {C_BRIGHT_GREEN}/see{C_RESET}              Camera snapshot + AI analysis
  {C_BRIGHT_GREEN}/wifi{C_RESET}             WiFi defense status
  {C_BRIGHT_GREEN}/coffee{C_RESET}           Coffee machine status
  {C_BRIGHT_GREEN}/ha{C_RESET}               Home Assistant status
  {C_BRIGHT_GREEN}/picar{C_RESET}            PiCar-X robot status
  {C_BRIGHT_GREEN}/gcp{C_RESET}              GCP agent health
  {C_BRIGHT_GREEN}/logs{C_RESET}             Entity logs (last 15)

{C_BOLD}Tips:{C_RESET}
  {C_GRAY}• End line with \\ for multi-line input{C_RESET}
  {C_GRAY}• Press Esc to cancel a running request{C_RESET}
  {C_GRAY}• Press Tab to autocomplete commands{C_RESET}

{C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}
""")


# ═══════════════════════════════════════════════════════
# Banner
# ═══════════════════════════════════════════════════════

def show_banner(mode_parts: list, agent=None):
    g = [196, 202, 208, 214, 220, 226]

    banner_lines = [
        "████████╗ ██████╗ ██╗  ██╗██╗ ██████╗ ",
        "╚══██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗",
        "   ██║   ██║   ██║█████╔╝ ██║██║   ██║",
        "   ██║   ██║   ██║██╔═██╗ ██║██║   ██║",
        "   ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝",
        "   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝",
    ]

    _safe_print()
    for i, line in enumerate(banner_lines):
        color = c256(g[i % len(g)])
        _safe_print(f"    {color}{line}{C_RESET}")

    model_name = "Claude"
    tools_count = 0
    if agent:
        try:
            stats = agent.get_stats()
            model_name = stats.get("llm", model_name)
            tools_count = stats.get("tools_count", 0)
        except Exception:
            pass

    _safe_print(f"    {C_BOLD}{C_BRIGHT_WHITE}  Autonomous AI Agent{C_RESET} {C_GRAY}v4.0{C_RESET}")
    _safe_print(f"    {C_GRAY}  {model_name} • {tools_count} tools • {' • '.join(mode_parts)}{C_RESET}")
    _safe_print()
    _safe_print(f"    {C_GRAY}  Type {C_BRIGHT_CYAN}help{C_GRAY} for commands • {C_BRIGHT_YELLOW}Esc{C_GRAY} to cancel • {C_BRIGHT_YELLOW}Tab{C_GRAY} to complete{C_RESET}")
    _safe_print()


# ═══════════════════════════════════════════════════════
# Stream Processing — The core loop
# Uses TerminalManager for safe cbreak enter/exit
# ═══════════════════════════════════════════════════════

async def process_streaming(agent, user_input: str, session_id: str):
    """Process a message with streaming output and rich formatting."""
    cancel_event = asyncio.Event()
    spinner = Spinner("thinking...")
    t0 = time.time()

    streaming_text = False
    ever_streamed = False
    collected_text = []
    tool_count = 0
    current_round = 1
    term = TerminalManager()

    term.enter_cbreak()

    async def _check_cancel():
        while not cancel_event.is_set():
            if term.is_active and _check_escape():
                cancel_event.set()
                spinner.stop()
                _safe_write(f"\n  {C_BRIGHT_YELLOW}⛔ Cancelling...{C_RESET}\n")
                break
            await asyncio.sleep(0.1)

    cancel_task = asyncio.create_task(_check_cancel())

    stream_gen = None
    try:
        spinner.start("thinking...")

        stream_gen = agent.process_message_stream(
            user_message=user_input,
            session_id=session_id,
            cancel_event=cancel_event,
        )

        async for event_type, data in stream_gen:
            if event_type == "thinking":
                current_round = data
                if data > 1:
                    spinner.update(f"round {data}...")
                else:
                    spinner.start("thinking...")

            elif event_type == "token":
                if not streaming_text:
                    spinner.stop()
                    streaming_text = True
                    ever_streamed = True
                    _safe_write("\n")
                _safe_write(data)
                collected_text.append(data)

            elif event_type == "preparing":
                if streaming_text:
                    _safe_write("\n")
                    streaming_text = False
                    collected_text = []
                spinner.start("preparing...")

            elif event_type == "tool_start":
                name, args = data
                spinner.stop()
                if streaming_text:
                    _safe_write("\n")
                    streaming_text = False
                    collected_text = []
                tool_count += 1
                _safe_print(_format_tool_start(name, args, tool_count))
                spinner.start(f"running {name}...")

            elif event_type == "tool_end":
                name, output = data
                spinner.stop()
                is_error = False
                if output and output.strip():
                    lower_out = output.strip().lower()[:100]
                    is_error = any(e in lower_out for e in ['error', 'traceback', 'exception', 'failed', 'permission denied'])
                _safe_print(_format_tool_result(name, output, not is_error))
                # Drain stdin after each tool to prevent key leakage
                _drain_stdin()
                spinner.start("thinking...")

            elif event_type == "text":
                spinner.stop()
                if not streaming_text and not ever_streamed:
                    rendered = MarkdownRenderer.render(data)
                    _safe_print(f"\n{rendered}")

            elif event_type == "done":
                spinner.stop()
                if not streaming_text and not ever_streamed and data:
                    rendered = MarkdownRenderer.render(data)
                    _safe_print(f"\n{rendered}")
                elif streaming_text:
                    _safe_write("\n")

            elif event_type == "error":
                spinner.stop()
                _safe_print(f"\n  {C_BRIGHT_RED}✗ Error: {data}{C_RESET}")

        elapsed = time.time() - t0

        # Update cost tracker
        stats = agent.get_stats()
        model = stats.get("llm", "")
        input_t = stats.get("input_tokens", 0)
        output_t = stats.get("output_tokens", 0)
        _cost_tracker.add_usage(model, input_t, output_t)

        status = format_status(agent, elapsed, tool_count)
        _safe_print(f"\n  {C_GRAY}{status}{C_RESET}")

    except KeyboardInterrupt:
        spinner.stop()
        cancel_event.set()
        _safe_print(f"\n  {C_BRIGHT_YELLOW}⛔ Cancelled{C_RESET}")

    except Exception as e:
        spinner.stop()
        _safe_print(f"\n  {C_BRIGHT_RED}✗ {e}{C_RESET}")

    finally:
        # CRITICAL: Restore terminal FIRST, before anything else
        # Inspired by Claude Code: cleanupTerminalModes() runs before all other cleanup
        term.exit_cbreak()

        if stream_gen:
            try:
                await stream_gen.aclose()
            except Exception:
                pass

        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

        # Final drain to catch any stragglers
        _flush_stdin()
        _drain_stdin()


# ═══════════════════════════════════════════════════════
# Config Command
# ═══════════════════════════════════════════════════════

def _show_config():
    w = min(_term_width() - 4, 55)
    _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
    _safe_print(f"  {C_BOLD}⚙️  Configuration{C_RESET}")
    _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")

    _safe_print(f"\n  {C_BOLD}Hosts:{C_RESET}")
    _safe_print(f"  {C_GRAY}Raspi LAN:{C_RESET}      {_RASPI_IP}")
    _safe_print(f"  {C_GRAY}Raspi TS:{C_RESET}       {_RASPI_TS}")
    _safe_print(f"  {C_GRAY}GCP:{C_RESET}            {_GCP_IP}")
    _safe_print(f"  {C_GRAY}PiCar LAN:{C_RESET}     {_PICAR_IP}")
    _safe_print(f"  {C_GRAY}PiCar TS:{C_RESET}      {_PICAR_TS}")

    _safe_print(f"\n  {C_BOLD}SSH Keys:{C_RESET}")
    raspi_key = '✅' if os.path.exists(_SSH_RASPI) else '❌'
    gcp_key = '✅' if os.path.exists(_SSH_GCP) else '❌'
    _safe_print(f"  {C_GRAY}Raspi:{C_RESET}          {raspi_key} {_SSH_RASPI}")
    _safe_print(f"  {C_GRAY}GCP:{C_RESET}            {gcp_key} {_SSH_GCP}")

    env_file = os.path.expanduser("~/.tokioai/.env")
    _safe_print(f"\n  {C_BOLD}Environment:{C_RESET}")
    _safe_print(f"  {C_GRAY}.env file:{C_RESET}      {'✅' if os.path.exists(env_file) else '❌'} {env_file}")
    _safe_print(f"  {C_GRAY}Model:{C_RESET}          {os.getenv('TOKIOAI_MODEL', 'sonnet')}")

    _safe_print(f"\n  {C_BOLD}Session:{C_RESET}")
    _safe_print(f"  {C_GRAY}History:{C_RESET}        {HISTORY_FILE}")
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                count = sum(1 for _ in f)
            _safe_print(f"  {C_GRAY}History size:{C_RESET}   {count} entries")
        except Exception:
            pass

    # Session cost
    _safe_print(f"\n  {C_BOLD}Costs:{C_RESET}")
    _safe_print(f"  {C_GRAY}Session:{C_RESET}        {_cost_tracker.format_cost()}")
    _safe_print(f"  {C_GRAY}Tokens:{C_RESET}         {_cost_tracker.session_input_tokens:,} in / {_cost_tracker.session_output_tokens:,} out")

    _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}\n")


# ═══════════════════════════════════════════════════════
# Multi-line Input
# ═══════════════════════════════════════════════════════

def _read_multiline(first_line: str) -> str:
    if not first_line.endswith('\\'):
        return first_line
    lines = [first_line[:-1]]
    while True:
        try:
            continuation = input(f"  {C_DIM}...{C_RESET} ")
            if continuation.endswith('\\'):
                lines.append(continuation[:-1])
            else:
                lines.append(continuation)
                break
        except (EOFError, KeyboardInterrupt):
            break
    return '\n'.join(lines)



# ═══════════════════════════════════════════════════════
# Main Loop — The heart of the CLI
# ═══════════════════════════════════════════════════════

async def run_interactive(session_id: Optional[str] = None, max_rounds: int = 0,
                          max_time: int = 0, persistent: bool = False):
    """Run the interactive CLI loop."""
    global _terminal_saved_state

    mode_parts = ["Streaming", "Native Tools", "Auto-compact"]
    if max_rounds == 0:
        mode_parts.append("Unlimited")
    if persistent:
        mode_parts.append("Persistent")

    _load_history()
    agent = create_agent()

    # Populate tool names for tab completion
    global _TOOL_NAMES
    try:
        _TOOL_NAMES = sorted(agent.registry.list_names())
    except Exception:
        pass

    show_banner(mode_parts, agent)

    # Save clean terminal state ONCE at startup
    # This is our "golden" state we always restore to
    if not _IS_WINDOWS and sys.stdin.isatty():
        try:
            _terminal_saved_state = termios.tcgetattr(sys.stdin)
        except Exception:
            pass

    # Session resumption
    sid = session_id
    resumed = False
    if not sid:
        prev = _load_session_state()
        if prev and prev.get("messages"):
            prev_sid = prev["session_id"]
            prev_ts = prev.get("timestamp", "?")
            prev_msgs = prev["messages"]
            _safe_print(f"  {C_BRIGHT_YELLOW}📋 Previous session found ({prev_ts}):{C_RESET}")
            for msg in prev_msgs[-4:]:
                role = msg.get("role", "?")
                content = msg.get("content", "")[:100]
                icon = f"{C_BRIGHT_CYAN}▸{C_RESET}" if role == "user" else f"{C_BRIGHT_GREEN}◂{C_RESET}"
                _safe_print(f"    {icon} {C_GRAY}{content}{'…' if len(msg.get('content', '')) > 100 else ''}{C_RESET}")
            _safe_print(f"  {C_GRAY}Enter = resume │ 'new' = fresh session{C_RESET}")
            try:
                choice = input(f"  ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = ""
            if choice not in ("new", "nueva", "n"):
                sid = prev_sid
                resumed = True
                for msg in prev_msgs:
                    agent.session_manager.add_message(sid, msg["role"], msg["content"])
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Session restored{C_RESET}\n")
                # Restore cost state
                _cost_tracker.restore(sid)
            else:
                _safe_print(f"  {C_GRAY}New session.{C_RESET}\n")
        if not sid:
            sid = f"cli-{int(time.time())}"

    # Persistent mode = unlimited rounds (don't cut mid-task)
    if persistent:
        max_rounds = 0
        max_time = 0
    agent.MAX_TOOL_ROUNDS = max_rounds
    agent.MAX_TOTAL_TIME = max_time
    _persistent_mode = persistent

    if max_rounds == 0:
        _safe_print(f"  {C_BRIGHT_YELLOW}∞ Unlimited mode: no round or time limits{C_RESET}")
    if _persistent_mode:
        _safe_print(f"  {C_BRIGHT_YELLOW}🔄 Persistent mode: will keep working until you type 'stop'{C_RESET}")

    while True:
        # ── Restore terminal to clean state before every prompt ──
        # This is the KEY fix for keyboard hang:
        # After streaming, cbreak mode might still be partially active.
        # We force restore to the golden state saved at startup.
        if _terminal_saved_state:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _terminal_saved_state)
            except Exception:
                pass
        if not _IS_WINDOWS and sys.stdin.isatty():
            try:
                os.system("stty sane 2>/dev/null")
            except Exception:
                pass
        _flush_stdin()
        _drain_stdin()

        try:
            if _IS_WINDOWS:
                prompt = f"\n{C_BOLD}{C_BRIGHT_CYAN}❯{C_RESET} "
            else:
                prompt = f"\n\001{C_BOLD}{C_BRIGHT_CYAN}\002❯\001{C_RESET}\002 "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            _safe_print(f"\n{C_GRAY}Bye! 👋{C_RESET}")
            break

        if not user_input:
            continue

        user_input = _read_multiline(user_input)

        _save_history()

        # Built-in commands
        lower = user_input.lower()
        if lower in ("exit", "quit", "q"):
            _safe_print(f"{C_GRAY}Bye! 👋{C_RESET}")
            break
        if lower == "help":
            show_help(agent)
            continue
        if lower == "reset":
            sid = f"cli-{int(time.time())}"
            _safe_print(f"  {C_BRIGHT_GREEN}✓ Session reset: {sid}{C_RESET}")
            continue
        if lower == "unlimited":
            _safe_print(f"  {C_BRIGHT_YELLOW}∞ Already unlimited by default — no round or time limits{C_RESET}")
            continue
        if lower == "persistent":
            _persistent_mode = not _persistent_mode
            if _persistent_mode:
                agent.MAX_TOOL_ROUNDS = 0
                agent.MAX_TOTAL_TIME = 0
                _safe_print(f"  {C_BRIGHT_YELLOW}🔄 Persistent ON — will keep working until 'stop'{C_RESET}")
            else:
                _safe_print(f"  {C_BRIGHT_GREEN}✓ Persistent OFF — still unlimited rounds{C_RESET}")
            continue
        if lower == "stop" and _persistent_mode:
            _persistent_mode = False
            _safe_print(f"  {C_BRIGHT_GREEN}✓ Stopped persistent mode. Rounds still unlimited.{C_RESET}")
            continue
        if lower == "config":
            _show_config()
            continue
        if lower == "stats":
            stats = agent.get_stats()
            mode = "UNLIMITED" if agent.MAX_TOOL_ROUNDS == 0 else f"{agent.MAX_TOOL_ROUNDS} rounds"
            w = min(_term_width() - 4, 50)
            _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            _safe_print(f"  {C_BOLD}📊 Statistics{C_RESET}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            _safe_print(f"  {C_BRIGHT_CYAN}🧠{C_RESET} LLM:          {stats.get('llm', '?')}")
            _safe_print(f"  {C_BRIGHT_CYAN}⚙️{C_RESET}  Mode:         {mode}{' + PERSISTENT' if _persistent_mode else ''}")
            _safe_print(f"  {C_BRIGHT_CYAN}🔧{C_RESET} Tools:         {stats.get('tools_count', 0)} available")
            _safe_print(f"  {C_BRIGHT_CYAN}💬{C_RESET} Messages:      {stats.get('messages_processed', 0)}")
            _safe_print(f"  {C_BRIGHT_CYAN}⚡{C_RESET} Tools used:    {stats.get('tools_executed', 0)}")
            total_tokens = stats.get('total_tokens', 0)
            input_tokens = stats.get('input_tokens', 0)
            output_tokens = stats.get('output_tokens', 0)
            _safe_print(f"  {C_BRIGHT_CYAN}📊{C_RESET} Tokens:        {total_tokens:,} (in:{input_tokens:,} out:{output_tokens:,})")
            _safe_print(f"  {C_BRIGHT_CYAN}📦{C_RESET} Compactions:   {stats.get('compactions', 0)}")
            _safe_print(f"  {C_BRIGHT_CYAN}🧠{C_RESET} Memories:      {stats.get('memories_extracted', 0)}")
            _safe_print(f"  {C_BRIGHT_CYAN}💰{C_RESET} Session cost:  ~{_cost_tracker.format_cost()}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            continue
        if lower == "tools":
            names = sorted(agent.registry.list_names())
            w = min(_term_width() - 4, 60)
            _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            _safe_print(f"  {C_BOLD}🔧 {len(names)} Tools Available{C_RESET}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            for n in names:
                t = agent.registry.get(n)
                icon = TOOL_ICONS.get(n, "🔧")
                desc = t.description[:55] if t else ""
                _safe_print(f"  {icon} {C_BRIGHT_CYAN}{n:<22}{C_RESET} {C_GRAY}{desc}{C_RESET}")
            _safe_print(f"  {C_BOLD}{C_BRIGHT_CYAN}{'─' * w}{C_RESET}")
            continue
        if lower == "model":
            stats = agent.get_stats()
            _safe_print(f"\n  {C_BRIGHT_CYAN}🧠{C_RESET} Current model: {C_BOLD}{stats.get('llm', '?')}{C_RESET}")
            continue
        if lower == "clear":
            os.system("cls" if _IS_WINDOWS else "clear")
            continue

        # Slash commands (instant, no LLM)
        if lower in _SLASH_COMMANDS:
            try:
                _SLASH_COMMANDS[lower]()
            except Exception as e:
                _safe_print(f"  {C_BRIGHT_RED}✗ {e}{C_RESET}")
            continue

        # Process with streaming
        await process_streaming(agent, user_input, sid)

        # Save session state + costs
        session = agent.session_manager.get_session(sid)
        if session:
            _save_session_state(sid, session.get("messages", []))
        _cost_tracker.save(sid)

        # Persistent mode
        if _persistent_mode:
            while _persistent_mode:
                # Restore terminal before persistent prompt too
                if _terminal_saved_state:
                    try:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _terminal_saved_state)
                    except Exception:
                        pass
                _flush_stdin()
                _drain_stdin()
                try:
                    if _IS_WINDOWS:
                        follow_prompt = f"\n  {C_GRAY}[persistent]{C_RESET} {C_BOLD}{C_BRIGHT_CYAN}❯{C_RESET} "
                    else:
                        follow_prompt = f"\n  \001{C_GRAY}\002[persistent]\001{C_RESET}\002 \001{C_BOLD}{C_BRIGHT_CYAN}\002❯\001{C_RESET}\002 "
                    follow_up = input(follow_prompt).strip()
                except (EOFError, KeyboardInterrupt):
                    _persistent_mode = False
                    _safe_print(f"\n  {C_BRIGHT_GREEN}✓ Persistent mode stopped.{C_RESET}")
                    break
                if not follow_up:
                    follow_up = "Continua con la tarea. Si terminaste, dime que esta listo."
                if follow_up.lower() in ("stop", "parar", "detener", "exit"):
                    _persistent_mode = False
                    _safe_print(f"  {C_BRIGHT_GREEN}✓ Persistent stopped.{C_RESET}")
                    break
                _save_history()
                await process_streaming(agent, follow_up, sid)
                _cost_tracker.save(sid)

    # Final cleanup
    _save_history()
    _cost_tracker.save(sid)
    _restore_terminal_sync()


async def run_single(query: str, session_id: Optional[str] = None):
    """Run a single command with streaming and exit."""
    agent = create_agent()
    sid = session_id or "cli-oneshot"
    _safe_print(f"\n  {C_BOLD}{C_BRIGHT_CYAN}❯{C_RESET} {query}\n")
    await process_streaming(agent, query, sid)


def main():
    """Entry point for the CLI."""
    if _IS_WINDOWS:
        os.system("")
    import argparse

    parser = argparse.ArgumentParser(
        description="TokioAI CLI v4.0 — Autonomous AI Agent",
    )
    parser.add_argument("query", nargs="*", help="Direct query (non-interactive)")
    parser.add_argument("-s", "--session", help="Session ID to resume")
    parser.add_argument("-r", "--max-rounds", type=int, default=0)
    parser.add_argument("-t", "--max-time", type=int, default=0)
    parser.add_argument("-u", "--unlimited", action="store_true")
    parser.add_argument("-p", "--persistent", action="store_true")

    args = parser.parse_args()

    if args.unlimited:
        args.max_rounds = 0
        args.max_time = 0

    try:
        if args.query:
            query = " ".join(args.query)
            asyncio.run(run_single(query, args.session))
        else:
            asyncio.run(run_interactive(
                session_id=args.session,
                max_rounds=args.max_rounds,
                max_time=args.max_time,
                persistent=args.persistent,
            ))
    except KeyboardInterrupt:
        _safe_print(f"\n{C_GRAY}Bye! 👋{C_RESET}")
    finally:
        _restore_terminal_sync()


if __name__ == "__main__":
    main()

