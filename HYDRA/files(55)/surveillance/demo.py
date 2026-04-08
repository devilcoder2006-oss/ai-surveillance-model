"""
Demo Mode — Team Hydra
========================
Runs full surveillance UI with simulated detections.
No webcam, no model, no hardware required.
Great for testing and presentations.

Scenarios (auto-rotate every 8 seconds):
  1. Normal scene    — 2 people, no threat
  2. Weapon detected — person + knife
  3. Robbery         — weapon held near person
  4. Fighting        — 2 people close together
  5. Fire            — fire region detected
  6. Loitering       — person stationary
"""

import cv2
import numpy as np
import time
import sys
from surveillance.detector import (
    FaceBlurModule, ThreatAnalyzer, HUDRenderer,
    AlertSoundThread, BehaviourAnalyser, FireDetector, COLOR_WEAPON, COLOR_PERSON
)
from surveillance.cross_camera import CrossCameraTracker


SCENARIOS = [
    "Normal Scene",
    "Weapon Detected",
    "Robbery in Progress",
    "Fighting",
    "Fire Detected",
    "Loitering",
]
SCENARIO_DURATION = 8.0


def run_demo():
    print("=" * 60)
    print("  DEMO MODE — Simulated Detections — Team Hydra")
    print("=" * 60)
    print("  Press Q=Quit | A=Toggle Admin/User | S=Screenshot")
    print()

    W, H       = 960, 540
    admin_mode = False
    face_mod   = FaceBlurModule()
    threat     = ThreatAnalyzer(alert_cooldown=5.0)
    hud        = HUDRenderer(admin_mode, "DEMO")
    behaviour  = BehaviourAnalyser(loiter_seconds=6.0)
    fire_det   = FireDetector(sensitivity=0.001)
    tracker    = CrossCameraTracker(cam_id="DEMO")
    alert_thread = None

    scenario_idx   = 0
    scenario_timer = time.time()

    while True:
        t = time.time()
        if t - scenario_timer > SCENARIO_DURATION:
            scenario_idx   = (scenario_idx + 1) % len(SCENARIOS)
            scenario_timer = t
            print(f"[DEMO] Scenario: {SCENARIOS[scenario_idx]}")

        scenario = SCENARIOS[scenario_idx]

        # Build background frame
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        for i in range(H):
            v = int(18 + 12*(i/H))
            frame[i] = (v, v+4, v+8)
        cv2.rectangle(frame, (40,300),(920,540),(28,28,38),-1)
        cv2.rectangle(frame, (580,60),(920,320),(22,22,32),-1)

        # Build detections per scenario
        person_boxes, weapon_boxes, all_boxes = [], [], []

        if scenario == "Normal Scene":
            for pb in [(80,140,240,490),(400,130,570,495)]:
                person_boxes.append(pb); all_boxes.append(("person",0.91,*pb))
                _draw_person(frame, pb)

        elif scenario == "Weapon Detected":
            pb=(90,140,250,490); wb=(700,180,755,310)
            person_boxes.append(pb); all_boxes.append(("person",0.88,*pb))
            weapon_boxes.append(wb); all_boxes.append(("knife",0.74,*wb))
            _draw_person(frame, pb)

        elif scenario == "Robbery in Progress":
            pb=(280,120,490,500); wb=(390,310,445,430)
            person_boxes.append(pb); all_boxes.append(("person",0.93,*pb))
            weapon_boxes.append(wb); all_boxes.append(("knife",0.82,*wb))
            _draw_person(frame, pb)

        elif scenario == "Fighting":
            pb1=(200,130,390,490); pb2=(320,120,510,495)
            for pb in [pb1,pb2]:
                person_boxes.append(pb); all_boxes.append(("person",0.87,*pb))
                _draw_person(frame, pb)

        elif scenario == "Fire Detected":
            pb=(100,140,260,490)
            person_boxes.append(pb); all_boxes.append(("person",0.85,*pb))
            _draw_person(frame, pb)
            # Draw fire region
            pts=np.array([[600,300],[700,280],[750,400],[580,420]],np.int32)
            cv2.fillPoly(frame,[pts],(30,100,220))
            cv2.fillPoly(frame,[pts-np.array([[20,20]])], (20,160,255))
            all_boxes.append(("fire",0.88,580,280,750,420))

        elif scenario == "Loitering":
            pb=(350,130,550,490)
            person_boxes.append(pb); all_boxes.append(("person",0.90,*pb))
            _draw_person(frame, pb)

        # Draw fake faces (circles) for face blur demo
        for (px1,py1,px2,py2) in person_boxes:
            cx=(px1+px2)//2; fy=py1+(py2-py1)//8+25
            cv2.circle(frame,(cx,fy),28,(175,135,105),-1)

        # Behaviour + fire
        bevents    = behaviour.analyse(person_boxes, weapon_boxes, frame.shape)
        fire_boxes,_ = fire_det.detect(frame)
        tracks     = tracker.update(frame, person_boxes)
        stats      = threat.analyze(person_boxes, weapon_boxes, fire_boxes, bevents)

        if stats["should_beep"]:
            if not (alert_thread and alert_thread.is_alive()):
                alert_thread = AlertSoundThread()
                alert_thread.start()
            print(f"[DEMO] ALERT! Threat:{stats['threat_score']}%")

        frame = face_mod.process(frame, admin_mode)
        frame = hud.draw(frame, stats, face_mod.face_count, 30.0, all_boxes, tracks)

        # Scenario label at bottom
        rem = int(SCENARIO_DURATION-(t-scenario_timer))
        cv2.putText(frame, f"DEMO SCENARIO: {scenario.upper()} ({rem}s)",
                    (W//2-200, H-15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (200,200,100), 1, cv2.LINE_AA)

        cv2.imshow("Hydra Smart Surveillance — DEMO", frame)

        key = cv2.waitKey(33) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("a"):
            admin_mode = not admin_mode
            hud = HUDRenderer(admin_mode, "DEMO")
            print(f"[DEMO] Switched to {'ADMIN' if admin_mode else 'USER'} mode")
        elif key == ord("s"):
            fname = f"demo_screenshot_{int(time.time())}.jpg"
            cv2.imwrite(fname, frame)
            print(f"[DEMO] Screenshot: {fname}")

    cv2.destroyAllWindows()
    print("[DEMO] Exited.")


def _draw_person(frame, box):
    x1,y1,x2,y2 = box
    cx=(x1+x2)//2
    cv2.rectangle(frame,(x1,y1+(y2-y1)//4),(x2,y2),(55,65,78),-1)
