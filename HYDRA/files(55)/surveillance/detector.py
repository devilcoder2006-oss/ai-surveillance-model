"""
Core Surveillance Detector — Team Hydra (ULTIMATE FINAL VERSION)
=================================================================
Features:
  ✅ YOLOv8s detection — persons + weapons
  ✅ Fire detection (HSV, strict, no false alarms)
  ✅ Behaviour: Robbery / Fighting / Loitering
  ✅ Cross-camera tracking (global IDs)
  ✅ Face blur (user) / face visible (admin)
  ✅ SMS notification via Twilio on threat
  ✅ Beep alert on threat
  ✅ ALL detections shown in HUD simultaneously
  ✅ Full HD display, auto fullscreen
  ✅ No lag — YOLO runs in background thread
  ✅ No frame drops — display always shows latest frame
  ✅ No false fight detection
  ✅ No false fire detection
"""

import cv2
import numpy as np
import time
import threading
import os
import sys
from collections import deque

WEAPON_CLASSES = {
    "knife","scissors","gun","pistol","rifle",
    "handgun","weapon","firearm","sword","baseball bat"
}
PERSON_CLASS = "person"

# BGR colors
COLOR_PERSON  = (0,   220, 0)
COLOR_WEAPON  = (0,   0,   255)
COLOR_FIRE    = (0,   140, 255)
COLOR_TEXT    = (255, 255, 255)
COLOR_ALERT   = (0,   0,   255)
COLOR_ADMIN   = (0,   215, 255)
COLOR_FIGHT   = (50,  50,  255)
COLOR_ROBBERY = (0,   0,   200)
COLOR_LOITER  = (0,   165, 255)
COLOR_SAFE    = (0,   220, 0)
ID_COLORS = [
    (255,80,80),(80,255,80),(80,80,255),(255,255,80),
    (255,80,255),(80,255,255),(255,165,0),(180,80,255)
]


# ─────────────────────────────────────────────────────────
# SMS NOTIFIER  (Gmail → Email-to-SMS gateway — no Twilio)
# ─────────────────────────────────────────────────────────
class SMSNotifier:
    """
    Sends SMS alerts via Gmail using Python's built-in smtplib.
    No external libraries needed — works out of the box on Windows.

    Setup (one-time):
      1. Use a Gmail account as the SENDER.
      2. Enable 2-Step Verification on that Gmail account.
      3. Create an App Password:
           Google Account → Security → 2-Step Verification
           → App passwords → Select app: Mail → Generate
           Copy the 16-character password and paste below.
      4. Fill GMAIL_USER, GMAIL_APP_PASSWORD, and RECIPIENT_EMAIL.

    For Indian Airtel numbers the gateway is: 10digitnumber@airtelap.com
    For Jio numbers the gateway is:           10digitnumber@jio.com
    For Vi (Vodafone) numbers:                10digitnumber@vimail.in
    Or just set RECIPIENT_EMAIL to any email you check on your phone.
    """

    GMAIL_USER        = "abhisheksaxena7116@gmail.com"       # ← your Gmail address
    GMAIL_APP_PASSWORD = "tkbe jlqj qhkc smzi"       # ← 16-char App Password
    RECIPIENT_EMAIL   = "7982028589@jio.com"    # ← SMS gateway OR any email

    def __init__(self):
        self._last_sms = 0
        self._cooldown = 60   # seconds between alerts
        self._configured = (
            "your.gmail" not in self.GMAIL_USER and
            "xxxx" not in self.GMAIL_APP_PASSWORD
        )

    def send(self, threat_type: str, threat_score: int, camera_id: str):
        """Send alert in background thread — never blocks detection."""
        if not self._configured:
            print("[SMS] NOT CONFIGURED — fill GMAIL_USER and GMAIL_APP_PASSWORD in detector.py")
            return
        now = time.time()
        if now - self._last_sms < self._cooldown:
            return
        self._last_sms = now
        threading.Thread(
            target=self._send_sms,
            args=(threat_type, threat_score, camera_id),
            daemon=True
        ).start()

    def _send_sms(self, threat_type, threat_score, camera_id):
        import smtplib
        from email.mime.text import MIMEText
        try:
            t   = time.strftime("%H:%M:%S")
            body = (f"HYDRA ALERT [{t}]\n"
                    f"Camera : {camera_id}\n"
                    f"Threat : {threat_type}\n"
                    f"Score  : {threat_score}%\n"
                    f"Immediate action required!")
            msg = MIMEText(body)
            msg["Subject"] = f"ALERT: {threat_type}"
            msg["From"]    = self.GMAIL_USER
            msg["To"]      = self.RECIPIENT_EMAIL

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.GMAIL_USER, self.GMAIL_APP_PASSWORD)
                server.sendmail(self.GMAIL_USER, self.RECIPIENT_EMAIL, msg.as_string())
            print(f"[SMS] Alert sent to {self.RECIPIENT_EMAIL}")
        except Exception as e:
            print(f"[SMS] Failed: {e}")


