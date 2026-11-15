"""The Automatic Doomscroller: look at your screen, lose your afternoon.

Run:        python auto_doomscroll.py
Self-test:  python auto_doomscroll.py --selftest   (no webcam/browser needed)
Stop:       Ctrl+C in the terminal, or slam the mouse into the TOP-LEFT corner.
"""
import argparse
import sys
import time

# ---------------- Tunables (adjust for venue lighting) ----------------
SCROLL_INTERVAL = 4.0      # seconds between "Down" presses while you're looking
LOAD_DELAY = 4.0           # seconds after showing the feeds before the first scroll
RETRIGGER_COOLDOWN = 10.0  # seconds away before the next glance starts a new viewing session
FRAMES_TO_LOOK = 3         # consecutive gaze hits before is_looking = True
FRAMES_TO_AWAY = 15        # consecutive gaze misses (~0.5 s at 30 FPS) before is_looking = False
URLS = [
    "https://www.instagram.com/reels/",
    "https://www.youtube.com/shorts/",
]
PREVIEW_WINDOW = "Doomscroller tracker"
CALIBRATION_WINDOW = "Doomscroller calibration"
CAMERA_SIZE = (1280, 720)   # requested webcam resolution
PREVIEW_WIDTH = 280         # px; small so the feeds stay visible
PREVIEW_BOTTOM_MARGIN = 90  # shortcut: assumes a ~48 px bottom taskbar + title bar; raise if the preview is cut off
# ----------------------------------------------------------------------


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
        s["tabs_opened"] = False  # next glance starts a new session with the same feeds

    if s["is_looking"] and now >= s["next_scroll"]:
        actions.append("scroll")
        s["next_scroll"] = now + SCROLL_INTERVAL
    return actions


def main():
    parser = argparse.ArgumentParser(description="Scroll Reels and Shorts when you look at the screen.")
    parser.add_argument("--selftest", action="store_true", help="Test the state machine without a webcam or browser.")
    parser.add_argument("--no-preview", dest="preview", action="store_false",
                        help="Hide the tracker preview (shown on top by default). It can cover part of a feed.")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return

    if sys.platform == "win32":
        from kill_switch import run_with_kill_switch

        run_with_kill_switch(run, args.preview, PREVIEW_WINDOW)
    else:
        run(args.preview)


