# ------- PPT Gesture Control (Streamlit / WebRTC version) -------
# Evolved from the original desktop script:
#   - Same finger-counting core: OpenCV contour + convexity-defect method
#     (no MediaPipe), same ROI + threshold + morphology pipeline.
#   - REMOVED: pyautogui (a key press on this server would do nothing for
#     the visitor — it doesn't run on their machine).
#   - REMOVED: tkinter UI, cv2.imshow windows, cv2.VideoCapture(0)
#     (the server has no access to the visitor's webcam directly).
#   - ADDED: a streamlit-webrtc VideoProcessor. This is what actually asks
#     the *visitor's browser* for camera permission and streams their frames
#     here for processing — the correct pattern for a shareable link.
#   - ADDED: instead of pressing a key, each recognized gesture is queued as
#     an "action" (prev / next / start) that the Streamlit frontend (app.py)
#     reads and uses to move through the uploaded slide deck.

import threading
import time

import av
import cv2
import numpy as np
from streamlit_webrtc import VideoProcessorBase

# === Settings (same values as the original script) ===
COOLDOWN_SECONDS = 1.0
ROI = (100, 100, 400, 400)  # x1, y1, x2, y2 — same box the user shows their hand in


# ---------- Finger counting (unchanged core logic from the original script) ----------
def count_fingers(thresh: np.ndarray) -> int:
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return -1

    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    if area < 2000:
        return -1

    hull_idx = cv2.convexHull(cnt, returnPoints=False)
    if hull_idx is None or len(hull_idx) < 3:
        return 0

    # convexityDefects requires indices in increasing order
    hull_idx = np.sort(hull_idx, axis=0)

    defects = cv2.convexityDefects(cnt, hull_idx)
    if defects is None:
        return 0

    defects = defects.reshape(-1, 4)

    count = 0
    for s, e, f, d in defects:
        start = tuple(cnt[s][0])
        end = tuple(cnt[e][0])
        far = tuple(cnt[f][0])

        a = np.linalg.norm(np.array(end) - np.array(start))
        b = np.linalg.norm(np.array(far) - np.array(start))
        c = np.linalg.norm(np.array(end) - np.array(far))

        if b <= 1e-5 or c <= 1e-5:
            continue

        cos_val = (b * b + c * c - a * a) / (2.0 * b * c)
        cos_val = float(np.clip(cos_val, -1.0, 1.0))
        angle = np.degrees(np.arccos(cos_val))

        if angle <= 95 and d > 1000:
            count += 1

    return min(count + 1, 5)


def _preprocess(roi: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (21, 21), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    thresh = cv2.erode(thresh, np.ones((3, 3), np.uint8), iterations=1)
    thresh = cv2.dilate(thresh, np.ones((3, 3), np.uint8), iterations=2)
    return thresh


def _action_for(fingers: int):
    if fingers == 0:
        return "prev", "Fist -> Previous Slide"
    if fingers == 5:
        return "next", "Open Palm -> Next Slide"
    if fingers == 1:
        return "start", "One Finger -> Start Slideshow"
    return None, None


class GestureProcessor(VideoProcessorBase):
    """
    Runs once per video frame received from the visitor's browser.
    Thread-safe: recv() runs on a streamlit-webrtc worker thread, while
    app.py reads results from the main Streamlit thread via get_action().
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._pending_action = None
        self._last_action_time = 0.0
        self.last_fingers = -1
        self.status_text = "Idle..."

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1)

        x1, y1, x2, y2 = ROI
        roi = img[y1:y2, x1:x2]
        thresh = _preprocess(roi)
        fingers = count_fingers(thresh)

        now = time.time()
        with self.lock:
            self.last_fingers = fingers
            if fingers == -1:
                self.status_text = "No hand detected..."
            else:
                action, label = _action_for(fingers)
                if action and (now - self._last_action_time) >= COOLDOWN_SECONDS:
                    self._pending_action = action
                    self._last_action_time = now
                    self.status_text = label
                elif action is None:
                    self.status_text = "Show a clear gesture..."

        # Draw the same overlays the desktop version showed, but onto the
        # frame that gets streamed back to the visitor's browser.
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, self.status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        if fingers >= 0:
            cv2.putText(img, f"Fingers: {fingers}", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

        return av.VideoFrame.from_ndarray(img, format="bgr24")

    def get_action(self):
        """Called from app.py's polling loop. Returns and clears the latest gesture action, if any."""
        with self.lock:
            action, self._pending_action = self._pending_action, None
            return action

    def get_status(self):
        with self.lock:
            return self.status_text, self.last_fingers