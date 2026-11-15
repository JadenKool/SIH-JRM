# The Automatic Doomscroller

## Windows 11 setup (Python 3.12)

The pinned MediaPipe 0.10.21 release provides Windows wheels for Python 3.9–3.12. Recreate the Python 3.14 virtual environment using Python 3.12.

From the repository root in **Command Prompt** (`cmd.exe`), with the [Python install manager](https://docs.python.org/3/using/windows.html#python-install-manager) installed, run the following. Run `deactivate` first if the old environment is active. The `ren` command keeps the old environment as a backup; skip it if there is no existing `.venv`, or choose a different backup name if `venv.bak` already exists.

```bat
py install 3.12
ren .venv venv.bak
py -3.12 -m venv .venv
.venv\Scripts\activate
python --version
python -m pip install -r requirements.txt
```

`python --version` should report Python 3.12.x.

Run `python auto_doomscroll.py` to start, or `python auto_doomscroll.py --selftest` to test without a webcam, browser, or third-party packages. Add `--preview` to show the tracker for a demo; the preview may take keyboard focus from the browser and intercept the Down presses.
