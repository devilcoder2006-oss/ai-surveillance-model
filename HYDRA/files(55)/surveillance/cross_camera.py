"""
Cross-Camera Tracking — Team Hydra
=====================================
Tracks the same person across multiple cameras using:
  - Color histogram appearance matching
  - Shared JSON identity database (all cameras read/write it)
  - Global IDs shown on HUD with camera history

How it works:
  1. Each person crop → color histogram (appearance descriptor)
  2. Descriptor matched against global DB
  3. If similarity > threshold → same person, same global ID
  4. If new → new global ID assigned
  5. HUD shows: ID badge + "Also seen: CAM2" label
"""

import cv2
import numpy as np
import time
import os
import json
import threading

SHARED_DB_PATH = "cross_camera_db.json"
DB_LOCK        = threading.Lock()

ID_COLORS = [
    (255, 50,  50),
    (50,  255, 50),
    (50,  50,  255),
    (255, 255, 50),
    (255, 50,  255),
    (50,  255, 255),
    (255, 165, 0),
    (128, 0,   255),
]

def get_id_color(person_id: int):
    return ID_COLORS[person_id % len(ID_COLORS)]


# ─────────────────────────────────────────────────────────
# APPEARANCE DESCRIPTOR
# ─────────────────────────────────────────────────────────
class AppearanceDescriptor:
    """Extracts a compact HSV color histogram from a person crop."""

    @staticmethod
    def extract(frame: np.ndarray, box: tuple) -> np.ndarray:
        x1, y1, x2, y2 = box
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(frame.shape[1], x2)
        y2 = min(frame.shape[0], y2)
        if x2 - x1 < 10 or y2 - y1 < 10:
            return np.zeros(96, dtype=np.float32)
        crop = frame[y1:y2, x1:x2]
        # Focus on torso (middle 60%) — more stable than head/feet
        h = crop.shape[0]
        torso = crop[int(h*0.2):int(h*0.8), :]
        if torso.size == 0:
            torso = crop
        hsv    = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        h_hist = cv2.calcHist([hsv], [0], None, [32], [0, 180])
        s_hist = cv2.calcHist([hsv], [1], None, [32], [0, 256])
        v_hist = cv2.calcHist([hsv], [2], None, [32], [0, 256])
        hist   = np.concatenate([h_hist, s_hist, v_hist]).flatten().astype(np.float32)
        norm   = np.linalg.norm(hist)
        return hist / norm if norm > 0 else hist

    @staticmethod
    def similarity(d1: np.ndarray, d2: np.ndarray) -> float:
        if d1 is None or d2 is None:
            return 0.0
        n1 = np.linalg.norm(d1); n2 = np.linalg.norm(d2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(d1, d2))


# ─────────────────────────────────────────────────────────
# LOCAL TRACKER (single camera)
# ─────────────────────────────────────────────────────────
class LocalTracker:
    """Tracks persons within one camera. Assigns stable local IDs."""

    def __init__(self, max_disappeared=30):
        self.max_disappeared = max_disappeared
        self._next_id = 0
        self._tracks  = {}

    def update(self, frame: np.ndarray, person_boxes: list) -> list:
        if not person_boxes:
            for tid in list(self._tracks.keys()):
                self._tracks[tid]["disappeared"] += 1
                if self._tracks[tid]["disappeared"] > self.max_disappeared:
                    del self._tracks[tid]
            return []

        new_descs = [AppearanceDescriptor.extract(frame, b) for b in person_boxes]

        if not self._tracks:
            for box, desc in zip(person_boxes, new_descs):
                self._register(box, desc)
        else:
            tids  = list(self._tracks.keys())
            tdescs = [self._tracks[t]["desc"] for t in tids]
            sim   = np.zeros((len(tids), len(person_boxes)))
            for i, td in enumerate(tdescs):
                for j, nd in enumerate(new_descs):
                    sim[i, j] = AppearanceDescriptor.similarity(td, nd)

            matched_t = set(); matched_d = set()
            while True:
                idx = np.unravel_index(np.argmax(sim), sim.shape)
                if sim[idx] < 0.65:
                    break
                ti, di = idx
                if ti in matched_t or di in matched_d:
                    sim[ti, di] = 0; continue
                tid = tids[ti]
                self._tracks[tid].update({
                    "box": person_boxes[di], "desc": new_descs[di],
                    "disappeared": 0, "last_seen": time.time()
                })
                matched_t.add(ti); matched_d.add(di)
                sim[ti, :] = 0; sim[:, di] = 0

            for ti, tid in enumerate(tids):
                if ti not in matched_t:
                    self._tracks[tid]["disappeared"] += 1
                    if self._tracks[tid]["disappeared"] > self.max_disappeared:
                        del self._tracks[tid]

            for di in range(len(person_boxes)):
                if di not in matched_d:
                    self._register(person_boxes[di], new_descs[di])

        return [(tid, info["box"], info["desc"])
                for tid, info in self._tracks.items() if info["disappeared"] == 0]

    def _register(self, box, desc):
        self._tracks[self._next_id] = {
            "box": box, "desc": desc, "disappeared": 0, "last_seen": time.time()
        }
        self._next_id += 1


