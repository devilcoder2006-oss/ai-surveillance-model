"""
AI Smart Surveillance — Team Hydra (FINAL)

Usage:
  python main.py                                      # Webcam
  python main.py --admin                              # Admin mode (no face blur)
  python main.py --mobile http://192.168.1.5:8080    # Phone camera
  python main.py --video path/to/video.mp4            # Video file
  python main.py --camera 1                           # Different webcam
  python main.py --cam-id CAM2                        # Set camera ID
  python main.py --conf 0.15                          # Lower = detects more
  python main.py --record output.mp4                  # Save recording
  python main.py --multi-cam                          # 2 cameras together
  python main.py --multi-cam --mobile http://IP:8080  # Webcam + phone
  python main.py --train                              # Train custom model
  python main.py --demo                               # Demo mode
  python main.py --clear-db                           # Clear cross-cam DB
"""

import argparse
import sys
import threading


def main():
    parser = argparse.ArgumentParser(description="Hydra AI Surveillance")
    parser.add_argument("--admin",     action="store_true",  help="Admin mode")
    parser.add_argument("--video",     type=str,  default=None,   help="Video file")
    parser.add_argument("--camera",    type=int,  default=0,      help="Webcam index")
    parser.add_argument("--mobile",    type=str,  default=None,   help="Phone camera URL")
    parser.add_argument("--cam-id",    type=str,  default="CAM1", help="Camera ID")
    parser.add_argument("--conf",      type=float,default=0.20,   help="Confidence (default 0.20)")
    parser.add_argument("--record",    type=str,  default=None,   help="Record output")
    parser.add_argument("--train",     action="store_true",  help="Train model")
    parser.add_argument("--demo",      action="store_true",  help="Demo mode")
    parser.add_argument("--multi-cam", action="store_true",  help="Two cameras")
    parser.add_argument("--clear-db",  action="store_true",  help="Clear cross-cam DB")
    args = parser.parse_args()

    if args.clear_db:
        from surveillance.cross_camera import CrossCameraDB
        CrossCameraDB().clear()
        print("[INFO] Cross-camera DB cleared.")
        return

    if args.train:
        from surveillance.trainer import run_training
        run_training()

    elif args.demo:
        from surveillance.demo import run_demo
        run_demo()

    elif args.multi_cam:
        _run_multi(args)

    else:
        from surveillance.detector import SurveillanceSystem
        system = SurveillanceSystem(
            admin_mode=args.admin,
            conf_threshold=args.conf,
            record_path=args.record,
            cam_id=args.cam_id,
        )
        source = args.video if args.video else args.camera
        system.run(source, mobile_url=args.mobile)


def _run_multi(args):
    from surveillance.detector import SurveillanceSystem
    def run_cam(idx, cam_id, mobile=None):
        SurveillanceSystem(
            admin_mode=args.admin,
            conf_threshold=args.conf,
            cam_id=cam_id
        ).run(idx, mobile_url=mobile)

    if args.mobile:
        print("[INFO] CAM1=Webcam | CAM2=Phone")
        t1 = threading.Thread(target=run_cam, args=(0,"CAM1",None),       daemon=True)
        t2 = threading.Thread(target=run_cam, args=(0,"CAM2",args.mobile),daemon=True)
    else:
        print("[INFO] CAM1=Webcam0 | CAM2=Webcam1")
        t1 = threading.Thread(target=run_cam, args=(0,"CAM1",None), daemon=True)
        t2 = threading.Thread(target=run_cam, args=(1,"CAM2",None), daemon=True)
    t1.start(); t2.start()
    t1.join();  t2.join()


if __name__ == "__main__":
    main()