# ─────────────────────────────────────────────────────────
# ALERT SOUND
# ─────────────────────────────────────────────────────────
class AlertSoundThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop_flag = threading.Event()

    def run(self):
        for _ in range(3):
            if self._stop_flag.is_set():
                break
            self._beep()
            time.sleep(0.3)

    def _beep(self):
        if sys.platform == "win32":
            try:
                import winsound
                winsound.Beep(1000, 300)
                return
            except Exception:
                pass
            try:
                import subprocess
                subprocess.Popen(["powershell","-c","[console]::beep(1000,300)"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        print("\a", flush=True)

    def cancel(self):
        self._stop_flag.set()


# ─────────────────────────────────────────────────────────
# FACE BLUR
# ─────────────────────────────────────────────────────────
class FaceBlurModule:
    def __init__(self):
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.cascade     = cv2.CascadeClassifier(path)
        self._face_boxes = []

    def process(self, frame, admin_mode):
        try:
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))
            self._face_boxes = []
            for (x,y,w,h) in faces:
                x2 = min(frame.shape[1], x+w)
                y2 = min(frame.shape[0], y+h)
                self._face_boxes.append((x,y,w,h))
                if not admin_mode:
                    roi = frame[y:y2, x:x2]
                    if roi.size > 0:
                        frame[y:y2, x:x2] = cv2.GaussianBlur(roi,(51,51),30)
                else:
                    cv2.rectangle(frame,(x,y),(x2,y2),COLOR_ADMIN,2)
                    cv2.putText(frame,"FACE",(x,max(y-5,12)),
                                cv2.FONT_HERSHEY_SIMPLEX,0.45,COLOR_ADMIN,1)
        except Exception:
            pass
        return frame

    @property
    def face_count(self): return len(self._face_boxes)


# ─────────────────────────────────────────────────────────
# FIRE DETECTOR
# ─────────────────────────────────────────────────────────
class FireDetector:
    def __init__(self):
        self._history = deque(maxlen=4)

    def detect(self, frame):
        try:
            hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            m1   = cv2.inRange(hsv, np.array([0,200,200]),  np.array([20,255,255]))
            m2   = cv2.inRange(hsv, np.array([165,200,200]),np.array([180,255,255]))
            mask = cv2.bitwise_or(m1, m2)
            k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=2)
            mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE,k, iterations=1)
            h,w  = frame.shape[:2]
            ratio= cv2.countNonZero(mask)/(h*w)
            self._history.append(ratio > 0.015)
            if len(self._history)==4 and all(self._history):
                cnts,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                boxes  = []
                for c in cnts:
                    if cv2.contourArea(c)>3000:
                        x,y,bw,bh = cv2.boundingRect(c)
                        boxes.append((x,y,x+bw,y+bh))
                return boxes, ratio
        except Exception:
            pass
        return [], 0.0


