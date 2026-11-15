"""Estimate screen gaze from iris position and head yaw, one frame at a time."""

import math

try:
    import cv2
    import mediapipe as mp
    import numpy as np
except ImportError as exc:
    raise ImportError("Install tracker dependencies: pip install -r requirements.txt") from exc


# Face Mesh sees a mirrored frame, so these labels avoid naming the user's eyes.
# Each tuple is (inner corner, outer corner, iris center, upper lid, lower lid).
EYE_A = (362, 263, 473, 386, 374)
EYE_B = (133, 33, 468, 159, 145)
IRIS_H_MIN, IRIS_H_MAX = 0.30, 0.70
IRIS_V_MIN, IRIS_V_MAX = 0.20, 0.70  # 0 = upper lid; 1 = lower lid
MAX_YAW_DEGREES = 20.0

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


def _iris_in_band(landmarks, eye):
    inner, outer, iris, upper, lower = (landmarks[i] for i in eye)
    width = abs(inner.x - outer.x)
    height = lower.y - upper.y
    if width <= 0 or height <= 0:
        return False
    # Measured from the smaller x; the corner order does not affect the ratio.
    horizontal = (iris.x - min(inner.x, outer.x)) / width
    vertical = (iris.y - upper.y) / height
    return (IRIS_H_MIN <= horizontal <= IRIS_H_MAX
            and IRIS_V_MIN <= vertical <= IRIS_V_MAX)


def _head_yaw(landmarks, width, height):
    image_points = np.array([
        (landmarks[i].x * width, landmarks[i].y * height)
        for i in POSE_LANDMARKS
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
    return math.degrees(math.atan2(matrix[0, 2], matrix[2, 2]))


class EyeTracker:
    def __init__(self):
        self.mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True)

    def process_frame(self, frame):
        """Return raw gaze and an annotated mirrored frame; the caller debounces gaze."""
        annotated = cv2.flip(frame, 1)
        height, width = annotated.shape[:2]
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        faces = self.mesh.process(rgb).multi_face_landmarks
        is_looking = False
        label = "No face"
        if faces:
            landmarks = faces[0].landmark
            yaw = _head_yaw(landmarks, width, height)
            is_looking = (yaw is not None and abs(yaw) <= MAX_YAW_DEGREES
                          and all(_iris_in_band(landmarks, eye) for eye in (EYE_A, EYE_B)))
            label = "Looking" if is_looking else "Away"
            if yaw is not None:
                label += f" | yaw {yaw:+.0f} deg"
            for eye in (EYE_A, EYE_B):
                iris = landmarks[eye[2]]
                cv2.circle(annotated, (int(iris.x * width), int(iris.y * height)),
                           3, (255, 255, 0), -1)
        color = (0, 220, 0) if is_looking else (0, 0, 255)
        cv2.putText(annotated, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, color, 2, cv2.LINE_AA)
        return {"is_looking": is_looking, "annotated_frame": annotated}

    def close(self):
        self.mesh.close()
