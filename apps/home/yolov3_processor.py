# apps/home/yolov3_processor.py
# -*- encoding: utf-8 -*-

import cv2
import numpy as np
import logging
import math
import os
import urllib.request

# Konfigurasi logging untuk output yang lebih jelas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Direktori tempat model akan disimpan
MODEL_DIR = os.path.join("apps", "static", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

class YOLOv3Processor:
    """
    Processor untuk deteksi objek menggunakan model YOLOv3-tiny.
    Menggunakan modul OpenCV DNN.
    """
    def __init__(self, confidence_threshold=0.5, nms_threshold=0.6):
        """
        Inisialisasi YOLOv3-tiny model processor.
        """
        self.confidence_threshold = float(confidence_threshold)
        self.nms_threshold = float(nms_threshold)
        
        self.cfg_path = os.path.join(MODEL_DIR, "yolov3-tiny.cfg")
        self.weights_path = os.path.join(MODEL_DIR, "yolov3-tiny.weights")
        self.names_path = os.path.join(MODEL_DIR, "coco.names")
        
        self.download_yolov3_tiny()

        try:
            self.classes = self._load_classes()
            self.net = cv2.dnn.readNetFromDarknet(self.cfg_path, self.weights_path)
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            self.output_layers = [self.net.getLayerNames()[i - 1] for i in self.net.getUnconnectedOutLayers()]
            logger.info("✅ YOLOv3-tiny model berhasil dimuat.")
        except Exception as e:
            logger.error(f"❌ Gagal memuat model YOLOv3-tiny: {e}")
            raise

    def _load_classes(self):
        """Memuat nama-nama kelas dari file .names."""
        if not os.path.exists(self.names_path):
            raise FileNotFoundError(f"File kelas tidak ditemukan: {self.names_path}")
        
        with open(self.names_path, 'r') as f:
            class_names = [line.strip() for line in f.readlines()]
        
        classes = {i: name for i, name in enumerate(class_names)}
        logger.debug("✅ Nama-nama kelas berhasil dimuat.")
        return classes

    def download_yolov3_tiny(self):
        """Fungsi untuk mengunduh model YOLOv3-tiny dan file kelas dari internet."""
        urls = {
            "yolov3-tiny.cfg": "https://raw.githubusercontent.com/pjreddie/darknet/master/cfg/yolov3-tiny.cfg",
            "yolov3-tiny.weights": "https://pjreddie.com/media/files/yolov3-tiny.weights",
            "coco.names": "https://raw.githubusercontent.com/pjreddie/darknet/master/data/coco.names"
        }
        
        for filename, url in urls.items():
            filepath = os.path.join(MODEL_DIR, filename)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024 * 10:
                logger.info(f"✅ Model file {filename} sudah ada.")
                continue

            logger.info(f"Mengunduh {filename} dari {url}...")
            try:
                urllib.request.urlretrieve(url, filepath)
                logger.info(f"✅ {filename} berhasil diunduh.")
            except Exception as e:
                logger.error(f"❌ Gagal mengunduh {filename}: {e}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                raise

    def process_frame(self, frame):
        """
        Metode utama untuk memproses frame video dan mengembalikan deteksi mentah.
        """
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 1/255.0, (416, 416), swapRB=True, crop=False)
        self.net.setInput(blob)
        layer_outputs = self.net.forward(self.output_layers)

        boxes, confidences, class_ids = [], [], []

        for output in layer_outputs:
            for detection in output:
                scores = detection[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]

                if confidence > self.confidence_threshold:
                    center_x = int(detection[0] * w)
                    center_y = int(detection[1] * h)
                    box_w = int(detection[2] * w)
                    box_h = int(detection[3] * h)

                    x = int(center_x - box_w / 2)
                    y = int(center_y - box_h / 2)

                    boxes.append([x, y, box_w, box_h])
                    confidences.append(float(confidence))
                    class_ids.append(class_id)
        
        indices = cv2.dnn.NMSBoxes(boxes, confidences, self.confidence_threshold, self.nms_threshold)
        
        detections_list = []
        if len(indices) > 0:
            for i in indices.flatten():
                (x, y, box_w, box_h) = boxes[i]
                obj_name = self.classes.get(class_ids[i])
                if not obj_name: continue
                
                detections_list.append({
                    'name': obj_name,
                    'box': [x, y, x + box_w, y + box_h], 
                    'confidence': confidences[i]
                })
        
        logger.debug(f"Ditemukan {len(detections_list)} deteksi setelah NMS.")
        return detections_list