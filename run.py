# run.py 

# -*- encoding: utf-8 -*-
import eventlet
eventlet.monkey_patch()

from os import environ
from sys import exit
from apps import create_app, socketio, db
from apps.config import config_dict
from flask_migrate import Migrate
from flask_minify import Minify
import os
import threading
import logging
from apps.home.models import Camera, AlarmLog
from flask import Flask

# Inisialisasi Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pilih Konfigurasi
DEBUG = os.getenv('DEBUG', 'False') == 'True'
config_mode = 'Debug' if DEBUG else 'Production'
app_config = config_dict[config_mode]

# Buat Aplikasi Flask
app = create_app(app_config)

# Database Migration
Migrate(app, db)

# Minify jika production
if not DEBUG:
    Minify(app=app, html=True, js=False, cssless=False)

# Info Logging
if DEBUG:
    app.logger.info(f'DEBUG        = {DEBUG}')
    app.logger.info(f'DBMS         = {app_config.SQLALCHEMY_DATABASE_URI}')
    app.logger.info(f'ASSETS_ROOT  = {app_config.ASSETS_ROOT}')

# Jalankan Socket.IO
if __name__ == "__main__":
    with app.app_context():
        # Buat tabel database jika belum ada
        db.create_all()
        from apps.home.routes import client_sids, camera_threads, camera_stop_events, ai_stream, background_data_sender, dashboard_stop_event
         
        # Mulai stream untuk setiap kamera yang is_ai_enabled = True
        cameras = Camera.query.filter_by(is_ai_enabled=True).all()
        for cam in cameras:
            if cam.id not in camera_threads or not camera_threads[cam.id].is_alive():
                stop_event = threading.Event()
                camera_stop_events[cam.id] = stop_event
                
                t = threading.Thread(target=ai_stream, args=(socketio, app, cam.id, cam.rtsp_url, stop_event, client_sids))
                t.daemon = True
                t.start()
                camera_threads[cam.id] = t
                logger.info(f"✅ AI thread for camera {cam.id} started automatically on startup.")

        # --- Tambahan Kode untuk Mengatasi Masalah Dasbor ---
        logger.info("✅ Starting dashboard data sender thread...")
        # Perhatikan argumen `app` yang ditambahkan di sini
        dashboard_thread = threading.Thread(target=background_data_sender, args=(app, dashboard_stop_event,))
        dashboard_thread.daemon = True
        dashboard_thread.start()
        # ---------------------------------------------------

    socketio.run(app, host="0.0.0.0", port=5001, debug=DEBUG)