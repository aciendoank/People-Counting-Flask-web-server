# apps/home/ai_processor.py
# -*- encoding: utf-8 -*-
import os
import cv2
import threading
import time
import json
import logging
import base64
import requests
import datetime
import subprocess
from ultralytics import YOLO
from flask_socketio import SocketIO
import subprocess
from .models import AlarmLog
from .ssd_mobilenet import SSDMobileNetProcessor



# Inisialisasi logger untuk output yang lebih jelas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Definisikan folder tempat menyimpan file yang diunggah
UPLOAD_FOLDER = 'apps/static/models'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Variabel global untuk menyimpan hitungan per kamera
total_counts = {}

# Variabel global untuk menyimpan waktu terakhir alarm dikirim per kamera (cooldown)
alarm_cooldowns = {}
screenshot_cooldowns = {} # Tambahkan cooldown untuk screenshot

# Fungsi untuk mengunduh model bawaan jika tidak ada atau rusak
def download_yolov8n_if_not_exists():
    default_model_path = os.path.join(UPLOAD_FOLDER, 'yolov8n.pt')
    
    # Cek apakah model sudah ada dan ukurannya valid (> 1MB)
    if os.path.exists(default_model_path) and os.path.getsize(default_model_path) > 1024 * 1024:
        logger.info("✅ Model bawaan yolov8n.pt sudah ada dan valid.")
        return

    logger.info("Model bawaan yolov8n.pt tidak ditemukan atau rusak. Mengunduh...")
    
    try:
        # Panggil YOLO untuk mengunduh model ke cache lokal Ultralytics
        YOLO('yolov8n.pt') 
        # Tentukan jalur cache ultralytics
        model_source_path = os.path.join(os.path.expanduser('~'), '.cache/ultralytics/models/yolov8n.pt')
        
        if os.path.exists(model_source_path):
            logger.info(f"✅ Model ditemukan di cache: {model_source_path}")
            # Pindahkan model dari cache ke folder aplikasi
            os.replace(model_source_path, default_model_path)
            logger.info(f"✅ Model berhasil dipindahkan ke: {default_model_path}")
        else:
            logger.error(f"❌ File yolov8n.pt tidak ditemukan di cache setelah mencoba mengunduh. Jalur yang dicari: {model_source_path}")
            logger.warning("Silakan pastikan koneksi internet stabil atau coba unggah model secara manual.")

    except Exception as e:
        logger.error(f"❌ Gagal mengunduh atau memindahkan model yolov8n.pt: {e}")