# ─────────────────────────────────────────────────────────
# CROSS-CAMERA DATABASE
# ─────────────────────────────────────────────────────────
class CrossCameraDB:
    """Shared global identity database across all cameras. Stored as JSON file."""

    def __init__(self, similarity_threshold=0.72):
        self.sim_threshold = similarity_threshold
        self._global_ids   = {}
        self._next_gid     = 0
        self._load()

    def _load(self):
        if not os.path.exists(SHARED_DB_PATH):
            return
        try:
            with open(SHARED_DB_PATH, "r") as f:
                data = json.load(f)
            self._next_gid = data.get("next_gid", 0)
            for gid_str, info in data.get("ids", {}).items():
                gid = int(gid_str)
                self._global_ids[gid] = {
                    "desc":      np.array(info["desc"], dtype=np.float32),
                    "cameras":   set(info["cameras"]),
                    "last_seen": info["last_seen"],
                    "sightings": info["sightings"],
                }
        except Exception:
            pass

    def _save(self):
        data = {
            "next_gid": self._next_gid,
            "ids": {
                str(gid): {
                    "desc":      info["desc"].tolist(),
                    "cameras":   list(info["cameras"]),
                    "last_seen": info["last_seen"],
                    "sightings": info["sightings"],
                }
                for gid, info in self._global_ids.items()
            }
        }
        with open(SHARED_DB_PATH, "w") as f:
            json.dump(data, f)

    def match_or_register(self, desc: np.ndarray, cam_id: str) -> dict:
        with DB_LOCK:
            self._load()
            best_gid = None; best_sim = 0.0
            for gid, info in self._global_ids.items():
                s = AppearanceDescriptor.similarity(desc, info["desc"])
                if s > best_sim:
                    best_sim = s; best_gid = gid

            is_new = best_sim < self.sim_threshold
            if is_new:
                gid = self._next_gid; self._next_gid += 1
                self._global_ids[gid] = {
                    "desc": desc, "cameras": {cam_id},
                    "last_seen": time.time(), "sightings": 1
                }
            else:
                gid  = best_gid
                info = self._global_ids[gid]
                info["desc"]      = info["desc"] * 0.7 + desc * 0.3
                info["cameras"].add(cam_id)
                info["last_seen"] = time.time()
                info["sightings"] += 1

            result = self._global_ids[gid]
            self._save()
            return {
                "global_id": gid,
                "is_new":    is_new,
                "cameras":   list(result["cameras"]),
                "sightings": result["sightings"],
                "similarity": best_sim,
            }

    def get_all(self):
        with DB_LOCK:
            self._load()
            return dict(self._global_ids)

    def clear(self):
        with DB_LOCK:
            self._global_ids = {}; self._next_gid = 0
            if os.path.exists(SHARED_DB_PATH):
                os.remove(SHARED_DB_PATH)
            print("[INFO] Cross-camera DB cleared.")


# ─────────────────────────────────────────────────────────
# CROSS-CAMERA TRACKER
# ─────────────────────────────────────────────────────────
class CrossCameraTracker:
    """Combines LocalTracker + CrossCameraDB to give global person IDs."""

    def __init__(self, cam_id="CAM1", similarity_threshold=0.72):
        self.cam_id     = cam_id
        self.local      = LocalTracker(max_disappeared=30)
        self.db         = CrossCameraDB(similarity_threshold)
        self._gmap      = {}   # local_id → global match

    def update(self, frame: np.ndarray, person_boxes: list) -> list:
        local_tracks = self.local.update(frame, person_boxes)
        results = []
        for (lid, box, desc) in local_tracks:
            if lid not in self._gmap:
                self._gmap[lid] = self.db.match_or_register(desc, self.cam_id)
            match = self._gmap[lid]
            results.append({
                "local_id":  lid,
                "global_id": match["global_id"],
                "box":       box,
                "cameras":   match["cameras"],
                "sightings": match["sightings"],
                "is_new":    match["is_new"],
            })
        return results
