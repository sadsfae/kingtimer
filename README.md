# Kingtimer

Timer for the King Gragnar camp on EverQuest Project 1999.

Watches your EQ log file for a King Gragnar/Gragnarr slain line (any wording:
"You have slain..." or "...has been slain..."), counts down exactly 48 minutes
until the respawn, and sounds the looping chime 20 seconds before he is due.
The dialog loops the sound until you click OK; after OK it keeps watching for
the next kill.

## Requirements

- Python 3 with tkinter (ships with most distro Pythons; Arch:
  `sudo pacman -S python tk`)
- One playback tool for the alert sound: `mpv` (preferred, loops the sound
  seamlessly), or `paplay`/`aplay`/`play` (restarted in a loop)
- Optional: `notify-send` or the Omarchy shell, so the alarm also pops a
  desktop notification (visible even over a fullscreen game)
- Nothing else: everything is Python standard library, no pip packages

The alert sound is `alert.wav`, included in the repo next to `kingtimer.py`.
If it is missing, a chime is generated on the fly.

## Run

```bash
python3 kingtimer.py
```

## Default log file

Kingtimer watches Aptom's log by default:

```
/home/wfoster/.wine/drive_c/Program Files/Everquest_P99/Logs/eqlog_Aptom_project1999.txt
```

In a shell, quote the path or escape the space (`Program\ Files`). Pick any
other character's log with the gear button or `--log PATH`.

## How it works

- Start: remembers the current end of the log, so only lines appended after
  Start are tracked.
- Gear: pick another character's log file (`eqlog_<char>_<server>.txt`). The
  choice is saved in `~/.config/gragnar_timer.json`.
- Moon: toggle dark mode.
- Stop: cancels the timer and the alert.
- The alarm fires 20 seconds before the 48 minute respawn.
- Killing Gragnarr again while the alarm plays stops the alarm, closes the
  dialog, and restarts the 48 minute timer from the new kill.
- `--alert-seconds N` shortens the countdown for testing (default 2880).
- `--log PATH` overrides the log file.

## Desktop entry

Build the `.desktop` file inside the checkout, so the paths point where you
cloned the repo:

```bash
cat > kingtimer.desktop <<EOF
[Desktop Entry]
Version=1.0
Name=Kingtimer
Comment=Alert 48 minutes after King Gragnar is slain
Exec=$(which python3) $(pwd)/kingtimer.py
Path=$(pwd)/
Icon=alarm-symbolic
Terminal=false
Type=Application
Categories=Game;
EOF
```

Then install it (directory and permissions):

```bash
mkdir -p ~/.local/share/applications/
mv kingtimer.desktop ~/.local/share/applications/
chmod +x ~/.local/share/applications/kingtimer.desktop
update-desktop-database ~/.local/share/applications/
```
