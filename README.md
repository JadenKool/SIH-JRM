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

On Windows, run `python auto_doomscroll.py` from the activated environment. The first launch may download a matching ChromeDriver through Selenium. At startup, the app loads Instagram Reels on the left and YouTube Shorts on the right and minimizes both Chrome windows. When the tracker detects that you're looking at the screen, both windows come forward. The app sends Down to both feeds after four seconds and repeats every four seconds. When you look away, it minimizes the windows and keeps your place in each feed for when you look back.

Sign in to Instagram in the app's Chrome window if prompted. Chrome saves that session in a dedicated profile for future runs.

Run `python auto_doomscroll.py --selftest` to test the timing without a webcam, browser, or third-party packages. The tracker preview window opens by default and stays on top; add `--no-preview` to hide it if it covers part of the browser windows.

## Test the Windows kill switch

Launch the doomscroller and focus either of its Chrome feed windows or the tracker preview. Press **Ctrl + Shift + Q**. The app pauses automatic scrolling and eye tracking, hides its windows, and opens the destruction prompt. The prompt has no cancel option.

1. Enter `SIH` or any other incorrect code and press Enter. The prompt should show **INVALID DESTRUCTION CODE**, then dismiss at the original 15-second deadline. The doomscroller should resume.
2. Press the shortcut again and leave the prompt alone. After 15 seconds, the prompt should dismiss and the doomscroller should resume again.
3. Press the shortcut again, enter `sih`, and press Enter before the timer runs out. The app and its feed windows should close immediately.
4. After restarting the app, press the shortcut while another app is focused. The prompt should open only when you press it with a Doomscroller window focused.
