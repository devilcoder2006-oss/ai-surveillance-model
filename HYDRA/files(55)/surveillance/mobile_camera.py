"""
Mobile Camera Support — Team Hydra (FIXED - No Lag, No Freeze)
===============================================================
Fixes:
  - Background thread reads frames continuously at full speed
  - Buffer always flushed — always shows LATEST frame
  - No queue buildup — old frames discarded immediately
  - Auto reconnect if stream drops
  - Frame resized to 640x480 for smooth detection
"""

import cv2
import numpy as np
import time
import threading
import urllib.request

TARGET_W = 640
TARGET_H = 480


class MobileCameraSource:
    def __init__(self, base_url: str):
        self.base_url      = base_url.rstrip("/")
        self.stream_url    = None
        self._connected    = False
        self._jpeg_mode    = False

        # Only store the LATEST frame — old frames discarded
        self._latest_frame = None
        self._lock         = threading.Lock()
        self._running      = False
        self._cap          = None

    # ── Connect ───────────────────────────────────────────
    def connect(self) -> bool:
        print(f"\n[MOBILE] Connecting to: {self.base_url}")
        print(f"[MOBILE] Phone and PC must be on SAME WiFi!\n")

        candidates = [
            f"{self.base_url}/video",
            f"{self.base_url}/mjpegfeed",
            f"{self.base_url}/stream",
            f"{self.base_url}:8080/video",
            self.base_url,
        ]

        for url in candidates:
            print(f"[MOBILE] Trying: {url}")
            cap = cv2.VideoCapture(url)

            # Key settings to reduce lag
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # smallest buffer possible
            cap.set(cv2.CAP_PROP_FPS, 30)

            deadline = time.time() + 5.0
            while time.time() < deadline:
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    oh, ow = frame.shape[:2]
                    self._cap        = cap
                    self.stream_url  = url
                    self._connected  = True
                    print(f"[MOBILE] ✅ Connected: {url}")
                    print(f"[MOBILE] Phone res: {ow}x{oh} → resized to {TARGET_W}x{TARGET_H}")
                    self._start_reader()
                    return True
            cap.release()

        # JPEG fallback
        jpeg_url = f"{self.base_url}/shot.jpg"
        print(f"[MOBILE] Trying JPEG fallback: {jpeg_url}")
        try:
            data  = urllib.request.urlopen(jpeg_url, timeout=3).read()
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                self.stream_url = jpeg_url
                self._connected = True
                self._jpeg_mode = True
                print(f"[MOBILE] ✅ JPEG fallback connected (lower FPS)")
                self._start_reader()
                return True
        except Exception:
            pass

        print(f"\n[MOBILE] ❌ Failed. Check:")
        print(f"  1. IP Webcam app is running on phone")
        print(f"  2. Phone and PC on SAME WiFi")
        print(f"  3. Open {self.base_url}/video in PC browser")
        return False

    # ── Background reader — runs at full speed ────────────
    def _start_reader(self):
        self._running = True
        t = threading.Thread(target=self._reader_loop, daemon=True)
        t.start()

    def _reader_loop(self):
        """
        Reads frames as fast as possible.
        Only keeps the LATEST frame — discards all older ones.
        This prevents buffer buildup which causes lag and freezing.
        """
        fail_count = 0

        while self._running:
            if self._jpeg_mode:
                ret, frame = self._read_jpeg()
            else:
                ret, frame = self._read_stream()

            if ret and frame is not None:
                # Resize immediately — smaller = faster processing later
                resized = cv2.resize(frame, (TARGET_W, TARGET_H))
                with self._lock:
                    self._latest_frame = resized
                fail_count = 0
            else:
                fail_count += 1
                if fail_count > 20:
                    print("[MOBILE] Stream lost — reconnecting...")
                    self._reconnect()
                    fail_count = 0
                time.sleep(0.01)

    def _read_stream(self):
        if self._cap is None:
            return False, None
        # CRITICAL: grab() decodes without storing — flushes buffer
        # Then retrieve() gets the actual latest frame
        # This combo gives us the most recent frame with no lag
        self._cap.grab()
        self._cap.grab()   # grab twice to skip any buffered frame
        ret, frame = self._cap.retrieve()
        return ret, frame

    def _read_jpeg(self):
        try:
            data  = urllib.request.urlopen(self.stream_url, timeout=1.5).read()
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            return (True, frame) if frame is not None else (False, None)
        except Exception:
            return False, None

    def _reconnect(self):
        if self._cap:
            self._cap.release()
            self._cap = None
        time.sleep(2.0)
        try:
            cap = cv2.VideoCapture(self.stream_url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                ret, frame = cap.read()
                if ret and frame is not None:
                    self._cap = cap
                    print("[MOBILE] ✅ Reconnected!")
                    return
            cap.release()
        except Exception as e:
            print(f"[MOBILE] Reconnect failed: {e}")

    # ── Public interface (same as cv2.VideoCapture) ───────
    def read(self):
        """Always returns the LATEST frame — never a stale/buffered one."""
        with self._lock:
            frame = self._latest_frame
        if frame is not None:
            return True, frame.copy()
        return False, None

    def get(self, prop_id):
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:  return float(TARGET_W)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT: return float(TARGET_H)
        if prop_id == cv2.CAP_PROP_FPS:          return 30.0
        return self._cap.get(prop_id) if self._cap else 0.0

    def isOpened(self):   return self._connected
    def set(self, p, v):
        if self._cap: self._cap.set(p, v)

    def release(self):
        self._running = False
        if self._cap:
            self._cap.release()
        self._connected = False


# ─────────────────────────────────────────────────────────
def get_camera_source(source, mobile_url: str = None):
    if mobile_url:
        cam = MobileCameraSource(mobile_url)
        if cam.connect():
            return cam
        print("[MOBILE] Falling back to webcam index 0")
        return cv2.VideoCapture(0)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open: {source}")
    return cap
