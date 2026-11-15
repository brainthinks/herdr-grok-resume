#!/usr/bin/env python3
"""Remember the Grok session in a Herdr pane, and start it again after a reboot.

herdr-core restores a dead pane as a shell and does not relaunch the agent.
This records the session on the pane while Grok is running, then prints one
shell command when that pane comes back as a new shell.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

LABEL_SESSION = "grok.session"
LABEL_CWD = "grok.cwd"
LABEL_BOOT = "grok.boot"
LABEL_SHELL = "grok.shell"
SHELLS = {"bash", "zsh", "sh", "fish", "dash"}
ACTIVE = Path.home() / ".grok" / "active_sessions.json"


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def pid_alive(pid: int) -> bool:
    return pid > 0 and Path(f"/proc/{pid}").exists()


def pid_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def session_already_open(session_id: str) -> bool:
    try:
        rows = json.loads(ACTIVE.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or row.get("session_id") != session_id:
            continue
        try:
            pid = int(row.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid_alive(pid) and pid_comm(pid) == "grok":
            return True
    return False


def hc_get(terminal: str) -> dict:
    raw = subprocess.check_output(["hc", "get", terminal, "--json"], text=True)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("hc get returned unexpected JSON")
    return data


def hc_label(terminal: str, pairs: list[str]) -> None:
    subprocess.run(
        ["hc", "label", terminal, *pairs],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def clear_labels(terminal: str) -> None:
    hc_label(
        terminal,
        [f"{LABEL_SESSION}=", f"{LABEL_CWD}=", f"{LABEL_BOOT}=", f"{LABEL_SHELL}="],
    )


def read_event() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def event_session(event: dict) -> str:
    for key in ("sessionId", "session_id"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return os.environ.get("GROK_SESSION_ID", "").strip()


def event_cwd(event: dict) -> str:
    value = event.get("cwd")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return os.getcwd()


def is_subagent(event: dict) -> bool:
    for key in ("subagentType", "subagent_type"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def safe_session(session_id: str) -> bool:
    return bool(session_id) and all(ch.isalnum() or ch in "-_" for ch in session_id)


def decide(
    labels: dict,
    *,
    terminal_pid: int,
    boot: str,
    foreground: str,
    cwd_exists: bool,
    session_open: bool,
) -> str | None:
    """Return the session id to resume, or None to leave the shell alone."""
    session_id = str(labels.get(LABEL_SESSION) or "")
    cwd = str(labels.get(LABEL_CWD) or "")
    saved_boot = str(labels.get(LABEL_BOOT) or "")
    saved_shell = str(labels.get(LABEL_SHELL) or "")
    if not safe_session(session_id) or not cwd or not saved_boot or not saved_shell:
        return None
    if foreground == "grok" or (foreground and foreground not in SHELLS):
        return None
    if session_open or not cwd_exists:
        return None
    same_shell = saved_shell == str(terminal_pid) and saved_boot == boot
    if same_shell:
        return None
    return session_id


def resume_command(session_id: str, cwd: str) -> str:
    return f"cd {shlex.quote(cwd)} && grok --resume {shlex.quote(session_id)}"


def cmd_note(event: dict) -> int:
    terminal = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not terminal or is_subagent(event):
        return 0
    session_id = event_session(event)
    cwd = event_cwd(event)
    if not safe_session(session_id) or not cwd or "\n" in cwd or "\x00" in cwd:
        return 0
    try:
        info = hc_get(terminal)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError):
        return 0
    shell = str(info.get("pid") or "")
    boot = boot_id()
    if not shell or not boot:
        return 0
    labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
    if (
        labels.get(LABEL_SESSION) == session_id
        and labels.get(LABEL_CWD) == cwd
        and labels.get(LABEL_BOOT) == boot
        and labels.get(LABEL_SHELL) == shell
    ):
        return 0
    try:
        hc_label(
            terminal,
            [
                f"{LABEL_SESSION}={session_id}",
                f"{LABEL_CWD}={cwd}",
                f"{LABEL_BOOT}={boot}",
                f"{LABEL_SHELL}={shell}",
            ],
        )
    except (OSError, subprocess.CalledProcessError):
        return 0
    return 0


def cmd_end(event: dict) -> int:
    terminal = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not terminal or is_subagent(event):
        return 0
    try:
        info = hc_get(terminal)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError):
        return 0
    labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
    try:
        shell = int(labels.get(LABEL_SHELL) or 0)
    except (TypeError, ValueError):
        shell = 0
    # The pane's shell is still there, so this was a quit, not a reboot.
    if shell and pid_alive(shell) and str(info.get("pid") or "") == str(shell):
        try:
            clear_labels(terminal)
        except (OSError, subprocess.CalledProcessError):
            return 0
    return 0


def cmd_here() -> int:
    terminal = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not terminal:
        return 0
    try:
        info = hc_get(terminal)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError):
        return 0
    labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
    foreground = info.get("foreground") if isinstance(info.get("foreground"), dict) else {}
    name = str(foreground.get("name") or "")
    cwd = str(labels.get(LABEL_CWD) or "")
    session_id = str(labels.get(LABEL_SESSION) or "")
    try:
        terminal_pid = int(info.get("pid") or 0)
    except (TypeError, ValueError):
        terminal_pid = 0
    chosen = decide(
        labels,
        terminal_pid=terminal_pid,
        boot=boot_id(),
        foreground=name,
        cwd_exists=bool(cwd) and Path(cwd).is_dir(),
        session_open=session_already_open(session_id),
    )
    if not chosen:
        return 0
    boot = boot_id()
    try:
        hc_label(
            terminal,
            [
                f"{LABEL_SESSION}={chosen}",
                f"{LABEL_CWD}={cwd}",
                f"{LABEL_BOOT}={boot}",
                f"{LABEL_SHELL}={terminal_pid}",
            ],
        )
    except (OSError, subprocess.CalledProcessError):
        return 0
    print(f"herdr: resuming grok {chosen}", file=sys.stderr)
    print(resume_command(chosen, cwd))
    return 0


def selftest() -> int:
    labels = {
        LABEL_SESSION: "01900000-0000-7000-8000-000000000001",
        LABEL_CWD: "/tmp/project",
        LABEL_BOOT: "old-boot",
        LABEL_SHELL: "6371",
    }
    assert (
        decide(
            labels,
            terminal_pid=7000,
            boot="new-boot",
            foreground="bash",
            cwd_exists=True,
            session_open=False,
        )
        == labels[LABEL_SESSION]
    )
    assert (
        decide(
            labels,
            terminal_pid=6371,
            boot="old-boot",
            foreground="bash",
            cwd_exists=True,
            session_open=False,
        )
        is None
    )
    assert (
        decide(
            labels,
            terminal_pid=7000,
            boot="new-boot",
            foreground="grok",
            cwd_exists=True,
            session_open=False,
        )
        is None
    )
    assert (
        decide(
            labels,
            terminal_pid=7000,
            boot="new-boot",
            foreground="vim",
            cwd_exists=True,
            session_open=False,
        )
        is None
    )
    assert (
        decide(
            labels,
            terminal_pid=7000,
            boot="new-boot",
            foreground="bash",
            cwd_exists=False,
            session_open=False,
        )
        is None
    )
    assert (
        decide(
            labels,
            terminal_pid=7000,
            boot="new-boot",
            foreground="bash",
            cwd_exists=True,
            session_open=True,
        )
        is None
    )
    assert (
        decide(
            labels,
            terminal_pid=8000,
            boot="old-boot",
            foreground="bash",
            cwd_exists=True,
            session_open=False,
        )
        == labels[LABEL_SESSION]
    )
    command = resume_command("abc", "/tmp/a b")
    assert command == "cd '/tmp/a b' && grok --resume abc"
    print("ok")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "note":
        return cmd_note(read_event())
    if cmd == "end":
        return cmd_end(read_event())
    if cmd == "here":
        return cmd_here()
    if cmd == "selftest":
        return selftest()
    if cmd == "pin":
        session_id = ""
        cwd = ""
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--session" and i + 1 < len(args):
                session_id = args[i + 1]
                i += 2
            elif args[i] == "--cwd" and i + 1 < len(args):
                cwd = args[i + 1]
                i += 2
            else:
                print(f"unknown pin argument: {args[i]}", file=sys.stderr)
                return 2
        return cmd_note({"sessionId": session_id, "cwd": cwd})
    print("usage: resume.py note|end|here|pin|selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
