# apps/home/routes.py
# -*- encoding: utf-8 -*-
from apps import db, socketio
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory
from flask_login import login_required, current_user, UserMixin
from jinja2 import TemplateNotFound
from apps.home.models import Camera, AIModel, GlobalSettings, Count, AlarmLog
from werkzeug.utils import secure_filename
import os
import base64
import cv2
import datetime
import eventlet
from flask import jsonify, Response ,Flask ,flash
from datetime import date
from threading import Thread
import threading
import time
from ultralytics import YOLO
from flask_socketio import emit
import json
import logging
from .ai_processor import ai_stream, download_yolov8n_if_not_exists
from apps.authentication.models import Users, Role

logger = logging.getLogger('ai-app')
# Inisialisasi logger untuk output yang lebih jelas
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi blueprint untuk rute-rute aplikasi
blueprint = Blueprint('home_blueprint', __name__, template_folder='templates')

# Gunakan dictionary untuk menyimpan thread dan event
background_data_sender = {}
camera_threads = {}
camera_stop_events = {}
camera_live_view_threads = {}
camera_live_view_stop_events = {}
active_ai_streams = {}
camera_ai_status = {}
# Kamus untuk melacak SID klien yang meminta live view.
client_sids = {}
camera_thread_lock = threading.Lock()
dashboard_thread = None
dashboard_stop_event = threading.Event()
thread_lock = threading.Lock()

# Definisikan folder tempat menyimpan file yang diunggah
UPLOAD_FOLDER = 'apps/static/models'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Panggil fungsi ini saat aplikasi dimulai
download_yolov8n_if_not_exists()

# -------------------------------
# Streaming Video Sederhana (Tanpa AI)
# -------------------------------
def simple_stream(app, cam_id, rtsp_url, stop_event):
    """
    Thread untuk streaming video sederhana tanpa deteksi AI.
    """
    with app.app_context():
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            logger.error(f"❌ Gagal membuka stream sederhana untuk kamera {cam_id} dari {rtsp_url}")
            socketio.emit('error_message', {'message': "❌ Gagal membuka stream kamera. Periksa URL."})
            return

        logger.info(f"✅ Stream sederhana untuk kamera {cam_id} dimulai.")
        socketio.emit('log', {'message': "✅ Live View dimulai."})

        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"⚠️ Frame kosong dari kamera {cam_id}. Mencoba reconnect...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(rtsp_url)
                if not cap.isOpened():
                    logger.error("❌ Gagal reconnect ke kamera.")
                    socketio.emit('error_message', {'message': "❌ Gagal reconnect ke kamera."})
                    break
                continue

            # Mengubah frame menjadi format JPEG
            _, jpeg = cv2.imencode('.jpg', frame)
            b64_frame = base64.b64encode(jpeg.tobytes()).decode('utf-8')
            socketio.emit('frame', {'cam_id': cam_id, 'frame': b64_frame})
            
            # Kontrol frame rate
            time.sleep(0.05)

        cap.release()
        logger.info(f"🛑 Thread stream sederhana untuk kamera {cam_id} dihentikan.")
        socketio.emit('log', {'message': "🛑 Live View dihentikan."})

# -------------------------------
# Socket.IO Event Handlers 
# -------------------------------
@socketio.on('connect')
def handle_connect():
    client_sid = request.sid
    logger.info(f"Client connected! SID: {client_sid}")
    
    cameras = Camera.query.all()
    status_list = [{'id': cam.id, 'name': cam.name, 'location': cam.location, 'is_ai_enabled': cam.is_ai_enabled} for cam in cameras]
    
    # 🚨 Perbaikan utama: Cek status AI kamera yang sudah aktif
    for cam in cameras:
        if cam.is_ai_enabled:
            # Panggil fungsi helper yang sama untuk memulai atau menambahkan klien ke stream yang sudah ada
            start_ai_stream_for_client(cam.id, client_sid)
            
    emit('initial_status', status_list, room=client_sid)
    
    
# Tambahkan fungsi helper baru untuk memulai stream
def start_ai_stream_for_client(cam_id, client_sid):
    with current_app.app_context():
        camera = Camera.query.get(cam_id)
        if not camera:
            logger.error(f"Kamera ID {cam_id} tidak ditemukan.")
            return

        # Daftarkan SID klien ke daftar penonton
        if cam_id not in client_sids:
            client_sids[cam_id] = set()
        client_sids[cam_id].add(client_sid)
        
        # Mulai thread hanya jika belum berjalan
        if cam_id not in camera_threads or not camera_threads[cam_id].is_alive():
            stop_event = threading.Event()
            camera_stop_events[cam_id] = stop_event
            
            t = threading.Thread(target=ai_stream, args=(socketio, current_app._get_current_object(), cam_id, camera.rtsp_url, stop_event, client_sids))
            t.daemon = True
            t.start()
            camera_threads[cam_id] = t
            logger.info(f"✅ AI thread for camera {cam_id} started on request from SID: {client_sid}")
        else:
            logger.info(f"ℹ️ AI stream for camera {cam_id} is already running. Added client SID {client_sid} to observers.")



@socketio.on('disconnect')
def handle_disconnect():
    client_sid = request.sid
    logger.info(f"Client disconnected! SID: {client_sid}")
    
    for cam_id, sids in list(client_sids.items()):
        if client_sid in sids:
            sids.discard(client_sid)
            # Jangan tambahkan logika untuk menghentikan proses AI di sini.
            # Proses AI akan tetap berjalan selama is_ai_enabled = True.
            break


