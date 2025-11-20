# apps/home/ai_processor.py
# -*- encoding: utf-8 -*-
import os
import cv2
import threading
import time
import json
import logging
import base64
import math
import requests
import datetime
import subprocess
from ultralytics import YOLO
from flask_socketio import SocketIO
from .models import AlarmLog, Camera, AIModel, Count, GlobalSettings, FileRecord
from .yolov5_processor import YOLOv5Processor
from .ssdmobilenet_processor import SSDMobileNetProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
UPLOAD_FOLDER = 'apps/static/models'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Tambahkan folder untuk SSD MobileNet files
SSDMOBILENET_FOLDER = os.path.join(UPLOAD_FOLDER, 'ssdmobilenet')
os.makedirs(SSDMOBILENET_FOLDER, exist_ok=True)

lock = threading.Lock()
total_counts = {}
alarm_cooldowns = {}
screenshot_cooldowns = {}

# --- Fungsi Pengunduhan Model ---
def download_file(url, destination_path, file_description):
    if os.path.exists(destination_path) and os.path.getsize(destination_path) > 10 * 1024: # Minimal 10KB
        logger.info(f"✅ {file_description} sudah ada dan valid: {destination_path}")
        return True
    
    logger.info(f"⏳ Mengunduh {file_description} dari {url}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(destination_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"✅ {file_description} berhasil diunduh ke: {destination_path}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Gagal mengunduh {file_description}: {e}")
        return False

def download_yolov8n_if_not_exists():
    default_model_path = os.path.join(UPLOAD_FOLDER, 'yolov8n.pt')
    if os.path.exists(default_model_path) and os.path.getsize(default_model_path) > 1024 * 1024:
        logger.info("✅ Model bawaan yolov8n.pt sudah ada dan valid.")
        return

    logger.info("Model bawaan yolov8n.pt tidak ditemukan atau rusak. Mengunduh...")
    try:
        # Mengunduh model YOLOv8n secara otomatis ke cache Ultralytics
        YOLO('yolov8n.pt')
        model_source_path = os.path.join(os.path.expanduser('~'), '.cache/ultralytics/models', 'yolov8n.pt')
        
        if os.path.exists(model_source_path):
            logger.info(f"✅ Model ditemukan di cache: {model_source_path}")
            os.replace(model_source_path, default_model_path)
            logger.info(f"✅ Model berhasil dipindahkan ke: {default_model_path}")
        else:
            logger.error(f"❌ File yolov8n.pt tidak ditemukan di cache setelah mencoba mengunduh. Jalur yang dicari: {model_source_path}")
            logger.warning("Silakan pastikan koneksi internet stabil atau coba unggah model secara manual.")
    except Exception as e:
        logger.error(f"❌ Gagal mengunduh atau memindahkan model yolov8n.pt: {e}")

def download_ssdmobilenet_if_not_exists():
    model_url = "https://github.com/opencv/opencv_extra/raw/4.x/testdata/dnn/ssd_mobilenet_v3_large_coco_2020_01_14.pb"
    config_url = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/dnn/ssd_mobilenet_v3_large_coco.pbtxt"
    labels_url = "https://raw.githubusercontent.com/pjreddie/darknet/master/data/coco.names" # Labels umum COCO

    model_path = os.path.join(SSDMOBILENET_FOLDER, 'ssd_mobilenet_v3_large_coco.pb')
    config_path = os.path.join(SSDMOBILENET_FOLDER, 'ssd_mobilenet_v3_large_coco.pbtxt')
    labels_path = os.path.join(SSDMOBILENET_FOLDER, 'coco.names')

    all_downloaded = True
    if not download_file(model_url, model_path, "SSD MobileNetV3 model"):
        all_downloaded = False
    if not download_file(config_url, config_path, "SSD MobileNetV3 config"):
        all_downloaded = False
    if not download_file(labels_url, labels_path, "COCO labels"):
        all_downloaded = False
    
    return all_downloaded, model_path, config_path, labels_path

# --- Fungsi-fungsi lainnya (draw_counting_line, check_line_crossing, execute_action) tidak berubah ---
def draw_counting_line(frame, line_coords):
    if line_coords and 'x1' in line_coords and 'y1' in line_coords and 'x2' in line_coords and 'y2' in line_coords:
        h, w, _ = frame.shape
        start_point = (int(line_coords['x1'] * w), int(line_coords['y1'] * h))
        end_point = (int(line_coords['x2'] * w), int(line_coords['y2'] * h))
        
        cv2.line(frame, start_point, end_point, (0, 0, 255), 2)
        mid_point_x = int((start_point[0] + end_point[0]) / 2)
        mid_point_y = int((start_point[1] + end_point[1]) / 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.4
        font_thickness = 1
        text_color = (255, 255, 255)

        dx = end_point[0] - start_point[0]
        dy = end_point[1] - start_point[1]
        
        offset = 20
        length = (dx**2 + dy**2)**0.5
        if length == 0:
            return
        
        offset_x = int((-dy / length) * offset)
        offset_y = int((dx / length) * offset)

        in_pos = (mid_point_x + offset_x, mid_point_y + offset_y)
        cv2.putText(frame, 'IN', in_pos, font, font_scale, text_color, font_thickness, cv2.LINE_AA)

        out_pos = (mid_point_x - offset_x, mid_point_y - offset_y)
        cv2.putText(frame, 'OUT', out_pos, font, font_scale, text_color, font_thickness, cv2.LINE_AA)

def check_line_crossing(p1, p2, p3, p4):
    def orientation(p, q, r):
        val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        if val == 0: return 0
        return 1 if val > 0 else 2

    def on_segment(p, q, r):
        return (q[0] <= max(p[0], r[0]) and q[0] >= min(p[0], r[0]) and
                q[1] <= max(p[1], r[1]) and q[1] >= min(p[1], r[1]))

    o1 = orientation(p1, p2, p3)
    o2 = orientation(p1, p2, p4)
    o3 = orientation(p3, p4, p1)
    o4 = orientation(p3, p4, p2)

    if o1 != o2 and o3 != o4: return True
    if o1 == 0 and on_segment(p1, p3, p2): return True
    if o2 == 0 and on_segment(p1, p4, p2): return True
    if o3 == 0 and on_segment(p3, p1, p4): return True
    if o4 == 0 and on_segment(p3, p2, p4): return True
    return False

def execute_action(action_code, camera_data):
    """
    Mengeksekusi aksi (webhook, skrip kustom) berdasarkan kode JSON.
    """
    try:
        if not action_code:
            return
        
        action_data = json.loads(action_code)
        action_type = action_data.get('action')
        
        if action_type == 'send_webhook':
            url = action_data.get('url')
            if not url:
                logger.error("❌ URL webhook tidak ditemukan.")
                return
            
            payload = {
                "camera_id": camera_data.id,
                "event": "alarm",
                "trigger": camera_data.alarm_trigger,
                "timestamp": datetime.datetime.now().isoformat()
            }
            auth_data = action_data.get('auth')
            auth = (auth_data.get('user'), auth_data.get('pass')) if auth_data else None

            response = requests.post(url, json=payload, auth=auth)
            response.raise_for_status() 
            logger.info(f"✅ Webhook berhasil dikirim ke {url}")
                
        elif action_type == 'custom_script':
            command = action_data.get('command')
            if command:
                subprocess.run(command, shell=True, check=True)
                logger.info(f"✅ Skrip custom berhasil dijalankan: {command}")
                
        else:
            logger.warning(f"⚠️ Tipe aksi tidak dikenal: {action_type}")
            
    except json.JSONDecodeError:
        logger.error(f"❌ Kode aksi bukan format JSON yang valid: {action_code}")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Gagal mengeksekusi skrip custom: {e}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Gagal mengirim webhook: {e}")
    except Exception as e:
        logger.error(f"❌ Gagal mengeksekusi aksi: {e}")


# -------------------------------
# Logic AI Stream Utama
# -------------------------------
def ai_stream(socketio, app, cam_id, rtsp_url, stop_event, client_sids):
    """
    Thread utama untuk memproses video dari kamera secara real-time.
    """
    from apps import db 
    
    with app.app_context():
        try:
            camera_data = Camera.query.get(cam_id)
            if not camera_data:
                logger.error(f"❌ Kamera dengan ID {cam_id} tidak ditemukan di database.")
                socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': f"❌ Kamera ID {cam_id} tidak ditemukan."}, room=client_sids)
                return

            camera_name = camera_data.name 

            global_settings = GlobalSettings.query.first()
            user_model = AIModel.query.filter_by(cam_id=cam_id).first()

            conf_threshold = user_model.conf_threshold if user_model and user_model.conf_threshold is not None else None
            iou_threshold = user_model.iou_threshold if user_model and user_model.iou_threshold is not None else None

            if conf_threshold is None:
                conf_threshold = global_settings.conf_threshold if global_settings and global_settings.conf_threshold is not None else 0.40
                
            if iou_threshold is None:
                iou_threshold = global_settings.iou_threshold if global_settings and global_settings.iou_threshold is not None else 0.7
                
        except Exception as e:
            logger.error(f"Error getting AI settings: {e}")
            conf_threshold = 0.25
            iou_threshold = 0.7

        logger.info(f"✅ Menggunakan conf_threshold={conf_threshold} dan iou_threshold={iou_threshold} untuk kamera {cam_id}.")

        model_processor = None
        yolo_classes = None 
        model_all_class_names = [] 
            
    try:
        # Perbarui logika untuk menentukan kelas yang akan dideteksi
        if camera_data.counting_line:
            # Jika counting_line aktif, kita hanya tertarik pada 'person'
            logger.info("⚠️ Pembatasan deteksi: Fokus pada 'person' karena ada garis penghitungan.")
        else:
            logger.info("ℹ️ Tidak ada batasan deteksi. Mendeteksi semua objek.")
        
        # --- Inisialisasi Model ---
        if user_model and user_model.model_type == 'ssdmobilenet':
            logger.info(f"⏳ Mengunduh atau memverifikasi file SSD MobileNetV3...")
            download_success, model_path, config_path, labels_path = download_ssdmobilenet_if_not_exists()
            if download_success:
                logger.info(f"✅ Menggunakan SSD MobileNetV3: {model_path}")
                model_processor = SSDMobileNetProcessor(model_path=model_path, config_path=config_path, labels_path=labels_path)
                model_all_class_names = model_processor.get_class_names()
            else:
                logger.error("❌ Gagal mengunduh file SSD MobileNetV3. Kembali ke YOLOv8n bawaan.")
                download_yolov8n_if_not_exists()
                model_processor = YOLO(os.path.join(UPLOAD_FOLDER, 'yolov8n.pt'))
                model_all_class_names = model_processor.names.values()

        elif user_model and os.path.exists(user_model.file_path):
            if user_model.model_type == 'yolov5':
                logger.info(f"✅ Menggunakan YOLOv5: {user_model.filename}")
                model_processor = YOLOv5Processor(model_path=user_model.file_path)

            elif user_model.model_type == 'yolov8' or user_model.model_type == 'yolo-pose':
                logger.info(f"✅ Menggunakan YOLOv8/YOLO-Pose: {user_model.filename}")
                model_processor = YOLO(user_model.file_path)
                model_all_class_names = model_processor.names.values()
            else:
                logger.error(f"❌ Tipe model '{user_model.model_type}' tidak didukung. Menggunakan YOLOv8n bawaan.")
                download_yolov8n_if_not_exists()
                model_processor = YOLO(os.path.join(UPLOAD_FOLDER, 'yolov8n.pt'))
                model_all_class_names = model_processor.names.values()
        else:
            download_yolov8n_if_not_exists()
            logger.info("✅ Menggunakan model bawaan: yolov8n.pt")
            model_processor = YOLO(os.path.join(UPLOAD_FOLDER, 'yolov8n.pt'))
            model_all_class_names = model_processor.names.values()
            
    except Exception as e:
        socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': f"❌ Gagal memuat model: {e}"})
        logger.error(f"❌ Gagal memuat model: {e}")
        return

    if not model_processor:
        logger.error(f"❌ Gagal menginisialisasi model processor untuk kamera {cam_id}.")
        socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': "❌ Gagal menginisialisasi model AI."})
        return
        
    # --- Inisialisasi Haar Cascade (Langkah 1) ---
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        logger.warning("⚠️ Gagal memuat Haar Cascade: haarcascade_frontalface_default.xml. Face Detection dinonaktifkan.")
        face_cascade = None # Set ke None jika gagal

    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': "❌ Gagal membuka stream kamera."})
        logger.error(f"❌ Gagal membuka stream untuk kamera {cam_id} dari {rtsp_url}")
        return

    socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "✅ AI Live View dimulai."})
    logger.info(f"✅ AI stream untuk kamera {cam_id} dimulai.")

    with app.app_context():
        today = datetime.date.today()
        daily_in = Count.query.filter(Count.camera_id == cam_id, Count.direction == 'in', db.func.date(Count.timestamp) == today).count()
        daily_out = Count.query.filter(Count.camera_id == cam_id, Count.direction == 'out', db.func.date(Count.timestamp) == today).count()

    with lock:
        total_counts[cam_id] = {'in': daily_in, 'out': daily_out}
    socketio.emit('ai_count_update', {'cam_id': cam_id, 'counts': total_counts[cam_id]})
    
    tracked_objects = {}
    
    video_writer = None
    is_recording = False
    output_filename = None
    
    running = True
    while running:
        if stop_event.is_set():
            logger.info(f"🛑 Thread AI untuk kamera {cam_id} dihentikan.")
            socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "🛑 AI Live View dihentikan."})
            break

        ret, frame = cap.read()
        if not ret:
            logger.warning(f"⚠️ Frame kosong dari kamera {cam_id}. Mencoba reconnect...")
            cap.release()
            time.sleep(1)
            cap = cv2.VideoCapture(rtsp_url)
            if not cap.isOpened():
                socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': "❌ Gagal reconnect ke kamera."})
                break
            continue

        with app.app_context():
            camera_data = Camera.query.get(cam_id)
            if not camera_data or not camera_data.is_ai_enabled:
                running = False
                continue
            
            global_settings = GlobalSettings.query.first()
        
        # --- Panggilan process_frame_with_ai (Langkah 2) ---
        annotated_frame, detections_info, detected_alarm_object = process_frame_with_ai(
            frame, model_processor, camera_data, tracked_objects, app, socketio, cam_id, 
            yolo_classes, conf_threshold, iou_threshold, model_all_class_names, face_cascade
        )

        with lock:
            now = time.time()
            if detected_alarm_object and camera_data.alarm_action:
                if now - alarm_cooldowns.get(cam_id, 0) > 10:
                    logger.warning(f"🚨 ALARM: Objek alarm terdeteksi di kamera {cam_id}! Mengirim aksi...")
                    
                    with app.app_context():
                        try:
                            alarm_log_entry = AlarmLog(camera_id=cam_id, camera_name=camera_name, message=f"Objek '{camera_data.alarm_trigger}' terdetksi")
                            db.session.add(alarm_log_entry)
                            db.session.commit()
                            logger.info("✅ Log alarm berhasil dicatat di database.")
                        except Exception as db_e:
                            db.session.rollback()
                            logger.error(f"❌ Gagal mencatat log alarm ke database: {db_e}")
                    
                    action_thread = threading.Thread(target=execute_action, args=(camera_data.alarm_action, camera_data))
                    action_thread.start()
                    
                    alarm_cooldowns[cam_id] = now
                else:
                    logger.info(f"⏳ Objek alarm terdeteksi, masih dalam masa cooldown.")

            if detected_alarm_object:
                sanitized_camera_name = camera_name.replace(" ", "_").lower()
                if global_settings and global_settings.save_screenshots and now - screenshot_cooldowns.get(cam_id, 0) > 10:
                    screenshot_folder = global_settings.screenshot_folder or 'apps/static/screenshots'
                    os.makedirs(screenshot_folder, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{sanitized_camera_name}_alarm_{timestamp}.jpg"
                    filepath = os.path.join(screenshot_folder, filename)
                    cv2.imwrite(filepath, annotated_frame)
                    logger.info(f"📸 Screenshot alarm berhasil disimpan: {filepath}")
                    screenshot_cooldowns[cam_id] = now
                    
                    with app.app_context():
                        try:
                            new_file_record = FileRecord(
                                cam_id=cam_id,
                                filename=filename,
                                file_type='screenshot',
                                date_created=datetime.date.today(),
                                time_created=datetime.datetime.now().time()
                            )
                            db.session.add(new_file_record)
                            db.session.commit()
                            logger.info("✅ Entri file record screenshot berhasil disimpan di database.")
                        except Exception as e:
                            db.session.rollback()
                            logger.error(f"❌ Gagal menyimpan entri file record screenshot: {e}")
                
                if global_settings and global_settings.save_videos and not is_recording:
                    video_folder = global_settings.video_folder or 'apps/static/videos'
                    os.makedirs(video_folder, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_filename = f"{sanitized_camera_name}_alarm_{timestamp}.mp4"
                    output_path = os.path.join(video_folder, output_filename)
                    
                    fps = cap.get(cv2.CAP_PROP_FPS) or 20
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    
                    video_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                    is_recording = True
                    logger.info(f"🔴 Merekam video alarm dimulai: {output_path}")

            if is_recording:
                video_writer.write(annotated_frame)
                if not detected_alarm_object:
                    if video_writer:
                        video_writer.release()
                        logger.info("⏹️ Perekaman video alarm dihentikan.")
                        
                        input_path = os.path.join(video_folder, output_filename)
                        optimized_output_path = input_path.replace('.mp4', '_browser.mp4')
                        
                        # Use a new thread for transcoding to avoid blocking the main stream
                        def transcode_and_save():
                            command = [
                                'ffmpeg', '-i', input_path,
                                '-movflags', 'faststart',
                                '-c:v', 'libx264',
                                '-preset', 'fast',
                                '-c:a', 'aac',
                                optimized_output_path
                            ]
                            try:
                                subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
                                logger.info(f"✅ Video berhasil di-transcode: {optimized_output_path}")
                                os.remove(input_path)
                                os.rename(optimized_output_path, input_path)
                                logger.info("✅ File asli dihapus dan file baru diganti namanya.")
                                
                                with app.app_context():
                                    try:
                                        new_file_record = FileRecord(
                                            cam_id=cam_id,
                                            filename=output_filename,
                                            file_type='video',
                                            date_created=datetime.date.today(),
                                            time_created=datetime.datetime.now().time()
                                        )
                                        db.session.add(new_file_record)
                                        db.session.commit()
                                        logger.info("✅ Entri file record video berhasil disimpan di database.")
                                    except Exception as e:
                                        db.session.rollback()
                                        logger.error(f"❌ Gagal menyimpan entri file record video: {e}")
                                
                            except subprocess.CalledProcessError as e:
                                logger.error(f"❌ Gagal mentranscode video dengan FFmpeg: {e}")
                        
                        transcode_thread = threading.Thread(target=transcode_and_save)
                        transcode_thread.start()
                        
                    is_recording = False
                    video_writer = None
            
            if len(client_sids.get(cam_id, set())) > 0:
                if camera_data.counting_line and camera_data.counting_line != "":
                    try:
                        line_coords = json.loads(camera_data.counting_line)
                        draw_counting_line(annotated_frame, line_coords)
                    except (json.JSONDecodeError, TypeError):
                        logger.error(f"❌ Gagal memuat koordinat garis untuk kamera {cam_id}.")

                _, jpeg = cv2.imencode('.jpg', annotated_frame)
                b64_frame = base64.b64encode(jpeg.tobytes()).decode('utf-8')

                sids_to_emit = list(client_sids.get(cam_id, set()))
                with app.app_context():
                    for sid in sids_to_emit:
                        socketio.emit('ai_frame', {'cam_id': cam_id, 'frame': b64_frame}, room=sid)
        
        time.sleep(0.03)

    cap.release()
    if video_writer:
        video_writer.release()
        logger.info("⏹️ Perekaman video dihentikan karena thread berhenti.")
        # Simpan file record video terakhir
        with app.app_context():
            try:
                if output_filename:
                    new_file_record = FileRecord(
                        cam_id=cam_id,
                        filename=output_filename,
                        file_type='video',
                        date_created=datetime.date.today(),
                        time_created=datetime.datetime.now().time()
                    )
                    db.session.add(new_file_record)
                    db.session.commit()
                    logger.info("✅ Entri file record video berhasil disimpan karena thread berhenti.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"❌ Gagal menyimpan entri file record video saat thread berhenti: {e}")

    logger.info(f"🛑 Thread AI untuk kamera {cam_id} dihentikan.")
    socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "🛑 AI Live View dihentikan."})


# -------------------------------------------------------------
# Fungsi Pemrosesan Frame Utama
# -------------------------------------------------------------
def process_frame_with_ai(frame, model_processor, camera_data, tracked_objects, app, socketio, cam_id, yolo_classes, conf_threshold, iou_threshold, model_all_class_names, face_cascade):
    """
    Melakukan deteksi objek, pelacakan, dan logika bisnis (penghitungan/alarm) pada satu frame.
    """
    from apps import db 

    triggers = [camera_data.alarm_trigger] if isinstance(camera_data.alarm_trigger, str) else camera_data.alarm_trigger or []
    
    all_detections = []
    
    # --- Pemrosesan Deteksi Berdasarkan Tipe Model ---
    if isinstance(model_processor, YOLO):
        results = model_processor.track(
            frame, 
            persist=True, 
            classes=None, 
            verbose=False, 
            conf=conf_threshold, 
            iou=iou_threshold
        )
        current_frame_detections = {}
        
        if results and results[0].boxes and results[0].boxes.id is not None:
            for box, id, cls, conf in zip(
                results[0].boxes.xyxy.cpu().numpy().astype(int), 
                results[0].boxes.id.cpu().numpy().astype(int), 
                results[0].boxes.cls.cpu().numpy().astype(int),
                results[0].boxes.conf.cpu().numpy().astype(float)
            ):
                name = model_processor.names.get(cls)
                if name:
                    obj_id = int(id)
                    current_center = (int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2))
                    
                    det_data = {
                        'box': box,
                        'id': obj_id,  
                        'name': name,
                        'center': current_center,
                        'conf': conf
                    }
                    
                    with lock:
                        if obj_id in tracked_objects:
                            det_data['prev_center'] = tracked_objects[obj_id]['center']
                            det_data['counted'] = tracked_objects[obj_id].get('counted', False)
                        else:
                            det_data['prev_center'] = None
                            det_data['counted'] = False
                        
                    current_frame_detections[obj_id] = det_data
        
        with lock:
            tracked_objects.clear()
            tracked_objects.update(current_frame_detections)
        
        all_detections = list(current_frame_detections.values())

    elif isinstance(model_processor, (YOLOv5Processor, SSDMobileNetProcessor)):
        raw_detections = model_processor.process_frame(frame)
        
        detections_filtered_by_conf = [d for d in raw_detections if d['confidence'] >= conf_threshold]

        tracking_distance_threshold = 100 
        
        temp_tracked_objects = {}
        
        for det in detections_filtered_by_conf:
            min_dist = float('inf')
            matched_id = None
            
            with lock:
                for obj_id, last_obj in tracked_objects.items():
                    if det['name'] == last_obj.get('name'):
                        dist = math.dist(det['center'], last_obj['center'])
                        if dist < min_dist and dist < tracking_distance_threshold:
                            min_dist = dist
                            matched_id = obj_id
            
            if matched_id:
                det['id'] = matched_id
                with lock:
                    if matched_id in tracked_objects:
                        det['prev_center'] = tracked_objects[matched_id]['center']
                        det['counted'] = tracked_objects[matched_id].get('counted', False)
                    else:
                        det['prev_center'] = None
                        det['counted'] = False
            else:
                new_id = 0
                with lock:
                    new_id = max(tracked_objects.keys()) + 1 if tracked_objects else 1
                det['id'] = new_id
                det['prev_center'] = None
                det['counted'] = False
            
            temp_tracked_objects[det['id']] = det
            all_detections.append(det)

        with lock:
            tracked_objects.clear()
            tracked_objects.update(temp_tracked_objects)
    
    else: # Fallback jika model_processor tidak dikenal
        logger.error(f"❌ Model processor tidak dikenal: {type(model_processor)}")
        return frame, [], False
    
    # --- LOGIKA KONDISIONAL BARU: FACE DETECTION (Haar Cascade) (Langkah 3) ---
    detected_faces = []
    # Deteksi wajah hanya jika face_cascade dimuat dan fitur diaktifkan di konfigurasi kamera
    if face_cascade and camera_data.is_face_detection_enabled:
        try:
            # Haar Cascade bekerja paling baik pada grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Deteksi wajah
            faces = face_cascade.detectMultiScale(
                gray, 
                scaleFactor=1.1, 
                minNeighbors=5, 
                minSize=(30, 30), 
                flags=cv2.CASCADE_SCALE_IMAGE
            )

            # Ubah format deteksi wajah agar sesuai dengan all_detections
            for (x, y, w, h) in faces:
                x1, y1, x2, y2 = x, y, x + w, y + h
                center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                
                # Gunakan ID negatif untuk wajah agar tidak bentrok dengan ID objek yang dilacak
                temp_face_id = -(len(detected_faces) + 1) 
                
                face_data = {
                    'box': (x1, y1, x2, y2),
                    'id': temp_face_id, 
                    'name': 'face',
                    'center': center,
                    'conf': 0.95 
                }
                detected_faces.append(face_data)
        except Exception as e:
            logger.error(f"❌ Error saat melakukan face detection: {e}")

    # Gabungkan deteksi wajah dengan deteksi objek utama
    all_detections.extend(detected_faces)
    detections_to_process = all_detections # Sekarang detections_to_process mencakup objek dan wajah

    is_people_counting_active = camera_data.counting_line is not None and camera_data.counting_line != ""
    is_people_counting_inactive = not camera_data.counting_line

    
    # Filter deteksi untuk people counting atau alarm
    if is_people_counting_active:
        # Hanya 'person' yang dihitung
        detections_to_process = [d for d in all_detections if d.get('name') == 'person']

    
    # --- Logika People Counting ---
    if is_people_counting_active:
        try:
            line_coords = json.loads(camera_data.counting_line)
            h, w, _ = frame.shape
            line_start = (int(line_coords['x1'] * w), int(line_coords['y1'] * h))
            line_end = (int(line_coords['x2'] * w), int(line_coords['y2'] * h))
            
            for obj_data in detections_to_process:
                obj_id = obj_data['id']
                
                with lock:
                    obj_in_tracked = obj_id in tracked_objects
                
                if obj_in_tracked and 'prev_center' in tracked_objects[obj_id] and tracked_objects[obj_id]['prev_center'] is not None:
                    with lock:
                        current_center = tracked_objects[obj_id]['center']
                        prev_center = tracked_objects[obj_id]['prev_center']
                    
                    if check_line_crossing(line_start, line_end, prev_center, current_center):
                        with lock:
                            counted_status = tracked_objects[obj_id].get('counted', False)

                        if not counted_status:
                            cross_product_old = (line_end[0] - line_start[0]) * (prev_center[1] - line_start[1]) - (line_end[1] - line_start[1]) * (prev_center[0] - line_start[0])
                            cross_product_new = (line_end[0] - line_start[0]) * (current_center[1] - line_start[1]) - (line_end[1] - line_start[1]) * (current_center[0] - line_start[0])
                            
                            direction = 'out' if cross_product_old > 0 else 'in'

                            with app.app_context():
                                try:
                                    camera_data = Camera.query.get(cam_id)
                                    camera_name = camera_data.name if camera_data else "Kamera Dihapus"
                                    count_entry = Count(camera_id=cam_id, camera_name=camera_name, direction=direction)
                                    db.session.add(count_entry)
                                    db.session.commit()
                                    logger.info(f"✅ Count berhasil dicatat: {direction} untuk objek ID {obj_id} di kamera {cam_id}.")

                                    with lock:
                                        if cam_id not in total_counts:
                                            total_counts[cam_id] = {'in': 0, 'out': 0}
                                        total_counts[cam_id][direction] += 1
                                        tracked_objects[obj_id]['counted'] = True
                                        
                                    socketio.emit('ai_count_update', {'cam_id': cam_id, 'counts': total_counts[cam_id]})
                                    
                                except Exception as db_e:
                                    db.session.rollback()
                                    logger.error(f"❌ Gagal mencatat hitungan ke database: {db_e}")

            # Reset status 'counted' jika objek sudah cukup jauh dari garis
            reset_threshold = 50 
            with lock:
                obj_ids_to_check = list(tracked_objects.keys())

            for obj_id in obj_ids_to_check:
                with lock:
                    obj_data = tracked_objects.get(obj_id)
                if not obj_data:
                    continue

                center = obj_data.get('center')
                if center and obj_data.get('counted', False):
                    line_length = math.sqrt((line_end[1] - line_start[1])**2 + (line_end[0] - line_start[0])**2)
                    if line_length > 0:
                        distance = abs((line_end[1] - line_start[1]) * center[0] - 
                                            (line_end[0] - line_start[0]) * center[1] +
                                            line_end[0] * line_start[1] - line_end[1] * line_start[0]) / line_length
                    else:
                        distance = float('inf') 
                    
                    if distance > reset_threshold:
                        with lock:
                            if obj_id in tracked_objects:
                                tracked_objects[obj_id]['counted'] = False
                        logger.info(f"🔄 Reset status hitung untuk objek ID {obj_id}.")
                
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"❌ Gagal memuat atau memproses koordinat garis untuk kamera {cam_id}: {e}")
            detections_to_process = all_detections
    
    # --- Anotasi Frame ---
    annotated_frame = frame.copy()
    
    # Deteksi YOLO/SSD dan Face Detection di `all_detections`
    for obj_data in all_detections:
        name, box, obj_id = obj_data['name'], obj_data['box'], obj_data.get('id', 'N/A')
        x1, y1, x2, y2 = box
        
        color = (0, 255, 0) # Hijau default
        label = f'{name} ID:{obj_id}'
        
        if name == 'face':
            color = (0, 255, 255) # Kuning untuk wajah
            label = 'Wajah'
        elif triggers and name in triggers:
            color = (0, 0, 255) # Merah untuk alarm
            
        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated_frame, label, (x1, max(y1 - 10, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Gambar titik tengah hanya untuk objek yang dilacak (bukan wajah Haar Cascade, ID negatif)
        if obj_id > 0 and (is_people_counting_active or is_people_counting_inactive): 
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            cv2.circle(annotated_frame, (cx, cy), 5, (0, 255, 255), -1) 
    
    # Tentukan apakah ada objek alarm yang terdeteksi
    detected_alarm_object = any(d['name'] in triggers for d in all_detections)
    
    return annotated_frame, all_detections, detected_alarm_object
