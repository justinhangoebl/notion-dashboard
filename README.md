# PhD Notion Dashboard

A small always-on-top desktop dashboard for your Notion PhD workspace, for **Windows** and **Linux**. It shows:

- **Upcoming** meetings and events for the next 7 days;
- your open **TODOs**, sorted by priority and due date;
- a **working-hours** bar (today / this week / this month) built from your workday entries, with **Clock in / Clock out**.

From the dashboard you can also:

- **dictate or type a TODO** from anywhere with a hotkey (speech is recognised locally, nothing leaves your PC);
- mark a TODO as done by clicking it (with an **Undo** button);
- add meetings and TODOs, including notes that become the TODO page's content;
- view and edit a TODO's notes;
- click **Today**, **This week** or **This month** to list the workdays behind each total.

Closing the window hides it to the **system tray**, so it keeps running in the background.

---

## 1. Requirements

- Windows 10/11, or Linux with an X11 or Wayland desktop (GNOME, KDE, …)
- Python 3.11 or newer
- A Notion account where you can create an integration

## 2. Create a Notion integration

1. Open [notion.so/profile/integrations](https://www.notion.so/profile/integrations) and create an **internal** integration.
2. Under **Capabilities**, enable **Read content**, **Update content** and **Insert content**.
   The dashboard writes to Notion (it marks TODOs done, creates pages and edits notes), so read-only access is not enough.
3. Copy the integration token. The app asks for it on first start (step 4).
4. In Notion, open the page the dashboard should live in (or your existing PhD page) and choose **••• → Connections → (your integration)**.
   If you already have Calendar and TODO databases elsewhere, connect those too.

## 3. Install

Both installers create a virtual environment in `.venv` inside this folder and install the app into it (`pip install -e .`, so changes to the source take effect on the next start). Add the voice option to also install [voice notes](#voice-notes).

### Windows

Install Python from [python.org](https://www.python.org/downloads/), then in PowerShell in this folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows\install.ps1            # or: .\scripts\windows\install.ps1 -Voice
```

### Linux

```bash
scripts/linux/install.sh                 # or: scripts/linux/install.sh --voice
```

This also adds **PhD Notion Dashboard** to your application menu. Right-clicking it there offers *New TODO* and *Clock in / out*.

Qt and voice notes need a few system libraries that most desktops already have. The installer tells you if any are missing, for example on Debian/Ubuntu:

```bash
sudo apt install python3-venv libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1   # dashboard
sudo apt install libportaudio2                                                                  # voice notes
```

### By hand

```bash
python -m venv .venv
.venv/bin/pip install -e ".[voice]"      # Windows: .venv\Scripts\pip install -e ".[voice]"
```

`pip install .` (or `pipx install .`) installs it like any other Python app, without the project folder.

### Optional: check voice notes

```bash
.venv/bin/python -m notion_dashboard.voice.check         # Windows: .venv\Scripts\python -m notion_dashboard.voice.check
```

This records 8 seconds from your default microphone and prints what the speech model understood. The first run downloads the speech model (about 150 MB for `base`); after that it works offline. An NVIDIA GPU is used automatically if available, but isn't needed.

### Optional: tidy up voice notes with a local LLM

Dictated notes can be cleaned up by a small language model running on your PC through [Ollama](https://ollama.com). Install Ollama, then download the model:

```bash
ollama pull qwen3:8b
```

That's all. The dashboard talks to Ollama on `http://127.0.0.1:11434`. If Ollama isn't running, notes are saved untouched.

## 4. First start

Start the app:

| | |
| --- | --- |
| Windows | `.\.venv\Scripts\notion-dashboard.exe` |
| Linux | `.venv/bin/notion-dashboard`, or from the application menu |

`python -m notion_dashboard` works too. On first start a setup window opens:

1. **Connect to Notion**: paste your integration token. It is checked against Notion and saved in your [config folder](#where-your-settings-live).
2. **Choose a workspace**, either
   - **Create a new PhD dashboard**: pick one of the pages shared with the integration. The app creates a *PhD Dashboard* page inside it with a ready-made **Calendar** and **TODOs** database (all the properties below, including the `Workday` tag and the `WorkHours` formula), or
   - **Use existing databases**: pick your Calendar and TODO databases from the dropdowns. Property names are detected (the names from the table below are preferred). Check `config.yaml` afterwards.

It then writes `config.yaml` and the dashboard opens. If a page or database is missing from the dropdowns, share it with the integration (**••• → Connections**) and click **Reload**.

To run the setup window again later (new token, other databases), quit the dashboard from the tray and start it with `--setup`. Your app, hotkey and voice settings are kept.

### Where your settings live

Your token (`.env`) and `config.yaml` are kept outside the project folder, so they survive reinstalls and never end up in git:

| | |
| --- | --- |
| Windows | `%APPDATA%\NotionDashboard` |
| Linux | `~/.config/notion-dashboard` |

Set `NOTION_DASHBOARD_HOME` to use a different folder.

### What the databases need

Only relevant if you use your own databases. Property names are case-sensitive and must match Notion exactly.

**Calendar database**

| Setting | Property type | Used for |
| --- | --- | --- |
| `title_property` | Title | Event name |
| `date_property` | Date | Start (a date range here also works) |
| `end_property` | Date (optional) | End, if you store it separately |
| `location_property` | Text (optional) | Location of new meetings |
| `link_property` | URL or text (optional) | Meeting link; double-clicking an event opens it |
| `tags_property` | Multi-select (optional) | Marks workday entries |
| `hours_property` | Formula returning a number (optional) | Hours for a workday |

When both `tags_property` and `workday_tag` are set, pages carrying that tag (e.g. `Workday`) are counted as workdays instead of being listed under Upcoming. Their hours come from `hours_property`. If that is missing or 0, the hours are calculated from the start and end dates.

**TODO database**

| Setting | Property type | Used for |
| --- | --- | --- |
| `title_property` | Title | Task name |
| `due_property` | Date | Due date |
| `status_property` | Status or select | Open vs. done |
| `priority_property` | Select (optional) | `High`, `Medium` or `Low` |

TODOs whose status is listed in `completed_statuses` are hidden. Clicking a TODO sets its status to the **first** entry in that list.

### Example `config.yaml`

```yaml
notion:
  phd_page_url: "https://www.notion.so/..."   # opened in the browser on start (optional)
  calendar_data_source_id: "..."
  todo_data_source_id: "..."

calendar:
  title_property: Name
  date_property: StartDate
  end_property: EndDate
  location_property: Location
  description_property: Description
  link_property: Link
  tags_property: Tags
  workday_tag: Workday
  hours_property: WorkHours

todo:
  title_property: Name
  due_property: Due
  status_property: Status
  priority_property: Priority
  completed_statuses:
    - Done

app:
  refresh_minutes: 5
  max_todos: 12
  max_meetings: 10
  open_notion_on_start: true
  start_minimized: false
  window_width: 520
  window_height: 760

hotkeys:              # optional; these are the defaults. "" turns one off.
  new_todo: Ctrl+Alt+N
  toggle_dashboard: Ctrl+Alt+D
  toggle_clock: Ctrl+Alt+W

voice:                # optional; these are the defaults
  enabled: true
  model: base         # tiny | base | small
  device: auto        # auto (GPU if available) | cpu
  language: auto      # auto | en | de
  silence_seconds: 2.0
  cleanup: true       # tidy notes up with Ollama (see "Tidying up notes")
  cleanup_model: qwen3:8b
  ollama_url: http://127.0.0.1:11434
  keep_transcript: true   # also keep the raw dictation at the end of the page
```

The `app`, `hotkeys` and `voice` settings can also be changed in the app itself, from the gear icon in the title bar.

## 5. Using it

| Option | |
| --- | --- |
| `--no-open` | Don't open your Notion page in the browser on start |
| `--setup` | Show the setup window again |
| `--action NAME` | Tell the running dashboard to `show`, `new_todo`, `toggle_dashboard` or `toggle_clock` (starts it first if needed) |

- **Close (X) or Alt+F4** hides the dashboard to the system tray; it keeps running.
- **Click the tray icon** to show or hide the dashboard.
- **Right-click the tray icon** for *Show dashboard*, *Refresh* and *Quit*. *Quit* is the only way to exit completely.
- With **Start minimized** on (Settings), the app starts straight in the tray.
- Starting the app while it's already running brings the running one to the front.

The dashboard refreshes every `refresh_minutes`. Use the refresh icon in the title bar to refresh immediately.

### Clock in / out

**Clock in** creates a workday page in the calendar database (tagged with `workday_tag`, start = now). **Clock out** sets its end time (`end_property`, or the end of the start date's range if you don't use a separate end property). Your hours formula then calculates the hours as usual.

Each clock in / out is confirmed with a desktop notification, e.g. *Clocked in: Started at 09:12* or *Clocked out: Worked 7h 45m (09:12–16:57)*. If you had several sessions that day, the day's total is added. If you don't see it, check your notification settings (including Do not disturb / Focus).

While you're clocked in, the bar shows how long you've been working, and the Today / This week / This month totals include the running time. The state lives in Notion (a workday with a start but no end), so it survives restarts, and a workday you start directly in Notion shows up as clocked in too.

The clock buttons only appear when `tags_property` and `workday_tag` are configured.

### Voice notes

1. Press `Ctrl+Alt+N` anywhere. A small overlay appears at the bottom of the screen with a red recording dot and a text field.
2. Speak. Your words appear live: white text is settled, grey text may still change.
3. Pause for about 2 seconds, or press `Ctrl+Alt+N` again, to finish. **Esc** cancels.
   **Rather type?** Just start typing instead of speaking. The recording stops, the overlay becomes a text field, and **Enter** (or `Ctrl+Alt+N`) saves it; **Esc** cancels. The overlay has keyboard focus while it's open and gives it back to the window you were in when you finish.
4. The note is saved as a TODO (priority Low). With [cleanup](#tidying-up-notes) on, it gets a heading and a tidied-up body. Without it, a short note becomes the title; for a longer one the first sentence is the title and the full text goes into the page.

The speech model runs in a separate background process that starts a few seconds after the dashboard, so the dashboard itself opens quickly. If you press the hotkey before the model has loaded, recording starts anyway and is transcribed as soon as it's ready.

The microphone is only open while you record. Speech recognition and the optional note cleanup run entirely on your PC.

Settings → **Voice notes**: turn it on/off, language (auto-detect, English, German), model size (`tiny`, `base`, `small`) and CPU vs. GPU. Mixing languages within one sentence is handled less reliably than sticking to one. Without the voice packages, `Ctrl+Alt+N` opens the typed New TODO dialog instead.

#### Tidying up notes

When you think out loud, you repeat yourself, correct yourself and use a lot of filler words. With **Tidy up notes** on (Settings → Voice notes) and [Ollama](#optional-tidy-up-voice-notes-with-a-local-llm) installed, a local language model rewrites each dictated note before it's saved:

- the **title** becomes a short heading, e.g. "Email Anna about lab slot and calibration data";
- the **page** gets the cleaned-up note. Repeated points are merged, and when you correct yourself ("Wednesday, no, Tuesday") only the correction is kept. Separate points become bullets;
- below it, under *Original dictation:*, the raw transcript is kept in case the model got something wrong. Set `keep_transcript: false` to leave it out.

The note stays in the language you spoke. While it's being tidied up the overlay shows "Tidying up…", which usually takes 1–2 seconds on a GPU. If Ollama isn't running, is too slow (over 60 s) or the model is missing, the note is saved untouched and the overlay tells you why.

Any Ollama chat model works, and you can change it under **Cleanup model**. `qwen3:8b` (about 5 GB) handled self-corrections most reliably in testing. `qwen3:4b` (2.5 GB) is faster and needs less memory, but sometimes keeps the wrong version when you correct yourself.

### Hotkeys

These work system-wide, even while the dashboard is hidden in the tray:

| Hotkey | Action |
| --- | --- |
| `Ctrl+Alt+N` | **New TODO**: dictate or type it (see [Voice notes](#voice-notes)) |
| `Ctrl+Alt+D` | Show / hide the dashboard |
| `Ctrl+Alt+W` | Clock in / out (a notification confirms it) |

Change them in **Settings → Hotkeys**: click a field and press the new combination, or clear it to turn that hotkey off. A hotkey needs Ctrl, Alt or Win/Super plus a letter, digit or F-key.

A hotkey is taken away from every other app while the dashboard runs. If another program already owns a combination, the dashboard shows "Hotkey not set" and you can pick a different one.

The defaults were chosen because on German and most European keyboards `Ctrl+Alt` is the same as `AltGr`, and `AltGr+N` / `AltGr+D` / `AltGr+W` don't type a character, so they don't steal symbols like `@` (`AltGr+Q`) or `€` (`AltGr+E`).

#### Hotkeys on Linux

- **X11 session**: hotkeys work like on Windows.
- **Wayland session** (default on recent GNOME and KDE): Wayland doesn't let apps grab keys globally. Add the shortcuts in your desktop's keyboard settings instead (GNOME: *Settings → Keyboard → Custom Shortcuts*; KDE: *System Settings → Shortcuts → Add Command*), with commands like:

  ```bash
  /path/to/phd-notion-dashboard/.venv/bin/notion-dashboard --action new_todo
  /path/to/phd-notion-dashboard/.venv/bin/notion-dashboard --action toggle_dashboard
  /path/to/phd-notion-dashboard/.venv/bin/notion-dashboard --action toggle_clock
  ```

  Then clear the hotkeys in the app's Settings so they don't clash.

On Wayland the dashboard runs through XWayland when it can, because only that way can it stay on top and place the voice overlay at the bottom of the screen. Set `QT_QPA_PLATFORM=wayland` to run it as a native Wayland app instead. On GNOME the tray icon needs the *AppIndicator and KStatusNotifierItem Support* extension; without a tray, closing the window quits the app.

## 6. Start automatically

**Windows**: adds a shortcut to your Startup folder, so the dashboard starts (without a console window) when you sign in.

```powershell
.\scripts\windows\install-startup.ps1
.\scripts\windows\uninstall-startup.ps1   # to remove it
```

`scripts\windows\run-hidden.vbs` starts the dashboard without a console window as well, if you prefer to launch it by double-clicking.

**Linux**: adds an XDG autostart entry.

```bash
scripts/linux/install-autostart.sh
scripts/linux/uninstall-autostart.sh     # to remove it
```

## 7. Troubleshooting

**`object_not_found`**: the integration has no access to that page or database. Add it under **••• → Connections**, then start with `--setup`.

**Nothing happens when completing or adding items / "insufficient permissions"**: the integration is missing the *Update content* or *Insert content* capability (step 2).

**A property shows up empty, or new meetings lose their location**: the property name in `config.yaml` doesn't exist in the database. Fix it in `config.yaml` (see [What the databases need](#what-the-databases-need)).

**No meetings appear**: meetings are shown for the next 7 days only. Also check that `date_property` points at the calendar's start date.

**Completed TODOs still show**: add your exact "done" status names to `completed_statuses`.

**Hotkeys don't do anything after an update**: an older copy of the dashboard may still be running and owns the hotkeys. Quit it from the tray icon (right-click → Quit) and start it again.

**Linux: `Could not load the Qt platform plugin "xcb"`**: a system library is missing. Install the packages from [Linux](#linux), or start with `QT_QPA_PLATFORM=wayland`.

**Voice notes: nothing is recognised / "Microphone unavailable"**: run the [voice check](#optional-check-voice-notes). On Windows, if the recording is silent, turn on Settings → Privacy & security → Microphone → *Let desktop apps access your microphone*. Check that the right microphone is the default input. On Linux, make sure `libportaudio2` is installed.

**Workday hours look wrong**: check `hours_property`. If the formula returns 0, the hours are calculated from `date_property` and `end_property` instead.

## Project layout

```
pyproject.toml              package metadata and dependencies (pip install -e ".[voice]")
scripts/
  windows/                  install.ps1, (un)install-startup.ps1, run-hidden.vbs
  linux/                    install.sh, (un)install-autostart.sh, .desktop template
src/notion_dashboard/
  app.py                    entry point: config, first-start setup, wires everything together
  paths.py                  config folder and bundled assets
  notion/
    api.py                  all Notion API calls used by the dashboard
    setup.py                setup logic: list, create and inspect databases
  ui/
    dashboard.py            the dashboard window
    dialogs.py              new meeting / new TODO / notes dialogs, calendar and clock pickers
    settings_dialog.py      in-app settings
    setup_wizard.py         first-start setup window
    title_bar.py            dark title bar, frameless window/dialog base classes
    tray.py                 system tray icon
    icons.py                icon glyphs (Segoe MDL2 on Windows, bundled Material Icons elsewhere)
    app_icon.py             draws the app icon; python -m notion_dashboard.ui.app_icon regenerates assets/
  hotkeys/
    __init__.py             shared hotkey logic, picks the platform backend
    windows.py              Win32 RegisterHotKey
    x11.py                  X11 XGrabKey
  voice/
    notes.py                voice notes: worker process, recording overlay, saving the TODO
    worker.py               background process: microphone + speech recognition (faster-whisper)
    cleanup.py              tidies up dictated notes with a local LLM (Ollama)
    check.py                microphone and speech-model check
  assets/                   app icon, check mark, Material Icons font (Apache 2.0)
```

## Security

Your Notion token is stored only in your [config folder](#where-your-settings-live), never in the project folder. `.env` and `config.yaml` are also listed in `.gitignore`.

The integration can read and change whatever pages and databases you connect it to. The dashboard itself only writes when you act: completing or undoing a TODO, adding a meeting or TODO, or saving notes.