@socketio.on('update_ai_status')
def handle_update_ai_status(data):
    cam_id = data.get('cam_id')
    is_enabled = data.get('is_enabled')

    if cam_id is None or is_enabled is None:
        logger.warning("Invalid data received for update_ai_status.")
        return

    camera = Camera.query.get(cam_id)
    if not camera:
        logger.error(f"Camera with ID {cam_id} not found.")
        return

    camera.is_ai_enabled = is_enabled
    db.session.commit()
    logger.info(f"AI status for camera {cam_id} updated to {is_enabled} in database.")
    
    if is_enabled:
        start_ai_stream_for_client(cam_id, request.sid)
        emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "✅ AI diaktifkan. Mendeteksi objek dan alarm."})
    else:
        # Hapus SID klien dari daftar penonton
        if cam_id in client_sids:
            client_sids[cam_id].discard(request.sid)

        # Logika Tambahan: Jika dinonaktifkan oleh admin, hentikan thread secara paksa
        if cam_id in camera_stop_events and camera_threads.get(cam_id):
            camera_stop_events[cam_id].set()
            camera_threads.pop(cam_id, None)
            camera_stop_events.pop(cam_id, None)
            logger.info(f"🛑 AI thread for camera {cam_id} stopped forcefully by admin request.")

        emit('ai_status', {'cam_id': cam_id, 'type': 'info', 'message': "🛑 AI tidak aktif. Alarm dan deteksi dihentikan."})

                    

@socketio.on('connect', namespace='/dashboard')
def handle_dashboard_connect():
    today_date = date.today().strftime('%Y-%m-%d')
    counts = Count.query.filter(db.func.date(Count.timestamp) == today_date).all()
    chart_data = {}
    for count in counts:
        cam_id = count.camera_id
        if cam_id not in chart_data:
            chart_data[cam_id] = {'in': 0, 'out': 0}
        chart_data[cam_id][count.direction] += 1
    
    emit('new_count_data', chart_data)

@socketio.on('disconnect', namespace='/dashboard')
def handle_dashboard_disconnect():
    print('Client dasbor terputus dari Socket.IO')



@socketio.on('start_stream')
def handle_start_stream(data):
    """Memulai streaming video sederhana ke klien."""
    cam_id = data.get('cam_id')
    if cam_id not in camera_live_view_threads or not camera_live_view_threads[cam_id].is_alive():
        camera = Camera.query.get(cam_id)        
        if camera:
            stop_event = threading.Event()
            camera_live_view_stop_events[cam_id] = stop_event
            t = threading.Thread(target=simple_stream, args=(current_app._get_current_object(), cam_id, camera.rtsp_url, stop_event))
            t.daemon = True
            t.start()
            camera_live_view_threads[cam_id] = t
            logger.info(f"✅ Simple stream thread for camera {cam_id} started.")

@socketio.on('stop_stream')
def handle_stop_stream(data):
    """Menghentikan streaming video sederhana ke klien."""
    cam_id = data.get('cam_id')
    if cam_id in camera_live_view_stop_events and camera_live_view_threads.get(cam_id):
        camera_live_view_stop_events[cam_id].set()
        camera_live_view_threads.pop(cam_id, None)
        camera_live_view_stop_events.pop(cam_id, None)
        logger.info(f"🛑 Simple stream thread for camera {cam_id} stopped.")


@blueprint.route('/edit_alarm/<int:cam_id>', methods=['POST'])
@login_required
def edit_alarm(cam_id):
    """Menangani permintaan POST untuk memperbarui pengaturan alarm."""
    try:
        camera = Camera.query.get(cam_id)
        if not camera:
            return jsonify({'status': 'error', 'message': 'Kamera tidak ditemukan.'}), 404

        alarm_trigger = request.form.get('alarm-trigger')
        alarm_action = request.form.get('alarm-action')

        camera.alarm_trigger = alarm_trigger if alarm_trigger else None
        camera.alarm_action = alarm_action if alarm_action else None
        db.session.commit()
        
        #if ai_processor:
         #   ai_processor.restart_ai_stream_for_camera(cam_id)
        
        return redirect(url_for('home_blueprint.alarm_settings'))
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Terjadi kesalahan saat memperbarui: {str(e)}'}), 500


@blueprint.route('/delete_alarm/<int:cam_id>', methods=['POST'])
@login_required
def delete_alarm(cam_id):
    """Menangani permintaan POST untuk menghapus pengaturan alarm."""
    try:
        camera = Camera.query.get(cam_id)
        if not camera:
            return jsonify({'status': 'error', 'message': 'Kamera tidak ditemukan.'}), 404

        camera.alarm_trigger = None
        camera.alarm_action = None
        
        db.session.commit()

        flash("alarm berhasil dihapus!", "success")
        return redirect(url_for('home_blueprint.alarm_settings'))
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Terjadi kesalahan saat menghapus: {str(e)}'}), 500


