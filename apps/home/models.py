# -*- encoding: utf-8 -*-
"""
Models for the Home Blueprint
"""

from apps import db
#from flask_login import UserMixin
import datetime

# Hapus "UserMixin" dari sini
class Camera(db.Model):
    __tablename__ = 'camera'

    id = db.Column(db.Integer, primary_key=True)
    rtsp_url = db.Column(db.String(256), unique=False, nullable=True)
    is_ai_enabled = db.Column(db.Boolean, default=False)
    counting_line = db.Column(db.Text, nullable=True)
    
    # Tambahan untuk nama & lokasi
    name = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(100), nullable=True)

    alarm_trigger = db.Column(db.String(50), nullable=True)
    alarm_action = db.Column(db.Text, nullable=True)
    
    ai_models = db.relationship('AIModel', backref='camera', lazy=True)

    def __repr__(self):
        return f'<Camera {self.id} - {self.name}>'


class AIModel(db.Model):
    __tablename__ = 'ai_model'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(256), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    model_type = db.Column(db.String(50), nullable=False, default='yolov8')
    cam_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    conf_threshold = db.Column(db.Float, default=0.25)
    iou_threshold = db.Column(db.Float, default=0.7)

    def __repr__(self):
        return f'<AIModel {self.filename}>'

class Count(db.Model):
    __tablename__ = 'count'

    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id', ondelete='SET NULL'), nullable=True)
    camera_name = db.Column(db.String(100), nullable=True)
    direction = db.Column(db.String(10), nullable=False) # 'in' or 'out'
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

    def __repr__(self):
        return f'<Count {self.camera_id} - {self.direction} at {self.timestamp}>'

# --- MODEL BARU UNTUK PENGATURAN GLOBAL ---

class GlobalSettings(db.Model):
    __tablename__ = 'global_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    video_folder = db.Column(db.String(255), nullable=True)
    screenshot_folder = db.Column(db.String(255), nullable=True)
    save_videos = db.Column(db.Boolean, default=False)
    save_screenshots = db.Column(db.Boolean, default=False)
    

    def __repr__(self):
        return f"GlobalSettings(id='{self.id}')"

# --- MODEL BARU UNTUK FILE RECORD ---
class FileRecord(db.Model):
    __tablename__ = 'file_record'  # Tambahkan nama tabel
    id = db.Column(db.Integer, primary_key=True)
    cam_id = db.Column(db.Integer, db.ForeignKey('camera.id', ondelete='SET NULL'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False) # 'screenshot' atau 'video'
    date_created = db.Column(db.Date, nullable=False)
    time_created = db.Column(db.Time, nullable=False)
    
    camera = db.relationship('Camera', backref='file_records', lazy=True)

    def __repr__(self):
        return f'<FileRecord {self.filename}>'        

# --- MODEL BARU UNTUK LOG ALARM ---
class AlarmLog(db.Model):
    __tablename__ = 'alarm_log'

    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id', ondelete='SET NULL'), nullable=True)
    camera_name = db.Column(db.String(100), nullable=True)
    message = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

    def __repr__(self):
        return f'<AlarmLog {self.id} - {self.message} at {self.timestamp}>'

