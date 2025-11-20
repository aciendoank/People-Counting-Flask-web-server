# apps/home/yolov5_processor.py
# -*- encoding: utf-8 -*-

import os
from ultralytics import YOLO
import logging

# Konfigurasi logging untuk output yang lebih jelas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Direktori tempat model akan disimpan
MODEL_DIR = os.path.join("apps", "static", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

class YOLOv5Processor:
    def __init__(self, model_path='yolov5n.pt'):
        self.model_path = os.path.join(MODEL_DIR, model_path)
        self.download_yolov5_model()

        try:
            self.model = YOLO(self.model_path)
            logger.info(f"✅ YOLOv5 model ({model_path}) berhasil dimuat.")
        except Exception as e:
            logger.error(f"❌ Gagal memuat model YOLOv5 dari {self.model_path}: {e}")
            raise

    def download_yolov5_model(self):
        if os.path.exists(self.model_path) and os.path.getsize(self.model_path) > 1024 * 1024:
            logger.info(f"✅ Model file {os.path.basename(self.model_path)} sudah ada dan valid.")
            return

        logger.info(f"Model {os.path.basename(self.model_path)} tidak ditemukan atau rusak. Mengunduh...")
        
        try:
            YOLO(os.path.basename(self.model_path))
            model_source_path = os.path.join(os.path.expanduser('~'), '.cache/ultralytics/models', os.path.basename(self.model_path))
            
            if os.path.exists(model_source_path):
                logger.info(f"✅ Model ditemukan di cache: {model_source_path}")
                os.replace(model_source_path, self.model_path)
                logger.info(f"✅ Model berhasil dipindahkan ke: {self.model_path}")
            else:
                logger.error(f"❌ File {os.path.basename(self.model_path)} tidak ditemukan di cache setelah mencoba mengunduh. Jalur yang dicari: {model_source_path}")
                logger.warning("Silakan pastikan koneksi internet stabil atau coba unggah model secara manual.")

        except Exception as e:
            logger.error(f"❌ Gagal mengunduh atau memindahkan model YOLOv5: {e}")

    def process_frame(self, frame, classes=None):
        results = self.model(frame, verbose=False)
        detections_list = []

        if results and results[0].boxes:
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = box.conf[0].item()
                    cls = int(box.cls[0].item())
                    name = self.model.names[cls]
                    
                    center_x = (x1 + x2) / 2
                    center_y = (y1 + y2) / 2

                    detections_list.append({
                        'name': name,
                        'box': [int(x1), int(y1), int(x2), int(y2)],
                        'confidence': conf,
                        'center': (int(center_x), int(center_y))
                    })
        
        logger.debug(f"Ditemukan {len(detections_list)} deteksi di frame.")
        return detections_list