# -------------------------------
# INDEX
# -------------------------------
@blueprint.route('/')
@blueprint.route('/dashboard')
@login_required
def dashboard():
    """
    Menampilkan halaman dashboard utama dengan data kamera dan grafik.
    """
    global dashboard_thread
    global dashboard_stop_event
    global thread_lock

    try:
        cameras = Camera.query.all()
        if not cameras:
            print("Peringatan: Tidak ada kamera yang terdaftar di database.")
            return render_template('home/dashboard.html', cameras=[], error="Tidak ada kamera yang terdaftar.")
        
        # Mulai thread pengirim data jika belum berjalan
        with thread_lock:
            if dashboard_thread is None or not dashboard_thread.is_alive():
                print("✅ Memulai thread pengirim data dasbor...")
                dashboard_stop_event.clear()
                dashboard_thread = Thread(target=background_data_sender, args=(current_app._get_current_object(), dashboard_stop_event,))
                dashboard_thread.daemon = True
                dashboard_thread.start()
        
        # Ambil data hitungan untuk hari ini untuk rendering awal
        today = date.today()
        daily_counts = {}
        for cam in cameras:
            in_count = Count.query.filter(
                Count.camera_id == cam.id,
                Count.direction == 'in',
                db.func.date(Count.timestamp) == today
            ).count()
            
            out_count = Count.query.filter(
                Count.camera_id == cam.id,
                Count.direction == 'out',
                db.func.date(Count.timestamp) == today
            ).count()
            
            daily_counts[cam.id] = {'in': in_count, 'out': out_count}

        return render_template('home/dashboard.html', cameras=cameras, daily_counts=daily_counts)

    except Exception as e:
        print(f"Kesalahan saat memuat dasbor: {e}")
        return render_template('home/dashboard.html', cameras=[], error="Kesalahan saat memuat dasbor.")

# Fungsi yang berjalan di latar belakang untuk mengirim data dasbor
def background_data_sender(app: Flask, stop_event: threading.Event):
    """
    Mengambil data hitungan dan log secara real-time dan mengirimkannya ke klien Socket.IO.
    """
    with app.app_context():
        while not stop_event.is_set():
            live_counts = {}
            latest_counting_logs = []
            latest_alarm_logs = []

            try:
                db_session = db.session()
                today = date.today()

                cameras = db_session.query(Camera).all()
                for cam in cameras:
                    # Kode hitungan per kamera
                    in_count = db_session.query(Count).filter(
                        Count.camera_id == cam.id,
                        Count.direction == 'in',
                        db.func.date(Count.timestamp) == today
                    ).count()
                    
                    out_count = db_session.query(Count).filter(
                        Count.camera_id == cam.id,
                        Count.direction == 'out',
                        db.func.date(Count.timestamp) == today
                    ).count()
                    
                    live_counts[cam.id] = {'in': in_count, 'out': out_count}

                # Mengambil log hitungan
                counting_logs_query = db_session.query(Count).order_by(Count.timestamp.desc()).limit(7).all()
                
                for log in reversed(counting_logs_query):
                    # Cek apakah camera_id bernilai NULL dan tambahkan penanda
                    if log.camera_id is None:
                        display_name = f"{log.camera_name} (Dihapus)"
                    else:
                        display_name = log.camera_name
                    latest_counting_logs.append(f"[{log.timestamp.strftime('%H:%M:%S')}] Kamera {display_name}: Orang '{log.direction}' terdeteksi.")

                # Mengambil log alarm
                alarm_logs_query = db_session.query(AlarmLog).order_by(AlarmLog.timestamp.desc()).limit(7).all()
                
                for log in reversed(alarm_logs_query):
                    # Cek apakah camera_id bernilai NULL dan tambahkan penanda
                    if log.camera_id is None:
                        display_name = f"{log.camera_name} (Dihapus)"
                    else:
                        display_name = log.camera_name
                    latest_alarm_logs.append(f"[{log.timestamp.strftime('%H:%M:%S')}] {log.message} di Kamera {display_name}.")
            
            except Exception as e:
                # Menangani error database
                print(f"❌ Kesalahan database di thread dasbor: {e}")
                db_session.rollback()
            finally:
                db_session.close()

            # Kirim data ke frontend
            dashboard_data = {
                'chart_data': live_counts,
                'counting_logs': latest_counting_logs,
                'alarm_logs': latest_alarm_logs,
            }
            
            socketio.emit('dashboard_data_update', dashboard_data, namespace='/dashboard')
            
            time.sleep(1)



@blueprint.teardown_app_request
def shutdown_session(exception=None):
    db.session.remove()

@blueprint.route('/api/count_data')
def get_count_data():
    date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    camera_id = request.args.get('camera_id', 'all')
    
    query = Count.query.filter(db.func.date(Count.timestamp) == date_str)
    
    if camera_id != 'all':
        try:
            query = query.filter(Count.camera_id == int(camera_id))
        except ValueError:
            return jsonify({'error': 'Invalid camera_id'}), 400
    
    counts = query.all()
    
    chart_data = {}
    for count in counts:
        cam_id = count.camera_id
        if cam_id not in chart_data:
            chart_data[cam_id] = {'in': 0, 'out': 0}
        chart_data[cam_id][count.direction] += 1
    
    return jsonify(chart_data)

# -------------------------------
# CAMERA SETTINGS
# -------------------------------
@blueprint.route('/cam_settings', methods=['GET', 'POST'])
@login_required
def cam_settings():
    if 'Admin' not in [role.name for role in current_user.roles]:
        # Alihkan pengguna jika mereka tidak memiliki peran 'admin'
        flash('Akses ditolak: Anda tidak memiliki izin untuk melihat halaman ini.', 'danger')
        return redirect(url_for('home_blueprint.dashboard'))    
    if request.method == 'POST':
        rtsp_url = request.form.get('rtsp-ip')
        name = request.form.get('camera-name')
        location = request.form.get('camera-location')

        if not rtsp_url:
            flash("RTSP URL wajib diisi!", "danger")
            return redirect(url_for('home_blueprint.cam_settings'))

        # Simpan kamera baru dengan nama dan lokasi
        cam = Camera(rtsp_url=rtsp_url, name=name, location=location, is_ai_enabled=False)
        db.session.add(cam)
        db.session.commit()
        flash("Kamera berhasil ditambahkan!", "success")
        return redirect(url_for('home_blueprint.cam_settings'))

    cameras = Camera.query.all()
    return render_template('home/cam_settings.html',
                           segment='cam_settings',
                           cameras=cameras)


