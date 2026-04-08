"""
Hydra AI Surveillance — Flask Web Backend
==========================================
Serves the dashboard, streams live video, and pushes real-time alerts via SSE.

Run:
    pip install flask opencv-python ultralytics numpy
    python app/app.py
"""

import cv2
import json
import os
import sys
import time
import threading
import queue
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, Response, render_template, jsonify,
    request, send_from_directory, stream_with_context
)

# ─── project root so we can import surveillance modules ───────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

app = Flask(__name__, template_folder="templates", static_folder="static")

# ─── Global state ─────────────────────────────────────────────────────────────
camera_state = {
    "running": False,
    "admin_mode": False,
    "conf": 0.20,
    "cam_id": "CAM1",
    "source": 0,          # 0 = webcam, str = video file / mobile URL
    "mobile_url": None,
    "mode": "webcam",     # webcam | video | mobile | demo
}

alert_queue: queue.Queue = queue.Queue(maxsize=200)  # SSE alert events
frame_lock = threading.Lock()
latest_frame: bytes = b""
camera_thread: threading.Thread | None = None
stop_event = threading.Event()

# ─── Surveillance engine (lazy-import so Flask starts even without GPU) ───────
def get_system():
    try:
        from surveillance.detector import SurveillanceSystem
        return SurveillanceSystem(
            admin_mode=camera_state["admin_mode"],
            conf_threshold=camera_state["conf"],
            cam_id=camera_state["cam_id"],
        )
    except ImportError:
        return None


# ─── Camera worker ────────────────────────────────────────────────────────────
def camera_worker():
    global latest_frame
    system = get_system()
    source = camera_state["source"]
    mobile_url = camera_state["mobile_url"]

    # Choose capture source
    if mobile_url:
        cap_source = f"{mobile_url}/video"
    elif camera_state["mode"] == "demo":
        # Use first video file found in project root
        for ext in ("*.mp4", "*.avi", "*.mov"):
            files = list(ROOT.glob(ext))
            if files:
                cap_source = str(files[0])
                break
        else:
            cap_source = 0
    else:
        cap_source = source

    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        _push_alert("error", "Cannot open camera/video source", "SYSTEM")
        return

    _push_alert("info", f"Camera started — source: {cap_source}", camera_state["cam_id"])

    fail_count = 0
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            fail_count += 1
            if fail_count > 50:
                _push_alert("error", "Camera feed lost after 50 retries", camera_state["cam_id"])
                break
            time.sleep(0.05)
            continue
        fail_count = 0

        # --- Run AI detections if system loaded ---
        if system:
            try:
                person_boxes, weapon_boxes, all_boxes = system._detect_yolo(frame) \
                    if system._model else system._detect_hog(frame)
                fire_boxes, fire_ratio = system.fire_detector.detect(frame)
                stats = system.threat_analyzer.analyze(person_boxes, weapon_boxes, fire_boxes)
                frame = system.face_module.process(frame, system.admin_mode)
                frame = system.hud.draw(frame, stats, system.face_module.face_count, 30, all_boxes)

                # Push alerts for detected threats
                if stats.get("threat_level", 0) >= 2:
                    threats = []
                    if weapon_boxes:
                        threats.append(f"Weapon detected ({len(weapon_boxes)})")
                    if fire_boxes:
                        threats.append("🔥 Fire detected")
                    if stats.get("robbery"):
                        threats.append("⚠️ Robbery behavior")
                    if stats.get("fighting"):
                        threats.append("⚠️ Fighting detected")
                    if threats:
                        _push_alert("threat", " | ".join(threats), camera_state["cam_id"])

                # Push person count periodically
                if hasattr(camera_worker, "_last_count_time"):
                    if time.time() - camera_worker._last_count_time > 5:
                        _push_alert("info",
                            f"Persons: {len(person_boxes)} | Faces: {system.face_module.face_count}",
                            camera_state["cam_id"])
                        camera_worker._last_count_time = time.time()
                else:
                    camera_worker._last_count_time = time.time()

            except Exception as e:
                # AI failed — still stream raw frame
                pass

        # Encode frame to JPEG for streaming
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with frame_lock:
            latest_frame = buf.tobytes()

    cap.release()
    camera_state["running"] = False
    _push_alert("info", "Camera stopped", camera_state["cam_id"])


def _push_alert(level: str, message: str, cam_id: str):
    """Push an alert event into the SSE queue."""
    event = {
        "level": level,
        "message": message,
        "cam": cam_id,
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    try:
        alert_queue.put_nowait(event)
    except queue.Full:
        alert_queue.get_nowait()   # drop oldest
        alert_queue.put_nowait(event)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG stream for the live feed <img> tag."""
    def generate():
        while True:
            with frame_lock:
                frame = latest_frame
            if frame:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.04)   # ~25 fps cap

    return Response(generate(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/alerts_stream")
def alerts_stream():
    """Server-Sent Events stream for real-time alerts."""
    def event_stream():
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            try:
                event = alert_queue.get(timeout=15)
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"   # keep-alive

    return Response(stream_with_context(event_stream()),
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/start", methods=["POST"])
def api_start():
    global camera_thread, stop_event
    if camera_state["running"]:
        return jsonify({"status": "already_running"})

    data = request.get_json(silent=True) or {}
    camera_state["admin_mode"] = data.get("admin", False)
    camera_state["conf"] = float(data.get("conf", 0.20))
    camera_state["cam_id"] = data.get("cam_id", "CAM1")
    camera_state["mode"] = data.get("mode", "webcam")
    camera_state["mobile_url"] = data.get("mobile_url") or None

    if camera_state["mode"] == "video" and data.get("video_path"):
        camera_state["source"] = data["video_path"]
    else:
        camera_state["source"] = int(data.get("camera_index", 0))

    stop_event = threading.Event()
    camera_state["running"] = True
    camera_thread = threading.Thread(target=camera_worker, daemon=True)
    camera_thread.start()
    return jsonify({"status": "started", "config": camera_state})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_event.set()
    camera_state["running"] = False
    return jsonify({"status": "stopped"})


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": camera_state["running"],
        "mode": camera_state["mode"],
        "cam_id": camera_state["cam_id"],
        "admin_mode": camera_state["admin_mode"],
        "conf": camera_state["conf"],
    })


@app.route("/api/clear_alerts", methods=["POST"])
def api_clear_alerts():
    while not alert_queue.empty():
        try:
            alert_queue.get_nowait()
        except queue.Empty:
            break
    return jsonify({"status": "cleared"})


# Serve static assets (videos, images) from project root
@app.route("/assets/<path:filename>")
def serve_asset(filename):
    return send_from_directory(str(ROOT), filename)


if __name__ == "__main__":
    print("=" * 60)
    print("  HYDRA AI SURVEILLANCE — Web Dashboard")
    print("  Open: http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
