# PhD Notion Dashboard

A small always-on-top Windows dashboard for your Notion PhD workspace. It shows:

- **Upcoming** meetings and events for the next 7 days;
- your open **TODOs**, sorted by priority and due date;
- a **working-hours** bar (today / this week / this month) built from your workday entries, with **Clock in / Clock out**.

From the dashboard you can also:

- **dictate a TODO by voice** from anywhere with a hotkey (speech is recognised locally, nothing leaves your PC);
- mark a TODO as done by clicking it (with an **Undo** button);
- add meetings and TODOs, including notes that become the TODO page's content;
- view and edit a TODO's notes;
- click **Today**, **This week** or **This month** to list the workdays behind each total.

Closing the window hides it to the **system tray**, so it keeps running in the background.

---

## 1. Requirements

- Windows 10 or 11
- Python 3.11 or newer ([python.org/downloads](https://www.python.org/downloads/))
- A Notion account where you can create an integration

## 2. Create a Notion integration

1. Open [notion.so/profile/integrations](https://www.notion.so/profile/integrations) and create an **internal** integration.
2. Under **Capabilities**, enable **Read content**, **Update content** and **Insert content**.
   The dashboard writes to Notion (it marks TODOs done, creates pages and edits notes), so read-only access is not enough.
3. Copy the integration token. The app asks for it on first start (step 4).
4. In Notion, open the page the dashboard should live in (or your existing PhD page) and choose **••• → Connections → (your integration)**.
   If you already have Calendar and TODO databases elsewhere, connect those too.

## 3. Install

Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

This creates a virtual environment in `.venv`, installs the dependencies from `requirements.txt` and generates the app icon in `assets/`.

To do it by hand instead:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app_icon.py
```

### Optional: voice notes

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe voice_check.py
```

`voice_check.py` records 8 seconds from your default microphone and prints what the speech model understood. The first run downloads the speech model (about 150 MB for `base`); after that it works offline. An NVIDIA GPU is used automatically if available, but isn't needed.

### Optional: tidy up voice notes with a local LLM

Dictated notes can be cleaned up by a small language model running on your PC through [Ollama](https://ollama.com). Install Ollama, then download the model:

```powershell
ollama pull qwen3:8b
```

That's all. The dashboard talks to Ollama on `http://127.0.0.1:11434`. If Ollama isn't running, notes are saved untouched, as before.

## 4. Configure

Just start the app (`.\.venv\Scripts\python.exe main.py`). On first start a setup window opens:

1. **Connect to Notion**: paste your integration token. It is checked against Notion and saved to `.env`.
2. **Choose a workspace**, either
   - **Create a new PhD dashboard**: pick one of the pages shared with the integration. The app creates a *PhD Dashboard* page inside it with a ready-made **Calendar** and **TODOs** database (all the properties below, including the `Workday` tag and the `WorkHours` formula), or
   - **Use existing databases**: pick your Calendar and TODO databases from the dropdowns. Property names are detected (the names from the table below are preferred).

It then writes `config.yaml` and the dashboard opens. If a page or database is missing from the dropdowns, share it with the integration (**••• → Connections**) and click **Reload**.

To run the setup window again later (new token, other databases), quit the dashboard from the tray and start it with:

```powershell
.\.venv\Scripts\python.exe main.py --setup
```

Your app, hotkey and voice settings are kept.

### Command-line setup

`setup.py` is the older, terminal-based alternative. It asks for your integration token (saved to `.env`), lists every database the integration can see along with its properties, and asks which ones are your Calendar and TODO databases. It then writes `config.yaml`.

`setup.py` guesses property names from their types. **Check `config.yaml` afterwards** against the property names it printed. In particular:

- `date_property` is the first date property it finds, so make sure it is your *start* date.
- `location_property` is the first text property it finds, which may not be your location.
- The link, tags and workday settings are **not** written by `setup.py`. Add them by hand (see below).

Property names are case-sensitive and must match Notion exactly.

### What the databases need

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

The `app` and `hotkeys` settings can also be changed in the app itself, from the gear icon in the title bar.

## 5. Run

```powershell
.\.venv\Scripts\python.exe main.py
```

To start without opening your Notion page in the browser:

```powershell
.\.venv\Scripts\python.exe main.py --no-open
```

- **Close (X) or Alt+F4** hides the dashboard to the system tray; it keeps running.
- **Click the tray icon** to show or hide the dashboard.
- **Right-click the tray icon** for *Show dashboard*, *Refresh* and *Quit*. *Quit* is the only way to exit completely.
- With **Start minimized** on (Settings), the app starts straight in the tray.

The dashboard refreshes every `refresh_minutes`. Use the refresh icon in the title bar to refresh immediately.

### Clock in / out

**Clock in** creates a workday page in the calendar database (tagged with `workday_tag`, start = now). **Clock out** sets its end time (`end_property`, or the end of the start date's range if you don't use a separate end property). Your hours formula then calculates the hours as usual.

Each clock in / out is confirmed with a Windows notification, e.g. *Clocked in: Started at 09:12* or *Clocked out: Worked 7h 45m (09:12–16:57)*. If you had several sessions that day, the day's total is added. The notification appears even while the dashboard is open, because the hotkey works from any app. If you don't see it, check Windows Settings → System → Notifications (including Do not disturb / Focus).

While you're clocked in, the bar shows how long you've been working, and the Today / This week / This month totals include the running time. The state lives in Notion (a workday with a start but no end), so it survives restarts, and a workday you start directly in Notion shows up as clocked in too.

The clock buttons only appear when `tags_property` and `workday_tag` are configured.

### Voice notes

1. Press `Ctrl+Alt+N` anywhere. A small overlay appears at the bottom of the screen with a red recording dot. It doesn't take focus, so the window you were in stays active.
2. Speak. Your words appear live: white text is settled, grey text may still change.
3. Pause for about 2 seconds, or press `Ctrl+Alt+N` again, to finish. **Esc** cancels.
4. The note is saved as a TODO (priority Low). With [cleanup](#tidying-up-notes) on, it gets a heading and a tidied-up body. Without it, a short note becomes the title; for a longer one the first sentence is the title and the full text goes into the page.

The speech model runs in a separate background process that starts a few seconds after the dashboard, so the dashboard itself opens as fast as before. If you press the hotkey before the model has loaded, recording starts anyway and is transcribed as soon as it's ready.

The microphone is only open while you record. Speech recognition and the optional note cleanup run entirely on your PC.

Settings → **Voice notes**: turn it on/off, language (auto-detect, English, German), model size (`tiny`, `base`, `small`) and CPU vs. GPU. Mixing languages within one sentence is handled less reliably than sticking to one.

#### Tidying up notes

When you think out loud, you repeat yourself, correct yourself and use a lot of filler words. With **Tidy up notes** on (Settings → Voice notes) and [Ollama](#optional-tidy-up-voice-notes-with-a-local-llm) installed, a local language model rewrites each note before it's saved:

- the **title** becomes a short heading, e.g. "Email Anna about lab slot and calibration data";
- the **page** gets the cleaned-up note. Repeated points are merged, and when you correct yourself ("Wednesday, no, Tuesday") only the correction is kept. Separate points become bullets;
- below it, under *Original dictation:*, the raw transcript is kept in case the model got something wrong. Set `keep_transcript: false` to leave it out.

The note stays in the language you spoke. While it's being tidied up the overlay shows "Tidying up…", which usually takes 1–2 seconds on a GPU. The model starts loading as soon as you begin recording. If Ollama isn't running, is too slow (over 60 s) or the model is missing, the note is saved untouched and the overlay tells you why.

Any Ollama chat model works, and you can change it under **Cleanup model**. `qwen3:8b` (about 5 GB) handled self-corrections most reliably in testing. `qwen3:4b` (2.5 GB) is faster and needs less memory, but sometimes keeps the wrong version when you correct yourself.

### Hotkeys

These work system-wide, even while the dashboard is hidden in the tray:

| Hotkey | Action |
| --- | --- |
| `Ctrl+Alt+N` | **Dictate a TODO** by voice (see below); opens the typed New TODO dialog if voice notes are off or not installed |
| `Ctrl+Alt+D` | Show / hide the dashboard |
| `Ctrl+Alt+W` | Clock in / out (a Windows notification confirms it) |

Change them in **Settings → Hotkeys**: click a field and press the new combination, or clear it to turn that hotkey off. A hotkey needs Ctrl, Alt or Win plus a letter, digit or F-key.

A hotkey is taken away from every other app while the dashboard runs. If another program already owns a combination, the dashboard shows "Hotkey not set" and you can pick a different one.

The defaults were chosen because on German and most European keyboards `Ctrl+Alt` is the same as `AltGr`, and `AltGr+N` / `AltGr+D` / `AltGr+W` don't type a character, so they don't steal symbols like `@` (`AltGr+Q`) or `€` (`AltGr+E`).

## 6. Start automatically with Windows

```powershell
.\install-startup.ps1
```

This adds a shortcut to your Windows Startup folder, so the dashboard launches (without a console window) every time you sign in.

To remove it:

```powershell
.\uninstall-startup.ps1
```

`run-hidden.vbs` starts the dashboard without a console window as well, if you prefer to launch it by double-clicking.

## 7. Troubleshooting

**`object_not_found`**: the integration has no access to that page or database. Add it under **••• → Connections**, then run `setup.py` again.

**Nothing happens when completing or adding items / "insufficient permissions"**: the integration is missing the *Update content* or *Insert content* capability (step 2).

**A property shows up empty, or new meetings lose their location**: the property name in `config.yaml` doesn't exist in the database. Run `setup.py` to print the real names and fix `config.yaml`.

**No meetings appear**: meetings are shown for the next 7 days only. Also check that `date_property` points at the calendar's start date.

**Completed TODOs still show**: add your exact "done" status names to `completed_statuses`.

**Hotkeys don't do anything after an update**: an older copy of the dashboard may still be running and owns the hotkeys. Quit it from the tray icon (right-click → Quit) and start it again. Starting the dashboard while it's already running just brings the running one to the front.

**Voice notes: nothing is recognised / "Microphone unavailable"**: run `voice_check.py`. If the recording is silent, turn on Windows Settings → Privacy & security → Microphone → *Let desktop apps access your microphone*, and check that the right microphone is the Windows default input.

**Workday hours look wrong**: check `hours_property`. If the formula returns 0, the hours are calculated from `date_property` and `end_property` instead.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Entry point: loads config, connects to Notion, starts the app and tray icon |
| `overlay.py` | The dashboard window |
| `add_dialog.py` | New meeting / new TODO / notes dialogs, calendar and clock pickers |
| `settings_dialog.py` | In-app settings |
| `title_bar.py` | Custom dark title bar and frameless window/dialog base classes |
| `tray.py` | System tray icon |
| `hotkeys.py` | System-wide hotkeys (Win32 `RegisterHotKey`) |
| `voice_notes.py` | Voice notes: starts the voice process, recording overlay, saves the TODO |
| `voice_worker.py` | Background process: microphone + speech recognition (faster-whisper) |
| `note_cleanup.py` | Tidies up dictated notes and gives them a heading with a local LLM (Ollama) |
| `voice_check.py` | Microphone and speech-model check |
| `app_icon.py` | Draws the app icon; run it to regenerate `assets/icon.ico` |
| `notion_api.py` | All Notion API calls |
| `setup_wizard.py` | First-start setup window (token, create or choose databases) |
| `notion_setup.py` | Notion side of the setup: lists, creates and inspects databases |
| `setup.py` | Command-line setup (alternative to the setup window) |

## Security

Your Notion token is stored only in `.env`, which is listed in `.gitignore`. Never commit it.

The integration can read and change whatever pages and databases you connect it to. The dashboard itself only writes when you act: completing or undoing a TODO, adding a meeting or TODO, or saving notes.