@blueprint.route('/cam_settings/delete/<int:cam_id>', methods=['POST'])
@login_required
def delete_camera(cam_id):
    try:
        # ... (Kode untuk menghentikan thread tetap sama) ...

        # Hapus semua entri di tabel 'count' yang terkait dengan kamera ini
        Count.query.filter_by(camera_id=cam_id).update({'camera_id': None})
        
        # Hapus semua entri di tabel 'alarm_log' yang terkait dengan kamera ini
        AlarmLog.query.filter_by(camera_id=cam_id).update({'camera_id': None})
        
        # Hapus kamera itu sendiri
        cam = Camera.query.get_or_404(cam_id)
        db.session.delete(cam)
        db.session.commit()
        
        flash("Kamera berhasil dihapus!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Gagal menghapus kamera: {e}", "danger")
        
    return redirect(url_for('home_blueprint.cam_settings'))

@blueprint.route('/cam_settings/edit/<int:cam_id>', methods=['POST'])
@login_required
def edit_camera(cam_id):
    cam = Camera.query.get_or_404(cam_id)
    cam.name = request.form.get('camera-name', cam.name)
    cam.location = request.form.get('camera-location', cam.location)
    cam.rtsp_url = request.form.get('rtsp-ip', cam.rtsp_url)
    db.session.commit()
    flash('Camera updated successfully', 'success')
    return redirect(url_for('home_blueprint.cam_settings'))
    

# -------------------------------
# SIMPAN PENGATURAN AI (TERMASUK UNGGAH MODEL OPSIONAL)
# -------------------------------
@blueprint.route('/save-ai-settings', methods=['POST'])
@login_required
def save_ai_settings():
    cam_id = request.form.get('camSelect')
    file = request.files.get('modelFile')
    ai_model_name = request.form.get('aiModel')
    
    # Ambil nilai conf_threshold dan iou_threshold dari formulir
    conf_threshold_str = request.form.get('confThreshold')
    iou_threshold_str = request.form.get('iouThreshold')

    # Konversi nilai ke float, gunakan None jika input kosong atau tidak valid
    conf_threshold = None
    if conf_threshold_str:
        try:
            conf_threshold = float(conf_threshold_str)
        except ValueError:
            flash("❌ Nilai Ambang Kepercayaan tidak valid. Harap masukkan angka.", "danger")
            return redirect(url_for('home_blueprint.ai_settings'))

    iou_threshold = None
    if iou_threshold_str:
        try:
            iou_threshold = float(iou_threshold_str)
        except ValueError:
            flash("❌ Nilai Ambang Tumpang Tindih tidak valid. Harap masukkan angka.", "danger")
            return redirect(url_for('home_blueprint.ai_settings'))
    
    if not cam_id or not ai_model_name:
        flash("Pilih kamera dan model AI terlebih dahulu!", "danger")
        return redirect(url_for('home_blueprint.ai_settings'))

    existing_model = AIModel.query.filter_by(cam_id=cam_id).first()

    # Logika untuk menangani file yang diunggah
    if file and file.filename != '':
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size < 1024 * 1024:
            flash("❌ File model yang diunggah terlalu kecil atau rusak. Silakan coba unduh lagi.", "danger")
            return redirect(url_for('home_blueprint.ai_settings'))
            
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        if existing_model:
            try:
                # Periksa apakah file yang ada adalah model bawaan
                if not existing_model.filename.startswith("yolov8n"):
                     # Hapus file lama hanya jika bukan model bawaan
                    if os.path.exists(existing_model.file_path):
                        os.remove(existing_model.file_path)
                    
                db.session.delete(existing_model)
            except OSError as e:
                logger.error(f"Error menghapus file lama: {e}")
        
        file.save(file_path)
        ai_model = AIModel(
            filename=filename, 
            cam_id=cam_id, 
            file_path=file_path, 
            model_type=ai_model_name,
            conf_threshold=conf_threshold, # Simpan nilai baru
            iou_threshold=iou_threshold   # Simpan nilai baru
        )
        db.session.add(ai_model)
        db.session.commit()
        flash(f"Model {filename} ({ai_model_name}) berhasil diunggah dan disimpan untuk Kamera {cam_id}!", "success")
    else:
        # Jika tidak ada file diunggah, pastikan ada entri model bawaan
        if not existing_model:
            # Gunakan model bawaan berdasarkan pilihan user
            if ai_model_name == 'yolov8':
                default_filename = "yolov8n.pt"
            elif ai_model_name == 'yolov5':
                default_filename = "yolov5n.pt"
            else:
                default_filename = "yolov8n.pt"
                
            default_model = AIModel(
                filename=default_filename, 
                cam_id=cam_id, 
                file_path=os.path.join(UPLOAD_FOLDER, default_filename), 
                model_type=ai_model_name,
                conf_threshold=conf_threshold, # Simpan nilai baru
                iou_threshold=iou_threshold   # Simpan nilai baru
            )
            db.session.add(default_model)
            db.session.commit()
            flash(f"Pengaturan berhasil disimpan untuk Kamera {cam_id}. Menggunakan model bawaan {ai_model_name}.", "success")
        else:
            # Jika tidak ada file baru dan model sudah ada, update saja
            existing_model.model_type = ai_model_name
            existing_model.conf_threshold = conf_threshold # Perbarui nilai
            existing_model.iou_threshold = iou_threshold   # Perbarui nilai
            db.session.commit()
            flash(f"Pengaturan berhasil diperbarui untuk Kamera {cam_id}. Menggunakan model {ai_model_name}.", "success")
    
    return redirect(url_for('home_blueprint.ai_settings'))

