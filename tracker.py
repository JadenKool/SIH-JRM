"""Decide whether the user is facing the screen, mainly from head angles (yaw + pitch).

How it works:
  1. Calibration: for the first ~1.5 s with a face visible, it records your head angles while
     you look at the screen. That becomes "center", so a webcam mounted above the screen
     (which sees you tilted down) still counts as looking.
  2. Each frame: head yaw/pitch from a 3D face fit, smoothed, compared to center.
     Hysteresis: it takes a stricter angle to START looking than to KEEP looking, so it
     doesn't flicker at the edge.
  3. Iris check: rejects eyes-only side glances while your head stays still.

Self-test (no webcam needed):  python tracker.py
"""

import math

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise ImportError("Install tracker dependencies: pip install -r requirements.txt") from exc

# ---------------- Tunables ----------------
MAX_YAW_DEGREES = 15.0     # head turned left/right from center by more than this = away
MAX_PITCH_DEGREES = 12.0   # head tilted up/down (e.g. at a phone) by more than this = away
EXIT_MARGIN_DEGREES = 6.0  # once looking, allow this much extra before switching to away
IRIS_H_MIN, IRIS_H_MAX = 0.25, 0.75  # eyes-only glance check (0 = one corner, 1 = the other)
SMOOTHING = 0.4            # weight of the newest frame's angles (lower = steadier but slower)
CALIBRATION_FRAMES = 45    # ~1.5 s at 30 FPS
# -------------------------------------------

# Face Mesh sees a mirrored frame, so these labels avoid naming the user's eyes.
# Each tuple is (inner corner, outer corner, iris center).
EYE_A = (362, 263, 473)
EYE_B = (133, 33, 468)

# Nose, chin, image-left/right outer eye corners, image-left/right mouth corners.
POSE_LANDMARKS = (1, 152, 33, 263, 61, 291)
# Approximate face model with x right, y down, and z increasing into the frame.
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


def iris_ratio(landmarks):
    """Average horizontal iris position across both eyes (0.5 = centered), or None."""
    ratios = []
    for inner, outer, iris in (EYE_A, EYE_B):
        x1, x2 = landmarks[inner].x, landmarks[outer].x
        if abs(x2 - x1) > 1e-6:
            ratios.append((landmarks[iris].x - min(x1, x2)) / abs(x2 - x1))
    return sum(ratios) / len(ratios) if ratios else None


def decide(yaw, pitch, iris, was_looking):
    """Looking = head near calibrated center AND eyes not glancing sideways."""
    margin = EXIT_MARGIN_DEGREES if was_looking else 0.0
    head_ok = abs(yaw) <= MAX_YAW_DEGREES + margin and abs(pitch) <= MAX_PITCH_DEGREES + margin
    iris_ok = iris is not None and IRIS_H_MIN <= iris <= IRIS_H_MAX
    return head_ok and iris_ok


class EyeTracker:
    def __init__(self):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise ImportError("Install tracker dependencies: pip install -r requirements.txt") from exc
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1, refine_landmarks=True,
            min_detection_confidence=0.6, min_tracking_confidence=0.6)
        self.looking = False
        self.recalibrate()

    def recalibrate(self):
        """Forget the center pose; the next CALIBRATION_FRAMES face frames set a new one."""
        self.center = None
        self._samples = []
        self._smoothed = None

    def process_frame(self, frame):
        """Return raw per-frame gaze and an annotated mirrored frame; the caller debounces."""
        annotated = cv2.flip(frame, 1)
        height, width = annotated.shape[:2]
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        faces = self.mesh.process(rgb).multi_face_landmarks

        is_looking = False
        status, detail = "NO FACE", ""
        angles = None
        if faces:
            landmarks = faces[0].landmark
            angles = head_angles(landmarks, width, height)
        if angles is None:
            self._smoothed = None
        elif self.center is None:
            self._samples.append(angles)
            if len(self._samples) >= CALIBRATION_FRAMES:
                self.center = tuple(np.median(self._samples, axis=0))
            status = "CALIBRATING"
            detail = f"look at the screen {len(self._samples)}/{CALIBRATION_FRAMES}"
        else:
            self._smoothed = angles if self._smoothed is None else tuple(
                SMOOTHING * new + (1 - SMOOTHING) * old for new, old in zip(angles, self._smoothed))
            yaw = self._smoothed[0] - self.center[0]
            pitch = self._smoothed[1] - self.center[1]
            iris = iris_ratio(landmarks)
            is_looking = decide(yaw, pitch, iris, self.looking)
            status = "LOOKING" if is_looking else "AWAY"
            detail = f"yaw {yaw:+.0f}  pitch {pitch:+.0f}  eyes {iris or 0:.2f}"

        if faces:
            for _, _, iris_index in (EYE_A, EYE_B):
                point = landmarks[iris_index]
                cv2.circle(annotated, (int(point.x * width), int(point.y * height)), 4, (255, 255, 0), -1)
        self.looking = is_looking

        # Big text: the preview is shown shrunk, so small fonts become unreadable.
        color = {"LOOKING": (0, 200, 0), "CALIBRATING": (0, 180, 255)}.get(status, (0, 0, 255))
        cv2.rectangle(annotated, (0, 0), (width, 90), color, -1)
        cv2.putText(annotated, status, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(annotated, detail, (14, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
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
        rvec = cv2.Rodrigues(ry @ rx)[0]
        points, _ = cv2.projectPoints(POSE_MODEL, rvec, np.array([0, 0, 1500.0]), camera, None)
        landmarks = [Point(x=0.0, y=0.0)] * 478
        for index, (x, y) in zip(POSE_LANDMARKS, points.reshape(-1, 2)):
            landmarks[index] = Point(x=x / width, y=y / height)
        yaw, pitch = head_angles(landmarks, width, height)
        assert abs(yaw - yaw_in) < 1.5 and abs(pitch - pitch_in) < 1.5, (yaw_in, pitch_in, yaw, pitch)

    # Decision + hysteresis.
    assert decide(0, 0, 0.5, False)
    assert not decide(18, 0, 0.5, False)       # too far to start looking
    assert decide(18, 0, 0.5, True)            # but close enough to keep looking
    assert not decide(25, 0, 0.5, True)        # beyond the exit margin
    assert not decide(0, -20, 0.5, True)       # head down at a phone
    assert not decide(0, 0, 0.9, False)        # eyes glancing sideways
    assert not decide(0, 0, None, False)
    print("tracker selftest OK")


if __name__ == "__main__":
    _selftest()
