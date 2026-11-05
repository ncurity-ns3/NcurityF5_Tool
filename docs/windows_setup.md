# windows setup guide

## project root

```cmd
cd /d "C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First"
```

## symptom

- `pip` is not recognized
- `python` prints only `Python` (microsoft store stub)

## fix

1. install python 3.12+ from https://www.python.org/downloads/windows/ (add to path + pip)
2. disable app execution aliases for `python.exe` and `python3.exe`
3. open a **new** terminal

## setup (use cmd wrappers)

```cmd
cd /d "C:\Users\ejes3\Ejes_OneDrive\OneDrive - Ncurity\바탕 화면\WorksFiles\F5 Project\Config & Rules & Apps\AI First"
scripts\setup_dev.cmd
scripts\run_tests.cmd
```

do **not** rely on bare `pip` or `python` until venv exists. use:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements_dev.txt
.venv\Scripts\python.exe -m pytest tests -v
.venv\Scripts\python.exe -m app.main health-check --use-fixture --output output
```

## verify

```cmd
py --version
where py
dir .venv\Scripts\python.exe
```

## gui: `Unknown Vendor ID: 0x4d4f4351`

- **not an f5tool error** — comes from **Qt** when reading monitor EDID (display manufacturer code not in Qt’s lookup table).
- `0x4d4f4351` as ASCII bytes is **`MOCQ`** (often a dock/USB/secondary monitor).
- If you see `window shown — check taskbar if not visible`, the GUI **started normally**; ignore the line or hide it:

```cmd
set QT_LOGGING_RULES=qt.gui.edid=false
scripts\run_gui.cmd
```

`run_gui.cmd` sets `QT_LOGGING_RULES` and `QT_LOGGING_TO_CONSOLE=0` by default.

**PyInstaller exe (windowed, no console):** this message normally does not appear for end users. Dev `python -m app.gui.main` may still print to the terminal if Qt writes before env is set — safe to ignore.