# -------------------------------
# HAPUS MODEL AI
# -------------------------------
@blueprint.route('/delete-model/<int:model_id>', methods=['POST'])
@login_required
def delete_model(model_id):
    model = AIModel.query.get_or_404(model_id)
    try:
        # Hanya hapus file fisik jika itu bukan model bawaan
        if not model.filename.startswith("yolov8n"):
            if os.path.exists(model.file_path):
                os.remove(model.file_path)
    except OSError as e:
        flash(f"Error menghapus file: {e.strerror}", "danger")
        
    db.session.delete(model)
    db.session.commit()
    flash("Model berhasil dihapus!", "success")
    return redirect(url_for('home_blueprint.ai_settings'))

# -------------------------------
# PENGATURAN AI
# -------------------------------
@blueprint.route('/ai_settings')
@login_required
def ai_settings():
    if 'Admin' not in [role.name for role in current_user.roles]:
        # Alihkan pengguna jika mereka tidak memiliki peran 'admin'
        flash('Akses ditolak: Anda tidak memiliki izin untuk melihat halaman ini.', 'danger')
        return redirect(url_for('home_blueprint.dashboard'))
    cameras = Camera.query.all()
    models = AIModel.query.all()
    camera_models = {model.cam_id: model for model in models}
    return render_template('home/ai_settings.html',
                           segment='ai_settings',
                           cameras=cameras,
                           models=models)


# -------------------------------
# PEOPLE COUNT
# -------------------------------
@blueprint.route('/people_count')
@login_required
def people_count():
    cameras = Camera.query.all()
    
    for cam in cameras:
        # Check for empty string or None before attempting to load
        if cam.counting_line and isinstance(cam.counting_line, str) and len(cam.counting_line.strip()) > 0:
            try:
                # Attempt to load JSON only if the string is not empty
                cam.counting_line = json.loads(cam.counting_line)
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, explicitly set to None
                cam.counting_line = None
        else:
            # If it's empty or None, set it to None to be safe
            cam.counting_line = None
            
    return render_template('home/people_count.html',
                           segment='people_count',
                           cameras=cameras)


@socketio.on('save_counting_line')
def handle_save_counting_line(data):
    """Menerima dan menyimpan koordinat garis hitung dari frontend."""
    # Menambahkan validasi untuk memastikan ID kamera ada dan valid
    if 'cam_id' not in data or data.get('cam_id') is None:
        emit('error_message', {'message': 'ID kamera tidak ditemukan. Gagal menyimpan garis.'})
        logger.error("❌ ID kamera tidak ditemukan dalam data save_counting_line.")
        return
        
    try:
        cam_id = int(data.get('cam_id'))
    except (ValueError, TypeError) as e:
        emit('error_message', {'message': f'ID kamera tidak valid: {str(e)}'})
        logger.error(f"❌ Gagal mengonversi ID kamera: {e}")
        return

    line_coords = data.get('line_coords')
    
    camera = Camera.query.get(cam_id)
    if camera:
        try:
            camera.counting_line = json.dumps(line_coords)
            db.session.commit()
            emit('line_saved_success', {'cam_id': cam_id, 'line_coords': line_coords})
            logger.info(f"✅ Garis hitung berhasil disimpan untuk Kamera {cam_id}: {line_coords}")
        except Exception as e:
            db.session.rollback()
            emit('error_message', {'message': f'Gagal menyimpan garis: {str(e)}'})
            logger.error(f"❌ Gagal menyimpan garis: {e}")
    else:
        emit('error_message', {'message': f'Kamera dengan ID {cam_id} tidak ditemukan.'})
        logger.warning(f"⚠️ Kamera dengan ID {cam_id} tidak ditemukan di database.")

@socketio.on('clear_line')
def handle_clear_line(data):
    """
    Menghapus koordinat garis hitung dari database.
    """
    if 'cam_id' not in data or data.get('cam_id') is None:
        emit('error_message', {'message': 'ID kamera tidak ditemukan. Gagal menghapus garis.'})
        return
        
    try:
        cam_id = int(data.get('cam_id'))
    except (ValueError, TypeError) as e:
        emit('error_message', {'message': f'ID kamera tidak valid: {str(e)}'})
        return

    camera = Camera.query.get(cam_id)
    if camera:
        try:
            camera.counting_line = None # Set menjadi None untuk menghapus garis
            db.session.commit()
            emit('line_cleared_success', {'cam_id': cam_id})
            logger.info(f"✅ Garis hitung berhasil dihapus untuk Kamera {cam_id}.")
        except Exception as e:
            db.session.rollback()
            emit('error_message', {'message': f'Gagal menghapus garis: {str(e)}'})
            logger.error(f"❌ Gagal menghapus garis: {e}")
    else:
        emit('error_message', {'message': f'Kamera dengan ID {cam_id} tidak ditemukan.'})



