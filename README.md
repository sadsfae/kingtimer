# Kingtimer

Timer for the King Gragnar camp on EverQuest Project 1999.

Watches your EQ log file for a King Gragnar/Gragnarr slain line (any wording:
"You have slain..." or "...has been slain..."), counts down exactly 48 minutes
until the respawn, then plays a looping chime and pops a dialog until you click
OK. After OK it keeps watching for the next kill.

## Run

```bash
python3 kingtimer.py
```

## How it works

- Start: remembers the current end of the log, so only lines appended after
  Start are tracked.
- Gear: pick another character's log file (`eqlog_<char>_<server>.txt`). The
  choice is saved in `~/.config/gragnar_timer.json`.
- Stop: cancels the timer and the alert.
- `--alert-seconds N` shortens the countdown for testing (default 2880).
- `--log PATH` overrides the log file.

## Desktop entry

`kingtimer.desktop` drops into `~/.local/share/applications/`, or run
`python3 kingtimer.py` from a terminal.
