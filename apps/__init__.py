# -*- encoding: utf-8 -*-
import os
from flask import Flask, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
from importlib import import_module

# --- Ekstensi ---
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO(cors_allowed_origins="*")

# --- Import models agar Flask-Migrate dapat menemukannya ---
# Ini sangat penting untuk perintah CLI seperti 'flask db migrate'
from apps.home.models import AlarmLog, GlobalSettings, Camera, AIModel, Count

# --- Fungsi-fungsi Pembantu ---
def register_extensions(app):
    """
    Fungsi untuk mendaftarkan semua ekstensi Flask.
    """
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)

def register_blueprints(app):
    """
    Fungsi untuk mendaftarkan semua Blueprint.
    """
    for module_name in ('authentication', 'home'):
        module = import_module(f'apps.{module_name}.routes')
        app.register_blueprint(module.blueprint)

# --- Pabrik Aplikasi ---
def create_app(config):
    """
    Fungsi pabrik untuk membuat instance aplikasi Flask.
    """
    app = Flask(__name__)
    app.config.from_object(config)

    register_extensions(app)
    register_blueprints(app)

    # Inisialisasi Flask-Migrate setelah ekstensi didaftarkan
    Migrate(app, db)
    
    # Jika menggunakan github login
    try:
        from apps.authentication.oauth import github_blueprint
        app.register_blueprint(github_blueprint, url_prefix="/login")
    except ImportError:
        pass

    return app