# -------------------------------
# AI VIEW
# -------------------------------
@blueprint.route('/ai_view')
@login_required
def ai_view():
    is_admin = False
    if 'Admin' in [role.name for role in current_user.roles]:
        is_admin = True
    cameras = Camera.query.all()
    return render_template('home/ai_view.html',
                           segment='ai_view',
                           cameras=cameras , is_admin=is_admin)

# -------------------------------
# DEV PAGE
# -------------------------------
@blueprint.route('/dev')
@login_required
def dev_page():
    if 'Admin' not in [role.name for role in current_user.roles]:
        # Alihkan pengguna jika mereka tidak memiliki peran 'admin'
        flash('Akses ditolak: Anda tidak memiliki izin untuk melihat halaman ini.', 'danger')
        return redirect(url_for('home_blueprint.dashboard'))
    """
    Menampilkan halaman untuk pengembang, termasuk pengunggahan video dan model.
    """
    cameras = Camera.query.all()
    return render_template('home/dev.html',
                           segment='dev_page',
                           cameras=cameras)

@blueprint.route('/upload_video', methods=['POST'])
@login_required
def upload_video():
    """
    Menangani pengunggahan file video untuk diproses AI.
    """
    if 'video_file' not in request.files:
        flash("Tidak ada file yang diunggah.", "danger")
        return redirect(url_for('home_blueprint.dev_page'))
    
    file = request.files['video_file']
    if file.filename == '':
        flash("Tidak ada file yang dipilih.", "danger")
        return redirect(url_for('home_blueprint.dev_page'))

    if file:
        filename = secure_filename(file.filename)
        upload_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(upload_path)
        
        # Simpan informasi video ke database
        video_cam = Camera(name=filename, rtsp_url=upload_path, location="Dev", is_ai_enabled=False)
        db.session.add(video_cam)
        db.session.commit()
        
        flash("Video berhasil diunggah dan disimpan sebagai kamera baru!", "success")
    return redirect(url_for('home_blueprint.dev_page'))

@blueprint.route('/upload_model', methods=['POST'])
@login_required
def upload_model():
    """
    Menangani pengunggahan model AI khusus.
    """
    if 'ai_model_file' not in request.files:
        flash("Tidak ada file model yang diunggah.", "danger")
        return redirect(url_for('home_blueprint.dev_page'))
    
    file = request.files['ai_model_file']
    if file.filename == '':
        flash("Tidak ada file model yang dipilih.", "danger")
        return redirect(url_for('home_blueprint.dev_page'))

    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        
        # Logika untuk menyimpan model AI ke database
        # Anda perlu menentukan cara model ini akan dikaitkan
        # di halaman dev.
        
        flash(f"Model {filename} berhasil diunggah.", "success")
    return redirect(url_for('home_blueprint.dev_page'))

@blueprint.route('/delete_video/<int:cam_id>', methods=['POST'])
@login_required
def delete_video(cam_id):
    """
    Menghapus video yang sudah diunggah, model AI, dan entri kameranya.
    """
    try:
        camera_to_delete = Camera.query.filter_by(id=cam_id).first()
        if not camera_to_delete:
            flash(f"Kamera dengan ID {cam_id} tidak ditemukan.", "danger")
            return redirect(url_for('home_blueprint.dev_page'))

        # Tentukan direktori upload
        UPLOAD_FOLDER = os.path.join(current_app.root_path, 'static', 'uploads')
        
        # Hapus file video lokal
        if camera_to_delete.rtsp_url and camera_to_delete.rtsp_url.startswith(UPLOAD_FOLDER):
            video_path = camera_to_delete.rtsp_url
            if os.path.exists(video_path):
                os.remove(video_path)
                flash(f"File video '{os.path.basename(video_path)}' berhasil dihapus.", "success")
        
        # Hapus file model AI yang terkait dengan kamera ini
        ai_model = AIModel.query.filter_by(cam_id=cam_id).first()
        if ai_model and ai_model.file_path and os.path.exists(ai_model.file_path):
            os.remove(ai_model.file_path)
            db.session.delete(ai_model)
            flash(f"Model AI '{os.path.basename(ai_model.file_path)}' berhasil dihapus.", "success")
        
        # Hapus kamera dari database.
        # Database sekarang akan otomatis mengosongkan cam_id di tabel log.
        db.session.delete(camera_to_delete)
        db.session.commit()

        flash(f"Kamera '{camera_to_delete.name}' berhasil dihapus.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Gagal menghapus kamera: {str(e)}", "danger")

    return redirect(url_for('home_blueprint.dev_page'))
    
@socketio.on('start_ai_analysis')
def handle_start_ai_analysis(data):
    """
    Memulai analisis AI untuk file video yang diunggah.
    """
    cam_id = data.get('cam_id')
    if not cam_id:
        emit('ai_status', {'type': 'error', 'message': 'ID kamera tidak valid.'})
        return

    camera = Camera.query.get(cam_id)
    if not camera or not os.path.exists(camera.rtsp_url):
        emit('ai_status', {'type': 'error', 'message': 'File video tidak ditemukan.'})
        return

    # Gunakan fungsi helper yang ada untuk memulai stream AI
    start_ai_stream_for_client(cam_id, request.sid)
    emit('ai_status', {'type': 'info', 'message': 'Memulai analisis AI...'})

