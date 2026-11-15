# herdr-grok-resume

The Herdr desktop app restores a pane as a shell after a reboot. It does not resume the agent. This records the Grok session on that pane and starts `grok --resume` when the pane comes back.

It only does this for Grok, and only for panes on the machine where it is installed. Herdr TUI sessions are a different server.

## Install

Linux, bash, Python 3.10+, Herdr desktop (`hc` on `PATH`), and Grok.

```
./install.sh
```

That copies `resume.py` to `~/.config/herdr-app/grok-resume/`, writes `~/.grok/hooks/herdr-resume.json`, and appends a marked block to `~/.bashrc`.

Start Grok inside a Herdr pane after installing. A session that is already running is not marked until the next start. Grok skips your hooks until the folder is trusted. Home counts as trusted. A new project asks once.

```
./install.sh --uninstall
```

## What a reboot does

While Grok is running in a Herdr pane, the hook stores the session id and folder on that pane. Quitting Grok clears the mark, so a quit stays quit. If the machine reboots, or herdr-core stops, the pane's new shell runs `grok --resume` in the saved folder. The shell turns job control on first, so Grok is the foreground program and Herdr keeps it in the agents list.

## Limits

- Linux only. The script reads `/proc/sys/kernel/random/boot_id`, and Herdr's Linux shells source `~/.bashrc`.
- Subagent sessions are ignored.
- A session that is already open in another live Grok process is not started again.