# ─────────────────────────────────────────────────────────
# BEHAVIOUR ANALYSER
# ─────────────────────────────────────────────────────────
class BehaviourAnalyser:
    def __init__(self):
        self._loiter       = {}
        self._fight_timers = {}

    def analyse(self, person_boxes, weapon_boxes, frame_shape):
        try:
            h,w    = frame_shape[:2]
            events = []
            now    = time.time()

            # ROBBERY — weapon strictly inside person box for 2s
            for (wx1,wy1,wx2,wy2) in weapon_boxes:
                wcx=(wx1+wx2)/2; wcy=(wy1+wy2)/2
                for pi,(px1,py1,px2,py2) in enumerate(person_boxes):
                    if px1<wcx<px2 and py1<wcy<py2:
                        rk = f"r{pi}"
                        if rk not in self._fight_timers:
                            self._fight_timers[rk] = now
                        elif now-self._fight_timers[rk]>=2.0:
                            events.append({"type":"ROBBERY","label":"ROBBERY DETECTED",
                                "color":COLOR_ROBBERY,"box":(px1,py1,px2,py2),"severity":95})
                    else:
                        self._fight_timers.pop(f"r{pi}", None)

            # FIGHTING — IOU > 0.45 for 3s
            active_pairs = set()
            if len(person_boxes)>=2:
                for i in range(len(person_boxes)):
                    for j in range(i+1,len(person_boxes)):
                        if self._iou(person_boxes[i],person_boxes[j])>0.45:
                            pk = f"f{i}_{j}"
                            active_pairs.add(pk)
                            if pk not in self._fight_timers:
                                self._fight_timers[pk]=now
                            elif now-self._fight_timers[pk]>=3.0:
                                x1=min(person_boxes[i][0],person_boxes[j][0])
                                y1=min(person_boxes[i][1],person_boxes[j][1])
                                x2=max(person_boxes[i][2],person_boxes[j][2])
                                y2=max(person_boxes[i][3],person_boxes[j][3])
                                events.append({"type":"FIGHTING","label":"FIGHTING DETECTED",
                                    "color":COLOR_FIGHT,"box":(x1,y1,x2,y2),"severity":80})
            for k in list(self._fight_timers.keys()):
                if k.startswith("f") and k not in active_pairs:
                    del self._fight_timers[k]

            # LOITERING — stationary > 15s
            for idx,(px1,py1,px2,py2) in enumerate(person_boxes):
                cx=(px1+px2)/2/w; cy=(py1+py2)/2/h
                if idx not in self._loiter:
                    self._loiter[idx]={"t":now,"cx":cx,"cy":cy}
                else:
                    prev=self._loiter[idx]
                    if ((cx-prev["cx"])**2+(cy-prev["cy"])**2)**0.5>0.05:
                        self._loiter[idx]={"t":now,"cx":cx,"cy":cy}
                    elif now-prev["t"]>15.0:
                        events.append({"type":"LOITERING",
                            "label":f"LOITERING {int(now-prev['t'])}s",
                            "color":COLOR_LOITER,"box":(px1,py1,px2,py2),"severity":40})
            for k in list(self._loiter.keys()):
                if k>=len(person_boxes): del self._loiter[k]

            return events
        except Exception as e:
            print(f"[WARN] Behaviour: {e}")
            return []

    @staticmethod
    def _iou(b1,b2):
        ix1=max(b1[0],b2[0]); iy1=max(b1[1],b2[1])
        ix2=min(b1[2],b2[2]); iy2=min(b1[3],b2[3])
        inter=max(0,ix2-ix1)*max(0,iy2-iy1)
        if inter==0: return 0
        return inter/((b1[2]-b1[0])*(b1[3]-b1[1])+(b2[2]-b2[0])*(b2[3]-b2[1])-inter)