@socketio.on('stop_ai_analysis')
def handle_stop_ai_analysis(data):
    """
    Menghentikan analisis AI yang sedang berjalan.
    """
    cam_id = data.get('cam_id')
    if cam_id in camera_stop_events and camera_threads.get(cam_id):
        camera_stop_events[cam_id].set()
        camera_threads.pop(cam_id, None)
        camera_stop_events.pop(cam_id, None)
        logger.info(f"🛑 AI thread for video {cam_id} stopped by client request.")
    emit('ai_status', {'type': 'info', 'message': 'Analisis AI dihentikan.'})




@blueprint.route('/alarm-setting')
@login_required
def alarm_settings():
    """Halaman pengaturan alarm."""
    all_cameras = Camera.query.all()
    
    # Ambil pengaturan global, atau buat jika tidak ada
    global_settings = GlobalSettings.query.first()
    if not global_settings:
        global_settings = GlobalSettings()
        db.session.add(global_settings)
        db.session.commit()
    
    return render_template('home/alarm_settings.html', 
                           cameras=all_cameras,
                           global_settings=global_settings)

@blueprint.route('/set_storage', methods=['POST'])
@login_required
def set_storage():
    """
    Menyimpan pengaturan folder penyimpanan video dan screenshot ke database.
    """
    video_folder = request.form.get('video-folder')
    screenshot_folder = request.form.get('screenshot-folder')
    
    save_videos = 'save-videos' in request.form
    save_screenshots = 'save-screenshots' in request.form

    global_settings = GlobalSettings.query.first()
    if not global_settings:
        global_settings = GlobalSettings()
        db.session.add(global_settings)

    global_settings.video_folder = video_folder
    global_settings.screenshot_folder = screenshot_folder
    global_settings.save_videos = save_videos
    global_settings.save_screenshots = save_screenshots

    db.session.commit()

    return redirect(url_for('home_blueprint.alarm_settings'))

@blueprint.route('/recording')
@login_required
def recording():
    """
    Menampilkan daftar file video .mp4 dan screenshot yang ada di folder rekaman.
    """
    recordings = []
    screenshots = []
    error_message = None

    try:
        global_settings = GlobalSettings.query.first()
        
        # Mengambil daftar file video
        video_folder = global_settings.video_folder if global_settings and global_settings.video_folder else None
        if video_folder:
            if not os.path.exists(video_folder):
                current_app.logger.warning(f"Folder video tidak ditemukan: {video_folder}")
            else:
                mp4_files = [filename for filename in os.listdir(video_folder) if filename.endswith(".mp4")]
                mp4_files.sort()
                for filename in mp4_files:
                    file_path = os.path.join(video_folder, filename)
                    file_size_bytes = os.path.getsize(file_path)
                    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)
                    recordings.append({
                        'name': filename,
                        'size': f"{file_size_mb} MB"
                    })

        # Mengambil daftar file screenshot
        screenshot_folder = global_settings.screenshot_folder if global_settings and global_settings.screenshot_folder else None
        if screenshot_folder:
            if not os.path.exists(screenshot_folder):
                current_app.logger.warning(f"Folder screenshot tidak ditemukan: {screenshot_folder}")
            else:
                image_files = [filename for filename in os.listdir(screenshot_folder) if filename.lower().endswith(('.png', '.jpg', '.jpeg'))]
                image_files.sort()
                for filename in image_files:
                    file_path = os.path.join(screenshot_folder, filename)
                    file_size_bytes = os.path.getsize(file_path)
                    file_size_kb = round(file_size_bytes / 1024, 2)
                    screenshots.append({
                        'name': filename,
                        'size': f"{file_size_kb} KB"
                    })

        if not recordings and not screenshots:
            error_message = "Tidak ada file rekaman atau screenshot yang ditemukan."

    except Exception as e:
        error_message = f"Terjadi kesalahan saat memuat file: {e}"
        current_app.logger.error(f"Error loading recordings and screenshots: {e}")

    return render_template('home/recording.html', 
                           recordings=recordings, 
                           screenshots=screenshots, 
                           error_message=error_message, 
                           now=datetime.datetime.now)

@blueprint.route('/stream-recording/<filename>')
def stream_recording(filename):
    """
    Mengalirkan (streaming) file video .mp4 yang diminta.
    """
    try:
        global_settings = GlobalSettings.query.first()
        # Menggunakan video_folder
        video_folder = global_settings.video_folder if global_settings else None

        if not video_folder:
            return "Error: Folder video tidak dikonfigurasi.", 404
        
        absolute_path = os.path.join(video_folder, filename)
        
        if not os.path.exists(absolute_path) or not os.path.isfile(absolute_path):
            current_app.logger.error(f"File not found or is not a file: {absolute_path}")
            return "Error: File video tidak ditemukan.", 404
            
        return send_from_directory(video_folder, filename, mimetype="video/mp4")
    except Exception as e:
        current_app.logger.error(f"Error streaming video file: {e}")
        return f"Error: {e}", 500

