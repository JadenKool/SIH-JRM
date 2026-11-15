"""Decide whether the user is looking at the screen from head angle + eye direction combined.

How it works:
  1. Calibration: for the first ~1.5 s with a face visible, it records your head angles and
     iris position while you look at the screen. That becomes "center".
  2. Gaze = head turn + eye turn. If you turn your head right but keep your eyes on the screen,
     your eyes rotate the other way inside your head and the two cancel out, so it still
     counts as looking. Turning head AND eyes away does not cancel, so that counts as away.
  3. Slim / narrow eyes: the iris position averages 5 iris points per eye, weights the eye that
     is more visible (the near eye when your head is turned), and ignores frames where an eye
     is nearly shut (blink, squint) by keeping the last good reading instead.
  4. Smoothing + hysteresis: a stricter angle to START looking than to KEEP looking, so it
     doesn't flicker at the edge.

Self-test (no webcam needed):  python tracker.py
"""

import math

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise ImportError("Install tracker dependencies: pip install -r requirements.txt") from exc

# ---------------- Tunables ----------------
MAX_GAZE_YAW_DEGREES = 15.0   # where you're looking left/right (head + eyes), from center
MAX_HEAD_YAW_DEGREES = 45.0   # head turned further than this = away (face fit gets unreliable)
MAX_PITCH_DEGREES = 12.0      # head tilted up/down (e.g. at a phone) by more than this = away
EXIT_MARGIN_DEGREES = 6.0     # once looking, allow this much extra before switching to away
# Degrees of eye rotation per unit of iris position (0..1 across the eye). Raise it if turning your
# head while staring at the screen still reads as away; lower it if eye-only glances don't register.
EYE_DEGREES_PER_RATIO = 120.0
MIN_EYE_OPENNESS = 0.10       # lid gap / eye width; below this (blink, squint) skip that eye. Slim eyes ~0.15-0.2
SMOOTHING = 0.4               # weight of the newest frame (lower = steadier but slower)
CALIBRATION_SETTLE_FRAMES = 20  # ~0.7 s to find the calibration dot before sampling starts
CALIBRATION_FRAMES = 45       # ~1.5 s at 30 FPS
# -------------------------------------------

# Face Mesh sees a mirrored frame, so these labels avoid naming the user's eyes.
# Each tuple is (inner corner, outer corner, upper lid, lower lid, iris center + 4 iris ring points).
EYE_A = (362, 263, 386, 374, (473, 474, 475, 476, 477))
EYE_B = (133, 33, 159, 145, (468, 469, 470, 471, 472))

# Nose, chin, image-left/right outer eye corners, image-left/right mouth corners.
POSE_LANDMARKS = (1, 152, 33, 263, 61, 291)
# Approximate face model with x right, y down, and z increasing into the frame.
# With this model, positive yaw turns the nose toward image-left.
POSE_MODEL = np.array([
    (0.0, 0.0, 0.0),
    (0.0, 330.0, 65.0),
    (-225.0, -170.0, 135.0),
    (225.0, -170.0, 135.0),
    (-150.0, 150.0, 125.0),
    (150.0, 150.0, 125.0),
], dtype=np.float64)


def head_angles(landmarks, width, height):
    """Return (yaw, pitch) in degrees from a 3D face fit, or None if the fit fails."""
    image_points = np.array([
        (landmarks[i].x * width, landmarks[i].y * height) for i in POSE_LANDMARKS
    ], dtype=np.float64)
    camera = np.array([
        (width, 0.0, width / 2),
        (0.0, width, height / 2),
        (0.0, 0.0, 1.0),
    ], dtype=np.float64)
    ok, rotation, translation = cv2.solvePnP(POSE_MODEL, image_points, camera, None)
    if not ok or translation[2, 0] <= 0:
        return None
    matrix, _ = cv2.Rodrigues(rotation)
    pitch, yaw, _roll = cv2.RQDecomp3x3(matrix)[0]
    return yaw, pitch


