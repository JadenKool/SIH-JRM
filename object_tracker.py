"""Real-time confidence-tracking GUI (OpenCV CSRT tracker).

Run:        python object_tracker.py
Self-test:  python object_tracker.py --selftest   (no webcam needed)

Controls:   r = pause and re-select a target    q / Esc = quit
            "Min confidence %" slider = threshold for counting a result as a lock

To swap in a detector (YOLOv8, OpenCV DNN, ...), write a class with the same two
methods as CSRTBackend (`start` and `update`) and change `make_backend()`.
Nothing else in the GUI needs to change.
"""
import sys
import time

import cv2
import numpy as np

WINDOW = "Confidence Tracker"
SLIDER = "Min confidence %"
DEFAULT_THRESHOLD = 50  # percent

GREEN = (0, 220, 0)  # BGR
RED = (0, 0, 255)
WHITE = (255, 255, 255)


# ----------------------------------------------------------------------------
# Tracking backends: anything with start(frame, box) and update(frame)
# ----------------------------------------------------------------------------
class CSRTBackend:
    """Wraps cv2.TrackerCSRT. CSRT has no confidence score, so we report 1.0 or 0.0."""

    def start(self, frame, box):
        """Begin tracking `box` = (x, y, w, h) in `frame`."""
        self.tracker = cv2.TrackerCSRT_create()
        self.tracker.init(frame, box)

    def update(self, frame):
        """Return (box or None, confidence 0.0-1.0) for this frame."""
        success, box = self.tracker.update(frame)
        return (tuple(int(v) for v in box), 1.0) if success else (None, 0.0)


# Example shape for a later detector swap (not used yet):
# class YoloBackend:
#     def start(self, frame, box): self.target_class = ...   # pick class under the box
#     def update(self, frame):
#         results = model(frame)                             # ultralytics YOLO
#         best = highest-scoring box of self.target_class
#         return (x, y, w, h), best.conf                     # conf already 0.0-1.0


def make_backend():
    return CSRTBackend()


# ----------------------------------------------------------------------------
# Drawing helpers
# ----------------------------------------------------------------------------
def draw_translucent_bar(frame, y1, y2, color=(0, 0, 0), alpha=0.55):
    """Darken a full-width strip between rows y1 and y2 (semi-transparent HUD)."""
    strip = frame[y1:y2]
    overlay = np.full_like(strip, color)
    cv2.addWeighted(overlay, alpha, strip, 1 - alpha, 0, dst=strip)


