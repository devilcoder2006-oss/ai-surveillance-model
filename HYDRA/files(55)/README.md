# Hydra AI Surveillance — Web Dashboard
### Team Code Warriors (Nikhil, Abhishek, Jatin, Dheeraj)

## Quick Start

### Windows
```
Double-click: run_web.bat
Open browser: http://localhost:5000
```

### Mac / Linux
```bash
chmod +x run_web.sh
./run_web.sh
# Open browser: http://localhost:5000
```

### Manual
```bash
pip install flask opencv-python ultralytics numpy
python app/app.py
```

---

## Project Structure

```
hydra_surveillance/
│
├── app/
│   ├── app.py               ← Flask backend (video stream, alerts SSE, REST API)
│   └── templates/
│       └── dashboard.html   ← Full website + live dashboard UI
│
├── surveillance/            ← Your existing AI modules (unchanged)
│   ├── detector.py
│   ├── cross_camera.py
│   ├── trainer.py
│   └── demo.py
│
├── main.py                  ← Original CLI entrypoint (still works)
├── run_web.bat              ← Windows launcher
├── run_web.sh               ← Mac/Linux launcher
├── run.bat                  ← Original webcam launcher
├── run_demo.bat
├── run_mobile.bat
├── V1.mp4, V2.mp4           ← Demo videos
├── Img1.jpeg, T1A.jpeg ...  ← Images
└── requirements.txt
```

---

## Flask API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard web page |
| GET | `/video_feed` | MJPEG live camera stream |
| GET | `/alerts_stream` | Server-Sent Events (real-time alerts) |
| POST | `/api/start` | Start camera with config |
| POST | `/api/stop` | Stop camera |
| GET | `/api/status` | Current system status |
| POST | `/api/clear_alerts` | Clear alert queue |
| GET | `/assets/<file>` | Serve images/videos |

### Start camera payload
```json
{
  "mode": "webcam",           // webcam | video | mobile | demo
  "conf": 0.20,               // confidence threshold
  "admin": false,             // true = show faces (admin only)
  "cam_id": "CAM1",           // camera label
  "mobile_url": null,         // e.g. "http://192.168.1.5:8080"
  "video_path": null          // e.g. "path/to/video.mp4"
}
```

---

## Dashboard Features

- **Live MJPEG video stream** from webcam / phone / video file
- **Real-time alert sidebar** via Server-Sent Events (no page refresh needed)
- **Start/Stop controls** with mode selector, confidence slider, admin toggle
- **Stats strip** — alert count, threat count, uptime, camera ID
- **SMS toast** popup on weapon/threat detection
- **All original sections preserved** — Features, How It Works, Presentations, Demo videos, Team

---

## Notes

- The surveillance AI modules (`surveillance/`) are imported automatically.
  If they are missing or YOLO model is not found, the system falls back to HOG
  person detection and still streams video.
- Place `yolov8n.pt` / `yolov8s.pt` in the project root for full AI detection.
- SMS alerts require Twilio credentials in `surveillance/` config.
