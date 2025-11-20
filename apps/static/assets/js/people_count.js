// Membangun koneksi Socket.IO ke server
const socket = io();

// Mengambil referensi elemen-elemen DOM
const cameraSelect = document.getElementById('cameraSelect');
const videoFeed = document.getElementById('videoFeed');
const drawCanvas = document.getElementById('drawCanvas');
const saveLineBtn = document.getElementById('saveLineBtn');
const clearLineBtn = document.getElementById('clearLineBtn');
const statusLog = document.getElementById('statusLog');
const peopleCountBadge = document.getElementById('peopleCountBadge');

// Mendapatkan konteks 2D untuk menggambar di canvas
const canvasContext = drawCanvas.getContext('2d');

// Variabel untuk melacak status gambar dan koordinat
let isDrawing = false;
let startPoint = {};
let endPoint = {};
let currentCamId = null;

/**
 * Menambahkan pesan log ke elemen statusLog
 * @param {string} message - Pesan yang akan ditambahkan ke log
 */
function addLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    statusLog.innerHTML += `[${timestamp}] ${message}\n`;
    statusLog.scrollTop = statusLog.scrollHeight;
}

/**
 * Menggambar titik di canvas
 * @param {Object} p - Titik {x, y}
 * @param {string} color - Warna titik
 */
function drawPoint(p, color) {
    canvasContext.beginPath();
    canvasContext.arc(p.x, p.y, 5, 0, 2 * Math.PI);
    canvasContext.fillStyle = color;
    canvasContext.fill();
}

/**
 * Menggambar garis di canvas dengan panah dua arah dan label IN/OUT.
 * @param {Object} p1 - Titik awal {x, y}
 * @param {Object} p2 - Titik akhir {x, y}
 */
function drawLineWithLabels(p1, p2) {
    clearCanvas();
    
    // Menggambar garis utama
    canvasContext.beginPath();
    canvasContext.moveTo(p1.x, p1.y);
    canvasContext.lineTo(p2.x, p2.y);
    canvasContext.strokeStyle = 'red';
    canvasContext.lineWidth = 3;
    canvasContext.stroke();
    
    // Menggambar titik awal dan akhir
    drawPoint(p1, 'green'); 
    drawPoint(p2, 'red'); 
    
    // Logika untuk panah dua arah dan label
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2;
    const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
    const labelOffset = 20; 

    // Fungsi bantu untuk menggambar panah
    const drawArrow = (angleOffset) => {
        canvasContext.save();
        canvasContext.translate(midX, midY);
        canvasContext.rotate(angle + angleOffset);
        canvasContext.beginPath();
        canvasContext.moveTo(0, 5); 
        canvasContext.lineTo(-10, 0); 
        canvasContext.lineTo(0, -5); 
        canvasContext.fillStyle = 'white';
        canvasContext.fill();
        canvasContext.restore();
    };

    drawArrow(0);           // Panah "IN"
    drawArrow(Math.PI);     // Panah "OUT"

    // Menambahkan label "OUT" dan "IN"
    canvasContext.font = 'bold 16px Arial';
    canvasContext.fillStyle = 'white';
    canvasContext.textAlign = 'center';

    const dx = Math.cos(angle + Math.PI/2);
    const dy = Math.sin(angle + Math.PI/2);
    
    const inLabelX = midX + dx * labelOffset;
    const inLabelY = midY + dy * labelOffset;
    const outLabelX = midX - dx * labelOffset;
    const outLabelY = midY - dy * labelOffset;

    canvasContext.fillText('IN', inLabelX, inLabelY);
    canvasContext.fillText('OUT', outLabelX, outLabelY);
}

/**
 * Menghapus semua yang ada di canvas
 */
function clearCanvas() {
    canvasContext.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
}

/**
 * Mengatur ukuran canvas agar sesuai dengan video
 */
function resizeCanvas() {
    if (videoFeed.offsetWidth > 0 && videoFeed.offsetHeight > 0) {
        drawCanvas.width = videoFeed.offsetWidth;
        drawCanvas.height = videoFeed.offsetHeight;
    } else {
        videoFeed.addEventListener('loadeddata', () => {
            drawCanvas.width = videoFeed.offsetWidth;
            drawCanvas.height = videoFeed.offsetHeight;
        }, { once: true });
    }
}