def run(preview, paused=None, stopping=None, chrome_pid=None, ready=None):
    if ready is not None:
        ready.wait()
    from tracker import EyeTracker, draw_calibration_target
    try:
        from selenium.common.exceptions import WebDriverException
    except ModuleNotFoundError as exc:
        if exc.name != "selenium":
            raise
        sys.exit("Install browser dependencies: python -m pip install -r requirements.txt")

    from split_browser import SplitBrowser

    import cv2
    import pyautogui

    pyautogui.FAILSAFE = True  # mouse in top-left corner -> FailSafeException -> script exits

    # DirectShow opens much faster than the default backend on Windows
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
    # More pixels per eye = steadier iris tracking, especially for narrow eyes. MJPG keeps 30 FPS
    # on webcams that drop to ~10 FPS at 720p otherwise; cameras that can't do 720p ignore this.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
    tracker = None
    browser = None
    try:
        if not cap.isOpened():
            sys.exit("No webcam found (or another app is using it).")
        tracker = EyeTracker()
        print("Preparing Instagram Reels and YouTube Shorts in Chrome...", flush=True)
        browser = SplitBrowser()
        if chrome_pid is not None:
            chrome_pid.value = browser.driver.capabilities["goog:processID"]
        browser.prepare_feeds(URLS)
        if preview:
            cam_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640
            cam_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480
            preview_size = (PREVIEW_WIDTH, int(PREVIEW_WIDTH * cam_h / cam_w))
            cv2.namedWindow(PREVIEW_WINDOW)
            cv2.setWindowProperty(PREVIEW_WINDOW, cv2.WND_PROP_TOPMOST, 1)  # pop in front on startup
            cv2.moveWindow(PREVIEW_WINDOW, 0, pyautogui.size().height - preview_size[1] - PREVIEW_BOTTOM_MARGIN)
        s = new_state()
        screen = tuple(pyautogui.size())
        target_open = False
        print("Calibrating: look at the dot in the middle of the screen. "
              "To recalibrate later, click the preview, then press c.")
        print("Doomscroller armed. (Ctrl+C or mouse to top-left to stop)", flush=True)
        while paused is None or not paused.is_set():
            pyautogui.failSafeCheck()
            ok, frame = cap.read()
            if not ok or (paused is not None and paused.is_set()):
                continue
            result = tracker.process_frame(frame)
            for action in step(s, result["is_looking"], time.monotonic()):
                if paused is not None and paused.is_set():
                    break
                print(f"[{time.strftime('%H:%M:%S')}] {action}")
                if action in ("open", "resume"):
                    browser.show()
                    delay = LOAD_DELAY if action == "open" else SCROLL_INTERVAL
                    s["next_scroll"] = max(s["next_scroll"], time.monotonic() + delay)
                elif action == "away":
                    browser.hide()
                elif action == "scroll":
                    browser.scroll()
            if paused is not None and paused.is_set():
                continue
            progress = tracker.calibration_progress
            if progress is not None:
                # Full-screen dot covers the preview and feeds so nothing pulls the eyes off-center.
                if not target_open:
                    cv2.namedWindow(CALIBRATION_WINDOW, cv2.WINDOW_NORMAL)
                    cv2.setWindowProperty(CALIBRATION_WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    cv2.setWindowProperty(CALIBRATION_WINDOW, cv2.WND_PROP_TOPMOST, 1)
                    target_open = True
                cv2.imshow(CALIBRATION_WINDOW, draw_calibration_target(*screen, progress))
            elif target_open:
                cv2.destroyWindow(CALIBRATION_WINDOW)
                target_open = False
                print("Calibrated.", flush=True)
            if preview:
                cv2.imshow(PREVIEW_WINDOW, cv2.resize(result["annotated_frame"], preview_size,
                                                      interpolation=cv2.INTER_AREA))
            if cv2.waitKey(1) & 0xFF == ord("c"):
                tracker.recalibrate()
        if not stopping.is_set():
            cv2.destroyAllWindows()
            try:
                browser.freeze_feeds(stopping)
            except WebDriverException:
                pass  # The countdown and shutdown are independent of Chrome.
            stopping.wait()
    except (KeyboardInterrupt, pyautogui.FailSafeException):
        print("\nDoomscroller stopped. Go touch grass.")
    except WebDriverException as exc:
        sys.exit(f"Could not control Chrome: {exc.msg}\n"
                 "Check that Chrome is installed and the Doomscroller windows are open.")
    finally:
        cap.release()
        if tracker is not None:
            tracker.close()
        cv2.destroyAllWindows()  # preview and/or calibration target
        if browser is not None:
            browser.close()


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
    assert run(True, 1) == ["open"]               # 3rd frame: show the preloaded feeds
    assert run(True, 119) == []                   # still inside LOAD_DELAY, no re-open
    assert run(True, 10) == ["scroll"]            # first scroll after load delay
    assert run(True, 1) + run(False, 14) == []    # 14 missed frames: still looking
    assert run(False, 1) == ["away"]              # 15th: paused
    assert run(True, 2) + run(False, 5) == []     # 2-frame flicker doesn't count as looking
    assert run(False, 280) == [] and s["tabs_opened"]
    run(False, 30)
    assert not s["tabs_opened"]                   # 10 s away: cooldown expired
    assert run(True, 3) == ["open"]               # next glance starts a new viewing session
    run(False, 15)
    assert run(True, 3) == ["resume"]             # quick return: resume the existing session
    print("selftest OK")


if __name__ == "__main__":
    main()