def draw_dashed_rect(frame, box, color, dash=10, thickness=2):
    """OpenCV has no dashed rectangle, so draw every other short segment of each edge."""
    x, y, w, h = box
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        length = max(abs(x2 - x1), abs(y2 - y1))
        for start in range(0, length, dash * 2):
            end = min(start + dash, length)
            p1 = (x1 + (x2 - x1) * start // length, y1 + (y2 - y1) * start // length)
            p2 = (x1 + (x2 - x1) * end // length, y1 + (y2 - y1) * end // length)
            cv2.line(frame, p1, p2, color, thickness, cv2.LINE_AA)


def draw_status_banner(frame, locked, confidence):
    """Top banner: green badge + confidence bar when locked, red warning when lost."""
    width = frame.shape[1]
    draw_translucent_bar(frame, 0, 50, GREEN if locked else RED, alpha=0.6)
    text = "STATUS: CONFIDENT / LOCKED" if locked else "STATUS: NOT CONFIDENT / LOST TARGET"
    cv2.putText(frame, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2, cv2.LINE_AA)

    # Confidence bar on the right side of the banner
    bar_w = 160
    x1, y1, x2, y2 = width - bar_w - 12, 18, width - 12, 34
    if x1 > 0:
        cv2.rectangle(frame, (x1, y1), (x2, y2), WHITE, 1)
        cv2.rectangle(frame, (x1, y1), (x1 + int(bar_w * confidence), y2), WHITE, -1)


def draw_hud(frame, fps, locked, threshold):
    """Bottom semi-transparent HUD with FPS, status, threshold and shortcuts."""
    height = frame.shape[0]
    draw_translucent_bar(frame, height - 34, height)
    status = "LOCKED" if locked else "LOST"
    text = f"FPS {fps:5.1f} | {status} | min conf {threshold}% | r: re-select   q: quit"
    cv2.putText(frame, text, (12, height - 12), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, WHITE, 1, cv2.LINE_AA)


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------
def select_target(frame):
    """Pop up selectROI on a frozen frame. Returns (x, y, w, h) or None if cancelled."""
    box = cv2.selectROI("Select target: drag a box, ENTER/SPACE to confirm, c to cancel",
                        frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Select target: drag a box, ENTER/SPACE to confirm, c to cancel")
    return box if box[2] > 0 and box[3] > 0 else None


def render(frame, box, last_box, confidence, threshold, fps):
    """Draw all overlays for one frame. Returns (locked, last_box)."""
    locked = box is not None and confidence * 100 >= threshold
    if locked:
        x, y, w, h = box
        cv2.rectangle(frame, (x, y), (x + w, y + h), GREEN, 3)
        last_box = box
    elif last_box is not None:
        draw_dashed_rect(frame, last_box, RED)  # last known position
    draw_status_banner(frame, locked, confidence if locked else 0.0)
    draw_hud(frame, fps, locked, threshold)
    return locked, last_box


def main():
    # DirectShow opens much faster than the default backend on Windows
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(0)
    if not cap.isOpened():
        sys.exit("No webcam found (or another app is using it).")

    try:
        ok, frame = cap.read()
        if not ok:
            sys.exit("Could not read from the webcam.")
        box = select_target(frame)
        if box is None:
            print("No target selected. Exiting.")
            return

        backend = make_backend()
        backend.start(frame, box)
        last_box = box

        cv2.namedWindow(WINDOW)
        cv2.createTrackbar(SLIDER, WINDOW, DEFAULT_THRESHOLD, 100, lambda _: None)

        fps, prev = 0.0, time.perf_counter()
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            found_box, confidence = backend.update(frame)
            threshold = cv2.getTrackbarPos(SLIDER, WINDOW)

            now = time.perf_counter()
            fps = 0.9 * fps + 0.1 / max(now - prev, 1e-6)  # smoothed so the number is readable
            prev = now

            _, last_box = render(frame, found_box, last_box, confidence, threshold, fps)
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # q or Esc
                break
            if key == ord("r"):
                new_box = select_target(frame)  # live feed pauses while the pop-up is open
                if new_box is not None:          # cancelled -> keep tracking the old target
                    backend.start(frame, new_box)
                    last_box = new_box
                prev = time.perf_counter()       # don't count the pause in FPS
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break  # window closed with the X button
    finally:
        cap.release()
        cv2.destroyAllWindows()


# ----------------------------------------------------------------------------
# Self-test: CSRT follows a moving square, overlays draw without errors
# ----------------------------------------------------------------------------
def selftest():
    def scene(x):
        frame = np.full((480, 640, 3), 40, np.uint8)
        cv2.rectangle(frame, (x, 200), (x + 60, 260), (0, 200, 255), -1)
        cv2.circle(frame, (x + 30, 230), 12, (255, 0, 0), -1)
        return frame

    backend = make_backend()
    backend.start(scene(100), (100, 200, 60, 60))
    for x in range(104, 300, 4):
        box, conf = backend.update(scene(x))
    assert box is not None and conf == 1.0 and abs(box[0] - x) < 15, box

    frame = scene(x)
    assert render(frame, box, None, conf, 50, 30.0)[0] is True       # locked at 50%
    assert render(frame, None, box, 0.0, 50, 30.0) == (False, box)    # lost: keeps last box
    assert render(frame, box, None, 0.4, 50, 30.0)[0] is False        # below threshold
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