@blueprint.route('/stream-screenshot/<filename>')
def stream_screenshot(filename):
    """
    Mengalirkan (streaming) file screenshot (.png, .jpg) yang diminta.
    """
    try:
        global_settings = GlobalSettings.query.first()
        # Menggunakan screenshot_folder
        screenshot_folder = global_settings.screenshot_folder if global_settings else None

        if not screenshot_folder:
            return "Error: Folder screenshot tidak dikonfigurasi.", 404
        
        absolute_path = os.path.join(screenshot_folder, filename)
        
        if not os.path.exists(absolute_path) or not os.path.isfile(absolute_path):
            current_app.logger.error(f"File not found or is not a file: {absolute_path}")
            return "Error: File screenshot tidak ditemukan.", 404

        # Menentukan mimetype berdasarkan ekstensi file
        if filename.lower().endswith('.png'):
            mimetype = "image/png"
        elif filename.lower().endswith(('.jpg', '.jpeg')):
            mimetype = "image/jpeg"
        else:
            mimetype = "application/octet-stream"
        
        return send_from_directory(screenshot_folder, filename, mimetype=mimetype)
    except Exception as e:
        current_app.logger.error(f"Error streaming screenshot file: {e}")
        return f"Error: {e}", 500

@blueprint.route('/clear-people-count-log', methods=['POST'])
def clear_people_count_log():
    try:
        # Hapus semua data dari tabel PeopleCountLog
        db.session.query(Count).delete()
        db.session.commit()
        flash('Semua log People Counting berhasil dihapus.', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Gagal menghapus log People Counting: {e}', 'error')
    return redirect(url_for('home_blueprint.dev_page'))

@blueprint.route('/clear-alarm-log', methods=['POST'])
def clear_alarm_log():
    try:
        # Hapus semua data dari tabel AlarmLog
        db.session.query(AlarmLog).delete()
        db.session.commit()
        flash('Semua log Alarm berhasil dihapus.', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Gagal menghapus log Alarm: {e}', 'error')
    return redirect(url_for('home_blueprint.dev_page'))

from sqlalchemy.sql import table, column, select, delete

@blueprint.route('/factory-default', methods=['POST'])
def factory_default():
    try:
        # Daftar tabel yang TIDAK AKAN DIHAPUS DATANYA
        excluded_tables = ['Users', 'Role', 'roles']
        
        # Hapus semua data dari tabel yang tidak dikecualikan
        meta = db.metadata
        for table in reversed(meta.sorted_tables):
            if table.name not in excluded_tables:
                db.session.execute(table.delete())
        
        users_table = db.metadata.tables['Users']
        delete_statement = delete(users_table).where(users_table.c.username != 'admin!@#')
        db.session.execute(delete_statement)
        
        db.session.commit()
        flash('Aplikasi berhasil dikembalikan ke pengaturan pabrik. Semua database kecuali akun admin telah dikosongkan.', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Gagal melakukan Factory Default: {e}', 'error')
    return redirect(url_for('home_blueprint.dev_page'))

@blueprint.route('/users')
@login_required
def users():
    all_users = Users.query.all()
    all_roles = Role.query.all()
    return render_template('home/users.html', users=all_users, roles=all_roles)

# Rute untuk menambah pengguna baru (POST)
@blueprint.route('/users/add', methods=['POST'])
@login_required
def add_user():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role_id = request.form.get('role')

    if not all([username, email, password, role_id]):
        flash('Semua bidang harus diisi!', 'danger')
        return redirect(url_for('home_blueprint.users'))

    new_user = Users(username=username, email=email, password=password)
    
    selected_role = Role.query.get(role_id)
    if selected_role:
        new_user.roles.append(selected_role)
    else:
        flash('Peran tidak valid.', 'danger')
        return redirect(url_for('home_blueprint.users'))

    try:
        db.session.add(new_user)
        db.session.commit()
        flash('Pengguna baru berhasil ditambahkan!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal menambah pengguna: {str(e)}', 'danger')
    
    return redirect(url_for('home_blueprint.users'))

# Rute untuk mengedit pengguna (POST)
@blueprint.route('/users/edit/<int:user_id>', methods=['POST'])
@login_required
def edit_user(user_id):
    user = Users.query.get_or_404(user_id)
    
    # Perbarui username dan email
    user.username = request.form.get('username')
    user.email = request.form.get('email')
    
    # Perbarui kata sandi jika ada input baru
    new_password = request.form.get('password')
    if new_password:
        user.password = hash_pass(new_password)
        
    # Perbarui peran
    new_role_id = request.form.get('role')
    if new_role_id:
        selected_role = Role.query.get(new_role_id)
        if selected_role:
            # Hapus semua peran lama dan tambahkan yang baru
            user.roles.clear()
            user.roles.append(selected_role)
        else:
            flash('Peran tidak valid.', 'danger')
            return redirect(url_for('home_blueprint.users'))

    try:
        db.session.commit()
        flash('Data pengguna berhasil diperbarui!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal memperbarui pengguna: {str(e)}', 'danger')

    return redirect(url_for('home_blueprint.users'))

# Rute untuk menghapus pengguna (POST)
@blueprint.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    user = Users.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash('Pengguna berhasil dihapus!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal menghapus pengguna: {str(e)}', 'danger')
    
    return redirect(url_for('home_blueprint.users'))
# -------------------------------
# ROUTE GENERIC TEMPLATE
# -------------------------------
@blueprint.route('/<template>')
@login_required
def route_template(template):
    try:
        if not template.endswith('.html'):
            template += '.html'
        segment = get_segment(request)
        return render_template("home/" + template, segment=segment)
    except TemplateNotFound:
        return render_template('home/page-404.html'), 404
    except:
        return render_template('home/page-500.html'), 500

# -------------------------------
# Helper
# -------------------------------
def get_segment(request):
    try:
        segment = request.path.split('/')[-1]
        if segment == '':
            segment = 'index'
        return segment
    except:
        return None