def iris_ratio(landmarks, width, height):
    """Horizontal iris position, 0.5 = centered, larger = toward image-right; None if both eyes shut.

    Each eye's reading is weighted by how wide it appears, so the near eye counts more when the
    head is turned and the far eye is squashed.
    """
    total = weight = 0.0
    for inner, outer, upper, lower, iris in (EYE_A, EYE_B):
        x1, x2 = landmarks[inner].x * width, landmarks[outer].x * width
        eye_width = abs(x2 - x1)
        if eye_width < 1:
            continue
        openness = abs(landmarks[lower].y - landmarks[upper].y) * height / eye_width
        if openness < MIN_EYE_OPENNESS:
            continue
        iris_x = sum(landmarks[i].x for i in iris) / len(iris) * width
        total += iris_x - min(x1, x2)  # == ratio * eye_width
        weight += eye_width
    return total / weight if weight else None


class GazeFilter:
    """Calibration + smoothing. Pure math, so it can be tested without a webcam."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.center = None    # (yaw, pitch, iris) while looking at the screen
        self.samples = []
        self.smoothed = None
        self.settle = 0       # face frames seen since calibration started

    def lost(self):
        self.smoothed = None  # face gone: don't blend stale angles into the next sighting

    def update(self, yaw, pitch, iris):
        """Feed one frame. Returns None while calibrating, else (gaze_yaw, head_yaw, pitch) from center."""
        if self.center is None:
            if self.settle < CALIBRATION_SETTLE_FRAMES:
                self.settle += 1  # eyes still travelling to the dot
            elif iris is not None:
                self.samples.append((yaw, pitch, iris))
                if len(self.samples) >= CALIBRATION_FRAMES:
                    self.center = tuple(float(v) for v in np.median(self.samples, axis=0))
            return None
        if self.smoothed is None:
            self.smoothed = (yaw, pitch, self.center[2] if iris is None else iris)
        else:
            a = SMOOTHING
            old_yaw, old_pitch, old_iris = self.smoothed
            self.smoothed = (a * yaw + (1 - a) * old_yaw,
                             a * pitch + (1 - a) * old_pitch,
                             old_iris if iris is None else a * iris + (1 - a) * old_iris)  # eye shut: hold
        head_yaw, pitch_rel, iris_rel = (s - c for s, c in zip(self.smoothed, self.center))
        # Head turned nose-left (+yaw) while watching the screen moves the iris right (+iris): cancels.
        return head_yaw - EYE_DEGREES_PER_RATIO * iris_rel, head_yaw, pitch_rel


def draw_calibration_target(width, height, progress):
    """Black screen with a big dot in the exact middle and a ring that fills as calibration runs."""
    image = np.zeros((height, width, 3), np.uint8)
    center = (width // 2, height // 2)
    radius = max(40, min(width, height) // 14)
    cv2.circle(image, center, radius, (70, 70, 70), -1, cv2.LINE_AA)
    if progress > 0:
        cv2.ellipse(image, center, (radius, radius), -90, 0, 360 * min(progress, 1.0),
                    (0, 200, 255), max(6, radius // 6), cv2.LINE_AA)
    cv2.circle(image, center, max(10, radius // 3), (255, 255, 255), -1, cv2.LINE_AA)
    text = "Look at the dot"
    scale = height / 900
    (text_w, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.putText(image, text, (center[0] - text_w // 2, center[1] + radius * 2 + int(20 * scale)),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (200, 200, 200), 2, cv2.LINE_AA)
    return image


def decide(gaze_yaw, head_yaw, pitch, was_looking):
    """Looking = gaze near center, head not wildly turned, head not tilted down/up."""
    margin = EXIT_MARGIN_DEGREES if was_looking else 0.0
    return (abs(gaze_yaw) <= MAX_GAZE_YAW_DEGREES + margin
            and abs(head_yaw) <= MAX_HEAD_YAW_DEGREES
            and abs(pitch) <= MAX_PITCH_DEGREES + margin)


class EyeTracker:
    def __init__(self):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise ImportError("Install tracker dependencies: pip install -r requirements.txt") from exc
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1, refine_landmarks=True,
            min_detection_confidence=0.5, min_tracking_confidence=0.5)
        self.filter = GazeFilter()
        self.looking = False

    def recalibrate(self):
        """Forget the center pose; the next CALIBRATION_FRAMES face frames set a new one."""
        self.filter.reset()

    @property
    def calibration_progress(self):
        """None once calibrated, else 0.0-1.0 for the on-screen target."""
        if self.filter.center is not None:
            return None
        return len(self.filter.samples) / CALIBRATION_FRAMES

    def process_frame(self, frame):
        """Return raw per-frame gaze and an annotated mirrored frame; the caller debounces."""
        annotated = cv2.flip(frame, 1)
        height, width = annotated.shape[:2]
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        faces = self.mesh.process(rgb).multi_face_landmarks

        is_looking = False
        status, detail = "NO FACE", ""
        landmarks = faces[0].landmark if faces else None
        angles = head_angles(landmarks, width, height) if landmarks else None
        if angles is None:
            self.filter.lost()
        else:
            iris = iris_ratio(landmarks, width, height)
            result = self.filter.update(*angles, iris)
            if result is None:
                status = "CALIBRATING"
                detail = f"look at screen {len(self.filter.samples)}/{CALIBRATION_FRAMES}"
            else:
                gaze_yaw, head_yaw, pitch = result
                is_looking = decide(gaze_yaw, head_yaw, pitch, self.looking)
                status = "LOOKING" if is_looking else "AWAY"
                detail = f"gaze {gaze_yaw:+.0f} head {head_yaw:+.0f} tilt {pitch:+.0f}"
            for *_, iris_points in (EYE_A, EYE_B):
                point = landmarks[iris_points[0]]
                cv2.circle(annotated, (int(point.x * width), int(point.y * height)), 4, (255, 255, 0), -1)
        self.looking = is_looking

        # Big text, scaled to the frame: the preview is shown shrunk.
        scale = width / 640
        color = {"LOOKING": (0, 200, 0), "CALIBRATING": (0, 180, 255)}.get(status, (0, 0, 255))
        cv2.rectangle(annotated, (0, 0), (width, int(100 * scale)), color, -1)
        cv2.putText(annotated, status, (int(14 * scale), int(50 * scale)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.5 * scale, (255, 255, 255), max(2, int(3 * scale)), cv2.LINE_AA)
        cv2.putText(annotated, detail, (int(14 * scale), int(88 * scale)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1 * scale, (255, 255, 255), max(2, int(2 * scale)), cv2.LINE_AA)
        return {"is_looking": is_looking, "annotated_frame": annotated}

    def close(self):
        self.mesh.close()


def _selftest():
    from types import SimpleNamespace as Point

    # Head-angle math: project the face model at known angles, recover them.
    width, height = 640, 480
    camera = np.array([(width, 0, width / 2), (0, width, height / 2), (0, 0, 1)], float)
    for yaw_in, pitch_in in ((0, 0), (15, 0), (-25, 0), (0, 10), (0, -15), (12, -8)):
        rx = cv2.Rodrigues(np.array([math.radians(pitch_in), 0.0, 0.0]))[0]
        ry = cv2.Rodrigues(np.array([0.0, math.radians(yaw_in), 0.0]))[0]
        points, _ = cv2.projectPoints(POSE_MODEL, cv2.Rodrigues(ry @ rx)[0],
                                      np.array([0, 0, 1500.0]), camera, None)
        landmarks = [Point(x=0.0, y=0.0)] * 478
        for index, (x, y) in zip(POSE_LANDMARKS, points.reshape(-1, 2)):
            landmarks[index] = Point(x=x / width, y=y / height)
        yaw, pitch = head_angles(landmarks, width, height)
        assert abs(yaw - yaw_in) < 1.5 and abs(pitch - pitch_in) < 1.5, (yaw_in, pitch_in, yaw, pitch)
        if yaw_in:  # sign convention the gaze formula relies on: +yaw = nose toward image-left
            nose_x, eyes_mid_x = points[0, 0, 0], (points[2, 0, 0] + points[3, 0, 0]) / 2
            assert (nose_x < eyes_mid_x) == (yaw_in > 0)

    # Iris ratio: weighted toward the wider eye, shut eyes skipped.
    def eyes(ratio_a, ratio_b, width_a=0.05, width_b=0.05, open_a=0.02, open_b=0.02):
        lm = [Point(x=0.0, y=0.0) for _ in range(478)]
        for (inner, outer, upper, lower, iris), left, w, ratio, gap in (
                (EYE_A, 0.6, width_a, ratio_a, open_a), (EYE_B, 0.3, width_b, ratio_b, open_b)):
            lm[inner], lm[outer] = Point(x=left, y=0.5), Point(x=left + w, y=0.5)
            lm[upper], lm[lower] = Point(x=left, y=0.5 - gap / 2), Point(x=left, y=0.5 + gap / 2)
            for i in iris:
                lm[i] = Point(x=left + ratio * w, y=0.5)
        return lm
    assert abs(iris_ratio(eyes(0.5, 0.5), 640, 480) - 0.5) < 1e-6
    assert abs(iris_ratio(eyes(0.6, 0.4, width_a=0.06, width_b=0.02), 640, 480) - 0.55) < 1e-6
    assert abs(iris_ratio(eyes(0.6, 0.3, open_b=0.0), 640, 480) - 0.6) < 1e-6   # B shut: A only
    assert iris_ratio(eyes(0.5, 0.5, open_a=0.0, open_b=0.0), 640, 480) is None  # blink

    # Calibration + combined gaze.
    f = GazeFilter()
    for _ in range(CALIBRATION_SETTLE_FRAMES):  # glances while finding the dot are thrown away
        assert f.update(40.0, 30.0, 0.9) is None
    assert f.samples == []
    for i in range(CALIBRATION_FRAMES - 1):
        assert f.update(2.0 + (i % 3), -10.0, 0.5) is None   # still calibrating
    assert f.update(3.0, -10.0, None) is None and len(f.samples) == CALIBRATION_FRAMES - 1  # shut eyes: no sample
    assert f.update(3.0, -10.0, 0.5) is None and f.center == (3.0, -10.0, 0.5)              # median
    gaze, head, pitch = f.update(3.0, -10.0, 0.5)
    assert abs(gaze) < 1e-9 and abs(pitch) < 1e-9
    f.lost()  # Head turned 25 deg, eyes counter-rotated back to the screen -> gaze ~0 -> looking.
    gaze, head, pitch = f.update(3.0 + 25, -10.0, 0.5 + 25 / EYE_DEGREES_PER_RATIO)
    assert abs(head - 25) < 1e-9 and abs(gaze) < 1e-9 and decide(gaze, head, pitch, False)
    f.lost()  # Head turned 25 deg, eyes staying straight in the head -> looking away.
    gaze, head, pitch = f.update(3.0 + 25, -10.0, 0.5)
    assert abs(gaze - 25) < 1e-9 and not decide(gaze, head, pitch, True)
    f.lost()  # Eyes shut mid-turn: hold the last iris reading instead of snapping to center.
    f.update(3.0 + 20, -10.0, 0.5 + 20 / EYE_DEGREES_PER_RATIO)
    gaze, _, _ = f.update(3.0 + 20, -10.0, None)
    assert abs(gaze) < 1e-9
    f.reset()
    assert f.center is None and f.update(0, 0, 0.5) is None

    # Calibration target: dot in the exact middle, ring grows with progress.
    blank, half = draw_calibration_target(1920, 1080, 0.0), draw_calibration_target(1920, 1080, 0.5)
    assert blank.shape == (1080, 1920, 3) and (blank[540, 960] == 255).all()
    assert (half != blank).any()

    # Decision + hysteresis.
    assert decide(0, 0, 0, False)
    assert not decide(18, 18, 0, False)        # too far to start looking
    assert decide(18, 18, 0, True)             # but close enough to keep looking
    assert not decide(25, 25, 0, True)         # beyond the exit margin
    assert not decide(0, 50, 0, True)          # head turned too far to trust
    assert not decide(0, 0, -20, True)         # head down at a phone
    print("tracker selftest OK")


if __name__ == "__main__":
    _selftest()
