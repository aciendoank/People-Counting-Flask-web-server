
# apps/home/ssdmobilenet_processor.py
import cv2
import numpy as np
import logging
import os

logger = logging.getLogger(__name__)

class SSDMobileNetProcessor:
    def __init__(self, model_path, config_path, labels_path):
        self.model_path = model_path
        self.config_path = config_path
        self.labels_path = labels_path
        self.net = None
        self.classes = []
        self._load_model()

    def _load_model(self):
        if not os.path.exists(self.model_path):
            logger.error(f"❌ File model SSD MobileNetV3 tidak ditemukan: {self.model_path}")
            raise FileNotFoundError(f"Model file not found: {self.model_path}")
        if not os.path.exists(self.config_path):
            logger.error(f"❌ File konfigurasi SSD MobileNetV3 tidak ditemukan: {self.config_path}")
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        if not os.path.exists(self.labels_path):
            logger.error(f"❌ File label SSD MobileNetV3 tidak ditemukan: {self.labels_path}")
            raise FileNotFoundError(f"Labels file not found: {self.labels_path}")

        try:
            self.net = cv2.dnn.readNetFromTensorflow(self.model_path, self.config_path)
            # Set backend ke OpenCV dan target ke CPU
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            logger.info("✅ SSD MobileNetV3 model berhasil dimuat dan diatur untuk CPU.")
        except Exception as e:
            logger.error(f"❌ Gagal memuat model SSD MobileNetV3: {e}")
            raise

        try:
            with open(self.labels_path, 'r') as f:
                self.classes = f.read().strip().split('\n')
            logger.info(f"✅ Label SSD MobileNetV3 berhasil dimuat. Jumlah kelas: {len(self.classes)}")
        except Exception as e:
            logger.error(f"❌ Gagal memuat label SSD MobileNetV3: {e}")
            raise

    def process_frame(self, frame, conf_threshold=0.5):
        h, w, _ = frame.shape

        # Preprocessing: normalisasi sesuai SSD MobileNet (scale 1/127.5 dan mean 127.5)
        blob = cv2.dnn.blobFromImage(
            frame, scalefactor=1/127.5, size=(300, 300),
            mean=(127.5, 127.5, 127.5), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        detections = self.net.forward()

        results = []
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]

            if confidence > conf_threshold:  # gunakan threshold (misal 0.5)
                idx = int(detections[0, 0, i, 1])
                if idx >= len(self.classes):
                    continue
                label = self.classes[idx - 1]

                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")

                # Clip biar tidak keluar dari frame
                offset_x = int(0.05 * w)
                startX = max(0, startX)
                startY = max(0, startY)
                endX = min(w - 1, endX)
                endY = min(h - 1, endY)

                center_x = int((startX + endX) / 2)
                center_y = int((startY + endY) / 2)

                results.append({
                    'name': label,
                    'confidence': float(confidence),
                    'box': [startX, startY, endX, endY],
                    'center': (center_x, center_y)
                })
        return results

    def get_class_names(self):
        return self.classes