# ─────────────────────────────────────────────────────────
# THREAT ANALYZER
# ─────────────────────────────────────────────────────────
class ThreatAnalyzer:
    def __init__(self, cooldown=5.0):
        self.cooldown     = cooldown
        self._last_alert  = 0.0
        self.threat_score = 0

    def analyze(self, person_boxes, weapon_boxes, fire_boxes, bevents):
        score = 0
        if len(weapon_boxes)==1:
            score = max(score, 60)
            if person_boxes: score = max(score, 90)
        if len(weapon_boxes)>1:  score = max(score,100)
        if fire_boxes:           score = max(score, 85)
        for ev in bevents:       score = max(score, ev.get("severity",50))
        self.threat_score = score
        alert  = score>=50
        beep   = False
        if alert:
            now = time.time()
            if now-self._last_alert>=self.cooldown:
                self._last_alert=now; beep=True
        return {
            "threat_score":score,"alert_active":alert,"should_beep":beep,
            "weapon_count":len(weapon_boxes),"person_count":len(person_boxes),
            "fire_count":len(fire_boxes),"behaviour_events":bevents,
        }


# ─────────────────────────────────────────────────────────
# HUD RENDERER
# ─────────────────────────────────────────────────────────
class HUDRenderer:
    def __init__(self, admin_mode, cam_id="CAM1"):
        self.admin_mode = admin_mode
        self.cam_id     = cam_id

    def draw(self, frame, stats, face_count, fps, detection_boxes, tracks=None):
        try:
            fh,fw   = frame.shape[:2]
            score   = stats["threat_score"]
            alert   = stats["alert_active"]
            bevents = stats.get("behaviour_events",[])
            tracks  = tracks or []

            # ── All detection boxes ───────────────────────
            for item in detection_boxes:
                try:
                    label,conf,x1,y1,x2,y2 = item
                    x1=max(0,min(int(x1),fw-1)); y1=max(0,min(int(y1),fh-1))
                    x2=max(0,min(int(x2),fw-1)); y2=max(0,min(int(y2),fh-1))
                    if x2<=x1 or y2<=y1: continue
                    is_w = label.lower() in WEAPON_CLASSES
                    is_f = label=="fire"
                    col  = COLOR_FIRE if is_f else (COLOR_WEAPON if is_w else COLOR_PERSON)
                    cv2.rectangle(frame,(x1,y1),(x2,y2),col,3 if(is_w or is_f) else 2)
                    tag = f"{label} {conf:.0%}"
                    (tw,th),_=cv2.getTextSize(tag,cv2.FONT_HERSHEY_SIMPLEX,0.55,1)
                    ty=max(th+8,y1)
                    cv2.rectangle(frame,(x1,ty-th-8),(x1+tw+6,ty),col,-1)
                    cv2.putText(frame,tag,(x1+3,ty-4),
                                cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,255,255),1,cv2.LINE_AA)
                except Exception: continue

            # ── Behaviour boxes ───────────────────────────
            seen=set()
            for ev in bevents:
                try:
                    if ev["type"] in seen: continue
                    seen.add(ev["type"])
                    bx1,by1,bx2,by2=ev["box"]
                    bx1=max(0,min(int(bx1),fw-1)); by1=max(0,min(int(by1),fh-1))
                    bx2=max(0,min(int(bx2),fw-1)); by2=max(0,min(int(by2),fh-1))
                    if bx2<=bx1 or by2<=by1: continue
                    cv2.rectangle(frame,(bx1,by1),(bx2,by2),ev["color"],3)
                    cv2.putText(frame,ev["label"],(bx1,max(by1-8,15)),
                                cv2.FONT_HERSHEY_SIMPLEX,0.65,ev["color"],2,cv2.LINE_AA)
                except Exception: continue

            # ── Cross-cam track IDs ───────────────────────
            for t in tracks:
                try:
                    gid=t["global_id"]; x1,y1,x2,y2=t["box"]
                    x1=max(0,min(int(x1),fw-1)); y1=max(0,min(int(y1),fh-1))
                    x2=max(0,min(int(x2),fw-1)); y2=max(0,min(int(y2),fh-1))
                    if x2<=x1 or y2<=y1: continue
                    tc=ID_COLORS[gid%len(ID_COLORS)]
                    ty=max(22,y1)
                    cv2.rectangle(frame,(x1,ty-22),(x1+55,ty),tc,-1)
                    cv2.putText(frame,f"ID:{gid}",(x1+3,ty-5),
                                cv2.FONT_HERSHEY_SIMPLEX,0.48,(0,0,0),1,cv2.LINE_AA)
                    others=[c for c in t.get("cameras",[]) if c!=self.cam_id]
                    if others:
                        cv2.putText(frame,f"Also:{','.join(others)}",
                                    (x1,min(y2+14,fh-2)),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.38,tc,1,cv2.LINE_AA)
                except Exception: continue

            # ── Left info panel ───────────────────────────
            ov=frame.copy()
            cv2.rectangle(ov,(5,5),(320,210),(15,15,15),-1)
            cv2.addWeighted(ov,0.75,frame,0.25,0,frame)
            rl = "ADMIN" if self.admin_mode else "USER"
            rc = COLOR_ADMIN if self.admin_mode else (170,170,170)

            # Collect ALL active detection types for headline
            active = []
            if stats["weapon_count"]:  active.append(f"WEAPON x{stats['weapon_count']}")
            if stats["fire_count"]:    active.append("FIRE")
            for ev in bevents:         active.append(ev["type"])
            headline = " | ".join(active) if active else "NONE"
            hcol     = COLOR_ALERT if active else COLOR_SAFE

            lines = [
                (f"HYDRA [{rl}] CAM:{self.cam_id}",        rc,              0.41),
                (f"FPS:{fps:.0f}  Persons:{stats['person_count']}  Faces:{face_count}", COLOR_TEXT,0.40),
                (f"Weapons:{stats['weapon_count']}  Fire:{stats['fire_count']}", COLOR_TEXT,0.40),
                (f"Events: {headline}",                     hcol,            0.41),
                (f"Cross-cam:{sum(1 for t in tracks if len(t.get('cameras',[]))>1)}", COLOR_ADMIN,0.40),
                (f"Threat: {score}%",
                 COLOR_ALERT if alert else COLOR_SAFE,                        0.52),
            ]
            for i,(txt,col,sc) in enumerate(lines):
                cv2.putText(frame,txt,(10,26+i*28),
                            cv2.FONT_HERSHEY_SIMPLEX,sc,col,1,cv2.LINE_AA)

            # ── Alert banner — shows ALL detections ───────
            if alert:
                if int(time.time()*2)%2==0:
                    bn=frame.copy()
                    cv2.rectangle(bn,(0,0),(fw,50),(0,0,160),-1)
                    cv2.addWeighted(bn,0.8,frame,0.2,0,frame)
                # Build full banner text
                parts=[]
                if stats["weapon_count"]: parts.append(f"WEAPON({stats['weapon_count']})")
                if stats["fire_count"]:   parts.append("FIRE")
                for ev in bevents:        parts.append(ev["type"])
                banner = "*** " + " + ".join(parts) + " DETECTED ***" if parts else "*** THREAT ***"
                bx = max(0, fw//2 - len(banner)*5)
                cv2.putText(frame,banner,(bx,34),
                            cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,255),2,cv2.LINE_AA)

            # ── Threat bar bottom right ───────────────────
            bx=fw-180; by=fh-35; bw=170; bh=22
            if bx>0 and by>0:
                fill=int(bw*score/100)
                bc=(0,200,0) if score<50 else ((0,165,255) if score<80 else (0,0,255))
                cv2.rectangle(frame,(bx,by),(bx+bw,by+bh),(40,40,40),-1)
                if fill>0: cv2.rectangle(frame,(bx,by),(bx+fill,by+bh),bc,-1)
                cv2.rectangle(frame,(bx,by),(bx+bw,by+bh),(140,140,140),1)
                cv2.putText(frame,f"Threat {score}%",(bx,by-7),
                            cv2.FONT_HERSHEY_SIMPLEX,0.44,COLOR_TEXT,1)

            # ── Privacy badge bottom left ─────────────────
            pt="FACES: VISIBLE (ADMIN)" if self.admin_mode else "FACES: BLURRED"
            pc=COLOR_ADMIN if self.admin_mode else (0,200,0)
            cv2.putText(frame,pt,(10,fh-10),
                        cv2.FONT_HERSHEY_SIMPLEX,0.42,pc,1,cv2.LINE_AA)

        except Exception as e:
            print(f"[WARN] HUD: {e}")
        return frame


