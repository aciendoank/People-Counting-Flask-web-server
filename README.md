# 🧠 People Counting System (YOLOv8 + OpenCV)

Sistem pendeteksi dan penghitung orang secara real-time menggunakan **YOLOv8**, **DeepSORT**, dan **OpenCV**.  
Support untuk **IP Camera (RTSP)**, **Webcam**, dan **rekaman video**.

## ✨ Fitur Utama
- 🔍 Deteksi orang secara real-time (YOLOv8)
- 🔢 Penghitungan masuk/keluar menggunakan garis virtual
- 🎯 Tracking akurat (DeepSORT)
- 📡 Support RTSP / IP Camera
- 🖥️ Dashboard monitoring (opsional)
- 💾 Auto-save log hasil hitung
- 📊 Export data ke CSV/Excel
- ⚡ Optimasi untuk CPU & GPU

---


1. Buat Virtual Environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

2. Install Dependency
pip install -r requirements.txt

3. Install database sqlite3
flask db init

4. tambah username password untuk login

flask shell
Jalankan Baris Kode: Anda harus menjalankan setiap baris kode yang Anda sediakan satu per satu di dalam sesi flask shell tersebut:


from apps import db
from apps.authentication.models import Users, Role, hash_pass 
admin_role = Role.query.filter_by(name='Admin').first() 
if not admin_role: 
    admin_role = Role(name='Admin', description='Administrator role')
    db.session.add(admin_role) 
    db.session.commit() 
    print("Role Admin dibuat.") 

username = "admin" 
email = "admin@example.com" 
password = "admin123" 
user = Users(username=username, email=email, password=password)
db.session.add(user)
db.session.commit()
print("User berhasil dibuat.")

user.roles.append(admin_role)
db.session.commit()
print("Role Admin berhasil ditambahkan ke user.")

quit()




5. jalankan aplikasi
python run.py

6.buka browser
localhost:5001
   

