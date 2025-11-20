# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os

class Config(object):
    """Kelas dasar untuk konfigurasi aplikasi."""
    
    basedir = os.path.abspath(os.path.dirname(__file__))

    # Set up the App SECRET_KEY
    SECRET_KEY = os.getenv('SECRET_KEY', 'S#perS3crEt_007')

    # Default database: SQLite
        # Default database: SQLite
    DB_USER = os.environ.get('DB_USER', 'ai_admin')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'S#perS3crEt_007')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_NAME = os.environ.get('DB_NAME', 'ai_watch_db')

    SQLALCHEMY_DATABASE_URI = f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'db.sqlite3')
    #SQLALCHEMY_TRACK_MODIFICATIONS = False 
    
    # Assets Management
    ASSETS_ROOT = os.getenv('ASSETS_ROOT', '/static/assets') 
    
    # Konfigurasi Social Authentication Github
    SOCIAL_AUTH_GITHUB = False
    GITHUB_ID = os.getenv('GITHUB_ID')
    GITHUB_SECRET = os.getenv('GITHUB_SECRET')
    if GITHUB_ID and GITHUB_SECRET:
        SOCIAL_AUTH_GITHUB = True


class ProductionConfig(Config):
    """Konfigurasi untuk lingkungan produksi."""
    DEBUG = False

    # Security enhancements
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 3600

    DB_USER = os.environ.get('DB_USER', 'ai_admin')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'Kulonuwun1!')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_NAME = os.environ.get('DB_NAME', 'ai_watch_db')
    # Gunakan SQLite juga di production
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(Config.basedir, 'db.sqlite3')
    #SQLALCHEMY_DATABASE_URI = f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'

class DebugConfig(Config):
    """Konfigurasi untuk development/debug."""
    DEBUG = True


# Load semua konfigurasi yang mungkin
config_dict = {
    'Production': ProductionConfig,
    'Debug': DebugConfig
}
