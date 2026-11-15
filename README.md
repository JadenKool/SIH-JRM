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

## Run the doomscroller

Install Google Chrome. If your Python 3.12 environment already exists, install the current requirements. On macOS, use the environment's Python directly from the project folder.

```sh
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python auto_doomscroll.py
```

On Windows, run `python auto_doomscroll.py` from the activated environment. The first launch may download a matching ChromeDriver through Selenium. The app opens Instagram Reels on the left and YouTube Shorts on the right in two Chrome windows. It sends Down to both feeds four seconds after opening them, then every four seconds while you're looking. Sign in to Instagram in the app's Chrome window if prompted. Chrome saves that session in a dedicated profile for future runs.

Run `python auto_doomscroll.py --selftest` to test the timing without a webcam, browser, or third-party packages. Add `--preview` to show the tracker window for a demo. It can cover part of the browser windows.