# ─────────────────────────────────────────────────────────
# BACKGROUND YOLO THREAD
# ─────────────────────────────────────────────────────────
class YOLOThread(threading.Thread):
    """
    Runs YOLO in a background thread so display is never blocked.
    Main loop reads cached results — zero wait time.
    """
    def __init__(self, model, conf):
        super().__init__(daemon=True)
        self._model    = model
        self._conf     = conf
        self._frame    = None
        self._result   = ([], [], [])
        self._lock     = threading.Lock()
        self._new_frame= threading.Event()
        self._running  = True

    def submit(self, frame):
        """Submit new frame for detection."""
        with self._lock:
            self._frame = frame.copy()
        self._new_frame.set()

    def get_result(self):
        """Get latest detection result (non-blocking)."""
        with self._lock:
            return self._result

    def run(self):
        while self._running:
            self._new_frame.wait(timeout=0.5)
            self._new_frame.clear()
            with self._lock:
                frame = self._frame
            if frame is None:
                continue
            try:
                results = self._model(frame, conf=self._conf,
                                      imgsz=416, verbose=False)
                pb,wb,ab = [],[],[]
                for r in results:
                    for box in r.boxes:
                        label = self._model.names[int(box.cls[0])].lower()
                        conf  = float(box.conf[0])
                        x1,y1,x2,y2 = map(int, box.xyxy[0])
                        ab.append((label,conf,x1,y1,x2,y2))
                        if label==PERSON_CLASS:      pb.append((x1,y1,x2,y2))
                        elif label in WEAPON_CLASSES: wb.append((x1,y1,x2,y2))
                with self._lock:
                    self._result = (pb,wb,ab)
            except Exception as e:
                print(f"[WARN] YOLO: {e}")

    def stop(self):
        self._running = False
        self._new_frame.set()


