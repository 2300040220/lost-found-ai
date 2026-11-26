"""Run this ONCE on your own PC (internet needed) to create ai_models/yolov8n.onnx.

    pip install ultralytics
    python export_yolo_onnx.py

'ultralytics' (and its PyTorch dependency) is needed ONLY for this export. It is not in requirements.txt,
because the app itself runs the exported file with OpenCV and needs no PyTorch.
"""
import os
import shutil

from ultralytics import YOLO

model = YOLO("yolov8n.pt")                         # downloads the small pre-trained COCO model
exported = model.export(format="onnx", imgsz=640, opset=12, simplify=False, dynamic=False)
os.makedirs("ai_models", exist_ok=True)
target = os.path.join("ai_models", "yolov8n.onnx")
shutil.copy(exported, target)
print(f"\nDone. Model saved to {target} ({os.path.getsize(target) / 1e6:.1f} MB)")