// Mendengarkan perubahan pilihan kamera
cameraSelect.addEventListener('change', () => {
    const selectedOption = cameraSelect.options[cameraSelect.selectedIndex];
    const newCamId = selectedOption.value;

    if (currentCamId && currentCamId !== newCamId) {
        addLog(`Menghentikan streaming untuk kamera: ${currentCamId}`);
        socket.emit('stop_stream', { cam_id: currentCamId });
    }

    if (newCamId) {
        currentCamId = newCamId;
        addLog(`Memulai streaming untuk kamera dengan ID: ${currentCamId}`);
        socket.emit('start_stream', { cam_id: currentCamId });
        
        const lineCoordsString = selectedOption.dataset.lineCoords || 'null';
        let lineCoords = null;
        
        // Periksa apakah data garis valid
        if (lineCoordsString && lineCoordsString !== 'null') {
            try {
                lineCoords = JSON.parse(lineCoordsString);
            } catch (e) {
                addLog(`ERROR: Gagal mem-parse data garis: ${e.message}`);
                console.error("Failed to parse JSON:", lineCoordsString, e);
            }
        }
        
        if (lineCoords) {
            // Panggil fungsi yang menunggu video dimuat
            drawExistingLine(lineCoords);
            addLog('Garis hitung yang sudah ada dimuat.');
            saveLineBtn.disabled = false;
            clearLineBtn.disabled = false;
        } else {
            // Jika tidak ada garis, bersihkan canvas dan nonaktifkan tombol
            clearCanvas();
            startPoint = {};
            endPoint = {};
            saveLineBtn.disabled = true;
            clearLineBtn.disabled = true;
            addLog('Tidak ada garis hitung yang tersimpan.');
        }
    } else {
        // Jika kamera tidak dipilih (opsi kosong), hentikan streaming
        addLog('Streaming dihentikan. Pilih kamera untuk memulai.');
        if (currentCamId) {
            socket.emit('stop_stream', { cam_id: currentCamId });
        }
        videoFeed.src = '';
        currentCamId = null;
        clearCanvas();
        saveLineBtn.disabled = true;
        clearLineBtn.disabled = true;
    }
});

function stopStream() {
    if (currentCamId) {
        addLog(`Menghentikan streaming untuk kamera: ${currentCamId}`);
        socket.emit('stop_stream', { cam_id: currentCamId });
        // Opsional: kosongkan sumber video untuk menghemat bandwidth
        videoFeed.src = '';
    }
}

function drawExistingLine(coords) {
    // Inner function to perform the actual drawing logic
    const draw = () => {
        const videoWidth = videoFeed.offsetWidth;
        const videoHeight = videoFeed.offsetHeight;
        
        // Periksa kembali untuk memastikan dimensi valid
        if (videoWidth === 0 || videoHeight === 0) {
            console.error('Video feed has no dimensions. Cannot draw line.');
            return;
        }

        // Perbarui variabel global
        startPoint = { x: coords.x1 * videoWidth, y: coords.y1 * videoHeight };
        endPoint = { x: coords.x2 * videoWidth, y: coords.y2 * videoHeight };

        // Panggil fungsi gambar dengan titik-titik yang sudah diperbarui
        drawLineWithLabels(startPoint, endPoint);
    };

    // Pengecekan status video: jika sudah siap, gambar langsung
    if (videoFeed.readyState >= 2) { // 2 = HAVE_CURRENT_DATA
        draw();
    } else {
        // Jika belum, tunggu sampai video memuat
        videoFeed.addEventListener('loadeddata', draw, { once: true });
    }
}

// Mendengarkan event mouse pada canvas untuk menggambar
drawCanvas.addEventListener('mousedown', (e) => {
    if (!currentCamId) {
        addLog('ERROR: Pilih kamera terlebih dahulu sebelum menggambar.');
        return;
    }
    isDrawing = true;
    const rect = drawCanvas.getBoundingClientRect();
    startPoint = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };
    endPoint = {};
    saveLineBtn.disabled = true;
});

drawCanvas.addEventListener('mouseup', (e) => {
    if (isDrawing) {
        isDrawing = false;
        const rect = drawCanvas.getBoundingClientRect();
        endPoint = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };
        drawLineWithLabels(startPoint, endPoint);
        saveLineBtn.disabled = false;
    }
});