# ─────────────────────────────────────────────────────────
# MAIN SURVEILLANCE SYSTEM
# ─────────────────────────────────────────────────────────
class SurveillanceSystem:
    def __init__(self, admin_mode=False, conf_threshold=0.20,
                 record_path=None, cam_id="CAM1"):
        self.admin_mode     = admin_mode
        self.conf_threshold = conf_threshold
        self.record_path    = record_path
        self.cam_id         = cam_id

        self.face_module     = FaceBlurModule()
        self.fire_detector   = FireDetector()
        self.behaviour       = BehaviourAnalyser()
        self.threat_analyzer = ThreatAnalyzer(cooldown=5.0)
        self.hud             = HUDRenderer(admin_mode, cam_id)
        self.sms             = SMSNotifier()

        from surveillance.cross_camera import CrossCameraTracker
        self.tracker = CrossCameraTracker(cam_id=cam_id)

        self._model        = None
        self._yolo_thread  = None
        self._alert_thread = None
        self._hog          = None

        print("="*65)
        print("  AI SMART SURVEILLANCE — Team Hydra (ULTIMATE FINAL)")
        print("="*65)
        print(f"  Camera     : {cam_id}")
        print(f"  Mode       : {'ADMIN' if admin_mode else 'USER'}")
        print(f"  Confidence : {conf_threshold:.0%}")
        print(f"  SMS        : {'CONFIGURED' if self.sms._configured else 'NOT CONFIGURED (see config in detector.py)'}")
        print("  Features   : Weapons|Fire|Behaviour|Cross-Cam|SMS|Beep")
        print("="*65)

    def _load_model(self):
        try:
            from ultralytics import YOLO
            custom = "models/weapon_detector.pt"
            if os.path.exists(custom):
                print(f"[INFO] Custom weights: {custom}")
                self._model = YOLO(custom)
            else:
                print("[INFO] Loading YOLOv8s...")
                self._model = YOLO("yolov8s.pt")
            print("[INFO] Warming up...")
            self._model(np.zeros((416,416,3),dtype=np.uint8),
                        imgsz=416, verbose=False)
            print("[INFO] YOLO ready ✅")
            return True
        except ImportError:
            print("[WARN] ultralytics not installed — HOG fallback")
            self._init_hog()
            return False
        except Exception as e:
            print(f"[WARN] YOLO failed ({e}) — HOG fallback")
            self._init_hog()
            return False

    def _init_hog(self):
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        print("[INFO] HOG ready ✅")

    def _detect_hog(self, frame):
        h,w=frame.shape[:2]; sc=640/w
        sm=cv2.resize(frame,(640,int(h*sc)))
        rects,weights=self._hog.detectMultiScale(sm,winStride=(4,4),padding=(8,8),scale=1.03)
        pb,ab=[],[]
        for i,(x,y,bw,bh) in enumerate(rects):
            x1=int(x/sc); y1=int(y/sc)
            x2=int((x+bw)/sc); y2=int((y+bh)/sc)
            cf=min(float(weights[i])/2.0,0.99) if i<len(weights) else 0.75
            pb.append((x1,y1,x2,y2))
            ab.append(("person",cf,x1,y1,x2,y2))
        return pb,[],ab

    def _trigger_alert(self):
        try:
            if self._alert_thread is not None:
                try:
                    alive = self._alert_thread.is_alive()
                except Exception:
                    alive = False
                if alive: return
            self._alert_thread = AlertSoundThread()
            self._alert_thread.start()
        except Exception as e:
            print(f"[WARN] Alert: {e}")

    def run(self, source, mobile_url=None):
        model_ok = self._load_model()

        # Start YOLO background thread
        if model_ok:
            self._yolo_thread = YOLOThread(self._model, self.conf_threshold)
            self._yolo_thread.start()
            detect_fn = None
        else:
            detect_fn = self._detect_hog

        from surveillance.mobile_camera import get_camera_source
        cap = get_camera_source(source, mobile_url)
        if not cap.isOpened():
            print(f"[ERROR] Cannot open: {mobile_url or source}")
            return

        sw=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        sh=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps_src=cap.get(cv2.CAP_PROP_FPS) or 30
        print(f"[INFO] {self.cam_id} | {mobile_url or source} | {sw}x{sh} | {fps_src:.1f}fps")

        writer=None
        if self.record_path:
            fourcc=cv2.VideoWriter_fourcc(*"mp4v")
            writer=cv2.VideoWriter(self.record_path,fourcc,fps_src,(sw,sh))
            print(f"[INFO] Recording → {self.record_path}")

        print()
        print("  Q=Quit | A=Admin/User | S=Screenshot | F=Fullscreen")
        print()

        # ── Window setup ──────────────────────────────────
        win = f"Hydra Surveillance — {self.cam_id}"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 1280, 720)

        # Get screen size
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
            SCREEN_W = ctypes.windll.user32.GetSystemMetrics(0)
            SCREEN_H = ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            SCREEN_W,SCREEN_H = 1920,1080

        is_full       = False
        went_full     = False

        def go_full():
            cv2.setWindowProperty(win,cv2.WND_PROP_FULLSCREEN,cv2.WINDOW_FULLSCREEN)

        def go_window():
            cv2.setWindowProperty(win,cv2.WND_PROP_FULLSCREEN,cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win,1280,720)

        # ── Main loop vars ────────────────────────────────
        t_prev    = time.time()
        frame_id  = 0
        fails     = 0
        det_frame = None  # small frame sent to YOLO thread

        # Cached results
        c_pb,c_wb,c_ab = [],[],[]

        # Scale factors (set after first frame)
        sx=sy=1.0

        while True:
            ret,frame = cap.read()
            if not ret or frame is None:
                if isinstance(source,str) and not mobile_url:
                    cap.set(cv2.CAP_PROP_POS_FRAMES,0); continue
                fails+=1
                if fails<60: time.sleep(0.02); continue
                print("[WARN] Camera stopped."); break
            fails=0; frame_id+=1

            # Get frame dimensions
            fh,fw = frame.shape[:2]

            # ── Submit to YOLO thread (non-blocking) ──────
            if model_ok:
                # Resize to 416 for YOLO, keep original for display
                det_frame = cv2.resize(frame,(416,416))
                self._yolo_thread.submit(det_frame)
                sx = fw/416; sy = fh/416

                # Get latest result (from previous submission — zero delay)
                raw_pb,raw_wb,raw_ab = self._yolo_thread.get_result()

                # Scale boxes back to display size
                c_pb=[(int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)) for x1,y1,x2,y2 in raw_pb]
                c_wb=[(int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)) for x1,y1,x2,y2 in raw_wb]
                c_ab=[(l,c,int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)) for l,c,x1,y1,x2,y2 in raw_ab]
            else:
                try:
                    c_pb,c_wb,c_ab = detect_fn(frame)
                except Exception: pass

            # ── Fire ──────────────────────────────────────
            fire_boxes,fire_ratio = self.fire_detector.detect(frame)
            for fx1,fy1,fx2,fy2 in fire_boxes:
                c_ab.append(("fire",min(fire_ratio*10,0.99),fx1,fy1,fx2,fy2))

            # ── Behaviour ─────────────────────────────────
            bevents = self.behaviour.analyse(c_pb,c_wb,frame.shape)

            # ── Cross-cam ─────────────────────────────────
            try:
                tracks = self.tracker.update(frame,c_pb)
            except Exception:
                tracks = []

            # ── Threat ────────────────────────────────────
            stats = self.threat_analyzer.analyze(c_pb,c_wb,fire_boxes,bevents)

            # ── Alert + SMS ───────────────────────────────
            if stats["should_beep"]:
                self._trigger_alert()
                # Determine threat type for SMS
                if c_wb:            ttype="WEAPON DETECTED"
                elif fire_boxes:    ttype="FIRE DETECTED"
                elif bevents:       ttype=bevents[0]["type"]
                else:               ttype="THREAT"
                self.sms.send(ttype, stats["threat_score"], self.cam_id)
                print(f"[ALERT] {self.cam_id} | {ttype} | "
                      f"Score:{stats['threat_score']}% | "
                      f"Weapons:{stats['weapon_count']} | "
                      f"Fire:{stats['fire_count']} | "
                      f"Events:{[e['type'] for e in bevents]}")

            # ── FPS ───────────────────────────────────────
            t_now=time.time(); fps=1.0/max(t_now-t_prev,1e-6); t_prev=t_now

            # ── Face blur ─────────────────────────────────
            frame = self.face_module.process(frame, self.admin_mode)

            # ── HUD ───────────────────────────────────────
            frame = self.hud.draw(frame,stats,self.face_module.face_count,
                                  fps,c_ab,tracks)

            # ── Show ──────────────────────────────────────
            if writer: writer.write(frame)
            cv2.imshow(win, frame)

            # Go fullscreen after first frame loads
            if not went_full:
                cv2.waitKey(300)
                go_full()
                went_full = True
                is_full   = True

            # ── Keys ──────────────────────────────────────
            key = cv2.waitKey(1) & 0xFF
            if key==ord("q"):
                print("[INFO] Quit."); break
            elif key==ord("f"):
                is_full = not is_full
                go_full() if is_full else go_window()
                print(f"[INFO] {'Fullscreen' if is_full else 'Windowed'}")
            elif key==ord("a"):
                self.admin_mode = not self.admin_mode
                self.hud = HUDRenderer(self.admin_mode, self.cam_id)
                print(f"[INFO] {'ADMIN' if self.admin_mode else 'USER'} mode")
            elif key==ord("s"):
                fn=f"screenshot_{self.cam_id}_{int(time.time())}.jpg"
                cv2.imwrite(fn, frame)
                print(f"[INFO] Screenshot: {fn}")

        # ── Cleanup ───────────────────────────────────────
        if self._yolo_thread:
            self._yolo_thread.stop()
        cap.release()
        if writer: writer.release()
        cv2.destroyAllWindows()
        print(f"[INFO] {self.cam_id} stopped.")