# Fungsi untuk menggambar garis dan label 'IN'/'OUT' di tengah
def draw_counting_line(frame, line_coords):
    if line_coords and 'x1' in line_coords and 'y1' in line_coords and 'x2' in line_coords and 'y2' in line_coords:
        h, w, _ = frame.shape
        start_point = (int(line_coords['x1'] * w), int(line_coords['y1'] * h))
        end_point = (int(line_coords['x2'] * w), int(line_coords['y2'] * h))
        
        # Menggambar garis
        cv2.line(frame, start_point, end_point, (0, 0, 255), 2)

        # Menghitung titik tengah garis untuk penempatan teks
        mid_point_x = int((start_point[0] + end_point[0]) / 2)
        mid_point_y = int((start_point[1] + end_point[1]) / 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.4
        font_thickness = 1
        text_color = (255, 255, 255) # Merah

        # Menentukan offset untuk penempatan teks
        dx = end_point[0] - start_point[0]
        dy = end_point[1] - start_point[1]
        
        offset = 20
        length = (dx**2 + dy**2)**0.5
        if length == 0:
            return
        
        offset_x = int((-dy / length) * offset)
        offset_y = int((dx / length) * offset)

        # Posisi untuk teks 'IN' (satu sisi garis) dan 'OUT' (sisi lainnya)
        in_pos = (mid_point_x + offset_x, mid_point_y + offset_y)
        cv2.putText(frame, 'IN', in_pos, font, font_scale, text_color, font_thickness, cv2.LINE_AA)

        out_pos = (mid_point_x - offset_x, mid_point_y - offset_y)
        cv2.putText(frame, 'OUT', out_pos, font, font_scale, text_color, font_thickness, cv2.LINE_AA)

# Fungsi untuk mengecek perpotongan garis
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


# Fungsi untuk mengeksekusi kode aksi dari database
def execute_action(action_code, camera_data):
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
            if response.status_code == 200:
                logger.info(f"✅ Webhook berhasil dikirim ke {url}")
            else:
                logger.error(f"❌ Gagal mengirim webhook ke {url}. Status: {response.status_code}, Respons: {response.text}")
                
        elif action_type == 'custom_script':
            command = action_data.get('command')
            if command:
                subprocess.run(command, shell=True, check=True) # check=True akan raise exception jika command gagal
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
# AI Streaming
# -------------------------------
def ai_stream(socketio, app, cam_id, rtsp_url, stop_event, client_sids):
    from apps import db
    from apps.home.models import Camera, AIModel, Count, GlobalSettings

    # Bagian 1: Inisialisasi (berjalan sekali)
    with app.app_context():
        camera_data = Camera.query.get(cam_id)
        global_settings = GlobalSettings.query.first() # Ambil pengaturan global
        
        if not camera_data:
            logger.error(f"❌ Kamera dengan ID {cam_id} tidak ditemukan di database.")
            socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': f"❌ Kamera ID {cam_id} tidak ditemukan."})
            return

        try:
            user_model = AIModel.query.filter_by(cam_id=cam_id).order_by(AIModel.id.desc()).first()
            
            model_to_use = None
            yolo_classes = None

            if user_model and os.path.exists(user_model.file_path):
                model_to_use = user_model.file_path
                logger.info(f"✅ Menggunakan model yang diunggah pengguna: {user_model.filename}")
                yolo_classes = None
            else:
                download_yolov8n_if_not_exists()
                model_to_use = os.path.join(UPLOAD_FOLDER, 'yolov8n.pt')
                logger.info("✅ Menggunakan model bawaan: yolov8n.pt")
                if camera_data.counting_line:
                    yolo_classes = [0]
                    logger.info("⚠️ Batasan deteksi: hanya 'person' karena ada garis penghitungan.")
                else:
                    yolo_classes = None
                    logger.info("ℹ️ Tidak ada batasan deteksi. Mendeteksi semua objek.")
            
            model = YOLO(model_to_use)
        
        except Exception as e:
            socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'error', 'message': f"❌ Gagal memuat model: {e}"})
            logger.error(f"❌ Gagal memuat model {model_to_use}: {e}")
            return

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

    total_counts[cam_id] = {'in': daily_in, 'out': daily_out}
    socketio.emit('ai_count_update', {'cam_id': cam_id, 'counts': total_counts[cam_id]})
    
    tracked_objects = {}
    
    # Variabel untuk perekaman video
    video_writer = None
    is_recording = False
    
    # Bagian 2: Loop Utama (berjalan terus-menerus)
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
            
            # Ambil kembali pengaturan dari database setiap loop untuk memastikan update
            global_settings = GlobalSettings.query.first()
            alarm_trigger = camera_data.alarm_trigger
            alarm_action = camera_data.alarm_action
            counting_line_json = camera_data.counting_line

        line_coords = None
        if counting_line_json:
            try:
                line_coords = json.loads(counting_line_json)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"❌ Gagal memuat koordinat garis untuk kamera {cam_id}: {e}")
        
        results = model.track(frame, persist=True, classes=yolo_classes)
        
        annotated_frame = results[0].plot()

        detected_alarm_object = False
        if results and results[0].boxes and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
            ids = results[0].boxes.id.cpu().numpy().astype(int)
            clses = results[0].boxes.cls.cpu().numpy().astype(int)
            
            for box, id, cls in zip(boxes, ids, clses):
                obj_name = model.names[cls]
                
                if alarm_trigger and obj_name == alarm_trigger:
                    detected_alarm_object = True
                    now = time.time()

                    # Logic untuk alarm (webhook, custom script)
                    last_alarm_time = alarm_cooldowns.get(cam_id, 0)
                    if now - last_alarm_time > 10: # Cooldown 10 detik
                        logger.warning(f"🚨 ALARM: '{obj_name}' terdeteksi di kamera {cam_id}! Mengirim aksi...")
                        with app.app_context():
                            try:
                                alarm_log_entry = AlarmLog(
                                    camera_id=cam_id,
                                    message=f"'{obj_name}' terdeteksi",
                                    #object_type=obj_name
                                )
                                db.session.add(alarm_log_entry)
                                db.session.commit()
                                logger.info(f"✅ Log alarm berhasil dicatat di database.")
                            except Exception as db_e:
                                db.session.rollback()
                                logger.error(f"❌ Gagal mencatat log alarm ke database: {db_e}")
                        
                        execute_action(alarm_action, camera_data)
                        alarm_cooldowns[cam_id] = now
                    else:
                        logger.info(f"⏳ Alarm '{obj_name}' terdeteksi, masih dalam masa cooldown.")

                    # Logic untuk menyimpan screenshot
                    last_screenshot_time = screenshot_cooldowns.get(cam_id, 0)
                    if global_settings.save_screenshots and now - last_screenshot_time > 10: # Cooldown 10 detik
                        screenshot_folder = global_settings.screenshot_folder or 'apps/static/screenshots'
                        os.makedirs(screenshot_folder, exist_ok=True)
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"cam_{cam_id}_alarm_{timestamp}.jpg"
                        filepath = os.path.join(screenshot_folder, filename)
                        cv2.imwrite(filepath, annotated_frame)
                        logger.info(f"📸 Screenshot alarm berhasil disimpan: {filepath}")
                        screenshot_cooldowns[cam_id] = now

                    # Logic untuk memulai perekaman video
                    if global_settings.save_videos and not is_recording:
                        video_folder = global_settings.video_folder or 'apps/static/videos'
                        os.makedirs(video_folder, exist_ok=True)
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        output_filename = f"cam_{cam_id}_alarm_{timestamp}.mp4"
                        output_path = os.path.join(video_folder, output_filename)
                        
                        fps = cap.get(cv2.CAP_PROP_FPS) or 20 # Gunakan 20 FPS sebagai default
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v') # Codec untuk .mp4
                        
                        video_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                        is_recording = True
                        logger.info(f"🔴 Merekam video alarm dimulai: {output_path}")

                if obj_name == 'person' and line_coords:
                    center_x = (box[0] + box[2]) / 2
                    center_y = (box[1] + box[3]) / 2 
                    current_pos = (int(center_x), int(center_y))
                    
                    cv2.circle(annotated_frame, current_pos, 5, (0, 255, 0), -1)

                    if id not in tracked_objects:
                        tracked_objects[id] = {'last_pos': current_pos}
                    else:
                        last_pos = tracked_objects[id]['last_pos']
                        
                        line_p1 = (int(line_coords['x1'] * frame.shape[1]), int(line_coords['y1'] * frame.shape[0]))
                        line_p2 = (int(line_coords['x2'] * frame.shape[1]), int(line_coords['y2'] * frame.shape[0]))
                        
                        if check_line_crossing(line_p1, line_p2, last_pos, current_pos):
                            cross_product_old = (line_p2[0] - line_p1[0]) * (last_pos[1] - line_p1[1]) - (line_p2[1] - line_p1[1]) * (last_pos[0] - line_p1[0])
                            cross_product_new = (line_p2[0] - line_p1[0]) * (current_pos[1] - line_p1[1]) - (line_p2[1] - line_p1[1]) * (current_pos[0] - line_p1[0])

                            if cross_product_old * cross_product_new < 0:
                                direction = 'out' if cross_product_old > 0 else 'in'
                                
                                total_counts[cam_id][direction] += 1
                                logger.info(f"➡️ Orang '{direction}': {total_counts[cam_id][direction]} (ID: {id})")

                                try:
                                    with app.app_context():
                                        new_count = Count(camera_id=cam_id, direction=direction)
                                        db.session.add(new_count)
                                        #update_dashboard_count()
                                        db.session.commit()
                                        logger.info(f"✅ Hitungan '{direction}' berhasil dicatat di database.")
                                except Exception as db_e:
                                    with app.app_context():
                                        db.session.rollback()
                                        logger.error(f"❌ Gagal mencatat hitungan ke database: {db_e}")

                                socketio.emit('ai_count_update', {'cam_id': cam_id, 'counts': total_counts[cam_id]})
                            
                        tracked_objects[id]['last_pos'] = current_pos
        
        current_ids = set(ids) if 'ids' in locals() else set()
        tracked_objects = {id: data for id, data in tracked_objects.items() if id in current_ids}
        
        # Logic untuk menghentikan perekaman video jika objek tidak lagi terdeteksi
        if is_recording and not detected_alarm_object:
                if video_writer:
                        video_writer.release()
                        logger.info("⏹️ Perekaman video alarm dihentikan.")
                        
                        input_path = output_path
                        # Ganti codec video dengan H.264 dan audio dengan AAC
                        optimized_output_path = output_path.replace('.mp4', '_browser.mp4')
                        command = [
                                'ffmpeg',
                                '-i', input_path,
                                '-movflags', 'faststart',
                                '-c:v', 'libx264', # <-- Transcode video ke H.264
                                '-preset', 'fast',  # <-- Tambahkan preset untuk kecepatan transcoding
                                '-c:a', 'aac',    # <-- Transcode audio ke AAC (jika ada)
                                optimized_output_path
                                ]

                        try:
                                subprocess.run(command, check=True)
                                logger.info(f"✅ Video berhasil di-transcode: {optimized_output_path}")
                                os.remove(input_path)
                                os.rename(optimized_output_path, input_path)
                                logger.info("✅ File asli dihapus dan file baru diganti namanya.")
                        except subprocess.CalledProcessError as e:
                                logger.error(f"❌ Gagal mentranscode video dengan FFmpeg: {e}")
                                logger.error(f"Perintah gagal: {' '.join(command)}")

                        is_recording = False
                        video_writer = None

        # Tulis frame ke file video jika sedang merekam
        if is_recording and video_writer:
            video_writer.write(annotated_frame)
        
        if len(client_sids.get(cam_id, set())) > 0:
            if line_coords:
                draw_counting_line(annotated_frame, line_coords)

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
    logger.info(f"🛑 Thread AI untuk kamera {cam_id} dihentikan.")
    socketio.emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "🛑 AI Live View dihentikan."})