drawCanvas.addEventListener('mousemove', (e) => {
    if (!isDrawing) return;
    const rect = drawCanvas.getBoundingClientRect();
    const currentPoint = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };
    clearCanvas();
    drawLineWithLabels(startPoint, currentPoint);
});

// Menangani tombol "Simpan Garis"
saveLineBtn.addEventListener('click', () => {
    if (!currentCamId) {
        addLog('ERROR: Pilih kamera terlebih dahulu.');
        return;
    }
    if (Object.keys(startPoint).length === 0 || Object.keys(endPoint).length === 0) {
        addLog('ERROR: Tidak ada garis untuk disimpan. Gambar garis terlebih dahulu.');
        return;
    }

    const videoWidth = videoFeed.offsetWidth;
    const videoHeight = videoFeed.offsetHeight;

    const lineCoords = {
        x1: startPoint.x / videoWidth,
        y1: startPoint.y / videoHeight,
        x2: endPoint.x / videoWidth,
        y2: endPoint.y / videoHeight
    };
    
    addLog('Mengirim koordinat garis ke server...');
    socket.emit('save_counting_line', {
        cam_id: currentCamId,
        line_coords: lineCoords
    });
});

// Menangani tombol "Hapus Garis"
clearLineBtn.addEventListener('click', () => {
    if (!currentCamId) {
        addLog('ERROR: Pilih kamera terlebih dahulu.');
        return;
    }
    socket.emit('clear_line', { cam_id: currentCamId });
    clearCanvas();
    startPoint = {};
    endPoint = {};
    saveLineBtn.disabled = true;
    clearLineBtn.disabled = true;
    addLog('Garis berhasil dihapus.');
});

// --- Pendengar Socket.IO ---
socket.on('frame', (data) => {
    if (currentCamId && data.cam_id == currentCamId) {
        videoFeed.src = 'data:image/jpeg;base64,' + data.frame;
        peopleCountBadge.textContent = data.count !== undefined ? data.count : 'N/A';
    }
});

socket.on('log', (data) => {
    addLog(`Server: ${data.message}`);
});

socket.on('line_saved_success', (data) => {
    addLog(`BERHASIL: Garis disimpan untuk kamera ${data.cam_id}.`);
    const selectedOption = cameraSelect.options[cameraSelect.selectedIndex];
    // Simpan koordinat baru ke dataset
    selectedOption.dataset.lineCoords = JSON.stringify(data.line_coords);
    
    // Perbarui startPoint dan endPoint saat berhasil disimpan
    if (videoFeed.readyState >= 2) {
        drawExistingLine(data.line_coords);
    } else {
        // Jika video belum dimuat, tunggu sampai siap
        videoFeed.addEventListener('loadeddata', () => {
            drawExistingLine(data.line_coords);
        }, { once: true });
    }
});

socket.on('line_cleared_success', (data) => {
    addLog(`BERHASIL: Garis dihapus untuk kamera ${data.cam_id}.`);
    const selectedOption = cameraSelect.options[cameraSelect.selectedIndex];
    // Set dataset ke 'null' untuk konsistensi dengan logika awal
    selectedOption.dataset.lineCoords = 'null';
    saveLineBtn.disabled = true;
    clearLineBtn.disabled = true;
    addLog('Garis berhasil dihapus.');
});

socket.on('error_message', (data) => {
    addLog(`ERROR: ${data.message}`);
});

// --- Inisialisasi Awal ---
window.onload = () => {
    resizeCanvas();
    saveLineBtn.disabled = true;
    addLog('Aplikasi siap. Pilih kamera untuk memulai streaming.');
};

window.addEventListener('resize', () => {
    resizeCanvas();
    const selectedOption = cameraSelect.options[cameraSelect.selectedIndex];
    const lineCoords = JSON.parse(selectedOption.dataset.lineCoords || 'null');
    if (lineCoords) {
        drawExistingLine(lineCoords);
    }
});

window.addEventListener('beforeunload', stopStream);

// Alternatif atau tambahan: menghentikan streaming saat tab tidak aktif
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopStream();
    } else {
        // Logika opsional: memulai kembali streaming saat kembali ke halaman
        if (currentCamId) {
            addLog(`Melanjutkan streaming untuk kamera: ${currentCamId}`);
            socket.emit('start_stream', { cam_id: currentCamId });
        }
    }
});