"""The Automatic Doomscroller: look at your screen, lose your afternoon.

Run:        python auto_doomscroll.py
Self-test:  python auto_doomscroll.py --selftest   (no webcam/browser needed)
Stop:       Ctrl+C in the terminal, or slam the mouse into the TOP-LEFT corner.
"""
import sys
import time
import webbrowser

import cv2
import pyautogui

# ---------------- Tunables (adjust for venue lighting) ----------------
SCROLL_INTERVAL = 4.0      # seconds between "Down" presses while you're looking
LOAD_DELAY = 3.5           # seconds to let Reels/Shorts load before the first scroll
RETRIGGER_COOLDOWN = 10.0  # seconds of continuous look-away before tabs may open again
MIN_NEIGHBORS = 5          # Haar sensitivity: lower (3-4) = catches faces in dim light but more false hits; higher (6-8) = stricter
MIN_FACE_SIZE = (80, 80)   # ignore small/distant faces (people walking behind you)
FRAMES_TO_LOOK = 3         # consecutive face frames before is_looking = True
FRAMES_TO_AWAY = 15        # consecutive no-face frames (~0.5 s at 30 FPS) before is_looking = False
URLS = [
    "https://www.instagram.com/reels/",
    "https://www.youtube.com/shorts/",  # opened last, so this tab has focus and receives the Down presses
]
# ----------------------------------------------------------------------

pyautogui.FAILSAFE = True  # mouse in top-left corner -> FailSafeException -> script exits


def new_state():
    return {"is_looking": False, "hits": 0, "misses": 0,
            "tabs_opened": False, "away_since": None, "next_scroll": 0.0}


def step(s, face_seen, now):
    """Advance the state machine by one frame. Returns actions: 'open', 'resume', 'away', 'scroll'."""
    actions = []
    if face_seen:
        s["hits"], s["misses"] = s["hits"] + 1, 0
    else:
        s["hits"], s["misses"] = 0, s["misses"] + 1

    if not s["is_looking"] and s["hits"] >= FRAMES_TO_LOOK:
        s["is_looking"], s["away_since"] = True, None
        if s["tabs_opened"]:
            actions.append("resume")
            s["next_scroll"] = max(s["next_scroll"], now + SCROLL_INTERVAL)
        else:
            s["tabs_opened"] = True
            actions.append("open")
            s["next_scroll"] = now + LOAD_DELAY
    elif s["is_looking"] and s["misses"] >= FRAMES_TO_AWAY:
        s["is_looking"], s["away_since"] = False, now
        actions.append("away")

    if (not s["is_looking"] and s["tabs_opened"] and s["away_since"] is not None
            and now - s["away_since"] >= RETRIGGER_COOLDOWN):
        s["tabs_opened"] = False  # looked away long enough: next glance opens fresh tabs

    if s["is_looking"] and now >= s["next_scroll"]:
        actions.append("scroll")
        s["next_scroll"] = now + SCROLL_INTERVAL
    return actions


def main():
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        sys.exit("Could not load Haar cascade.")
    # DirectShow opens much faster than the default backend on Windows
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
    if not cap.isOpened():
        sys.exit("No webcam found (or another app is using it).")

    s = new_state()
    print("Doomscroller armed. Look at the screen... (Ctrl+C or mouse to top-left to stop)")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1,
                                             minNeighbors=MIN_NEIGHBORS, minSize=MIN_FACE_SIZE)
            for action in step(s, len(faces) > 0, time.monotonic()):
                print(f"[{time.strftime('%H:%M:%S')}] {action}")
                if action == "open":
                    for url in URLS:
                        webbrowser.open_new_tab(url)
                elif action == "scroll":
                    pyautogui.press("down")
    except (KeyboardInterrupt, pyautogui.FailSafeException):
        print("\nDoomscroller stopped. Go touch grass.")
    finally:
        cap.release()


def selftest():
    s, t, dt = new_state(), 0.0, 1 / 30

    def run(face, n):
        nonlocal t
        out = []
        for _ in range(n):
            out += step(s, face, t)
            t += dt
        return out

    assert run(True, 2) == []                     # 2 frames: not enough
    assert run(True, 1) == ["open"]               # 3rd frame: tabs open once
    assert run(True, 100) == []                   # still inside LOAD_DELAY, no re-open
    assert run(True, 10) == ["scroll"]            # first scroll after load delay
    assert run(True, 1) + run(False, 14) == []    # 14 missed frames: still looking
    assert run(False, 1) == ["away"]              # 15th: paused
    assert run(True, 2) + run(False, 5) == []     # 2-frame flicker doesn't count as looking
    assert run(False, 280) == [] and s["tabs_opened"]
    run(False, 30)
    assert not s["tabs_opened"]                   # 10 s away: cooldown expired
    assert run(True, 3) == ["open"]               # next glance re-opens
    run(False, 15)
    assert run(True, 3) == ["resume"]             # quick return: no tab-bombing
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
