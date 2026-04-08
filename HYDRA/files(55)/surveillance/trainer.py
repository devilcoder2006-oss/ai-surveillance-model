"""
Weapon Detector Training Pipeline — Team Hydra
================================================
Fine-tunes YOLOv8s on a custom weapon dataset.
Best weights saved to models/weapon_detector.pt
Auto-used by the system on next run.

Dataset sources (free):
  - https://universe.roboflow.com  (search "knife detection" or "gun detection")
  - https://www.kaggle.com/datasets

Dataset folder structure needed:
  datasets/weapon/
    images/train/   ← training images (.jpg/.png)
    images/val/     ← validation images
    labels/train/   ← YOLO label .txt files
    labels/val/     ← YOLO label .txt files
    data.yaml       ← class config (auto-created if missing)

YOLO label format (one object per line):
  <class_id> <center_x> <center_y> <width> <height>
  All values 0–1 relative to image dimensions.
"""

import os
import sys
import shutil

DATASET_YAML = "datasets/weapon/data.yaml"
OUTPUT_DIR   = "models/"
WEIGHTS_OUT  = "models/weapon_detector.pt"

SAMPLE_YAML = """\
path: datasets/weapon
train: images/train
val:   images/val

nc: 4
names:
  - knife
  - gun
  - scissors
  - baseball bat
"""


def run_training():
    print("=" * 60)
    print("  WEAPON DETECTOR TRAINING — Team Hydra")
    print("=" * 60)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics not installed.")
        print("        1. Enable Windows Long Paths (see README)")
        print("        2. Run: python3 -m pip install ultralytics")
        sys.exit(1)

    # Create folder structure
    for folder in [
        "datasets/weapon/images/train",
        "datasets/weapon/images/val",
        "datasets/weapon/labels/train",
        "datasets/weapon/labels/val",
        OUTPUT_DIR,
    ]:
        os.makedirs(folder, exist_ok=True)

    # Create data.yaml if missing
    if not os.path.exists(DATASET_YAML):
        with open(DATASET_YAML, "w") as f:
            f.write(SAMPLE_YAML)
        print(f"[INFO] Created: {DATASET_YAML}")

    # Check dataset has images
    train_imgs = os.listdir("datasets/weapon/images/train")
    if not train_imgs:
        print()
        print("  ┌──────────────────────────────────────────────────┐")
        print("  │  DATASET REQUIRED — No training images found     │")
        print("  │                                                  │")
        print("  │  Download a free dataset:                        │")
        print("  │  1. Go to: https://universe.roboflow.com         │")
        print("  │  2. Search: 'knife detection' or 'gun detection' │")
        print("  │  3. Download → YOLOv8 format                     │")
        print("  │  4. Extract into datasets/weapon/                │")
        print("  │  5. Re-run: python3 main.py --train              │")
        print("  └──────────────────────────────────────────────────┘")
        print()
        print("  Quick Roboflow download:")
        print("    pip install roboflow")
        print("    python3 -c \"")
        print("    from roboflow import Roboflow")
        print("    rf = Roboflow(api_key='YOUR_KEY')")
        print("    p = rf.workspace().project('knife-detection-8jvhz')")
        print("    p.version(2).download('yolov8', location='datasets/weapon')\"")
        return

    print(f"[INFO] Found {len(train_imgs)} training images")
    print("[INFO] Loading YOLOv8s base model...")
    model = YOLO("yolov8s.pt")

    print("[INFO] Starting training (50 epochs)...")
    print()
    model.train(
        data=DATASET_YAML,
        epochs=50,
        imgsz=640,
        batch=16,
        name="weapon_detector",
        project="runs/train",
        patience=10,
        augment=True,
        degrees=10.0,
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.1,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        save=True,
        plots=True,
    )

    best = "runs/train/weapon_detector/weights/best.pt"
    if os.path.exists(best):
        shutil.copy(best, WEIGHTS_OUT)
        print(f"\n[SUCCESS] Best weights saved → {WEIGHTS_OUT}")
        print(f"          Run the system: python3 main.py")
    else:
        print("[WARN] best.pt not found — check runs/train/")

    print("\n[INFO] Running validation...")
    model.val(data=DATASET_YAML)
    print("\n[DONE] Training complete!")
    print("       Plots and metrics: runs/train/weapon_detector/")
