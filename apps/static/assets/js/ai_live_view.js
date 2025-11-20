document.addEventListener('DOMContentLoaded', function() {
    // Pastikan ini terhubung ke namespace yang benar jika ada
    const socket = io(); 
    const aiLiveContainer = document.getElementById('ai-live-container');
    const layoutButtons = document.querySelectorAll('[data-grid]');

    let cameras = window.cameras || [];
    let cameraElements = {};

    function renderCameraCards() {
        aiLiveContainer.innerHTML = '';
        cameraElements = {};

        cameras.forEach(cam => {
            const isAiEnabled = cam.is_ai_enabled;
            const disabledAttribute = !isAdmin ? 'disabled' : '';
            const cardHtml = `
                <div class="col-lg-6 col-md-12 ai-card-container" id="card-${cam.id}" data-cam-id="${cam.id}">
                    <div class="card card-video">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h4 class="card-title mb-0">${cam.name || 'Kamera ' + cam.id}</h4>
                            <div class="form-check form-switch d-flex align-items-center">
                                <span class="me-2 text-muted" style="font-size: 0.9rem;">AI Aktif</span>
                                <label class="ai-switch">
                                    <input type="checkbox" class="ai-toggle" data-cam-id="${cam.id}" ${isAiEnabled ? 'checked' : ''}${disabledAttribute}>
                                    <span class="ai-slider"></span>
                                </label>
                            </div>
                        </div>
                        <div class="card-body">
                            <p class="text-muted text-center mb-2">${cam.location || 'Lokasi tidak diketahui'}</p>
                            <div class="video-container">
                                <img id="ai-video-feed-${cam.id}" src="" alt="AI Live View" style="display: none;">
                                <div id="ai-placeholder-${cam.id}" class="placeholder-text">
                                    <span>${isAiEnabled ? 'Memulai Live View...' : 'AI tidak aktif'}</span>
                                </div>
                                <div id="ai-loading-spinner-${cam.id}" class="spinner-border text-info" role="status" style="display: none;">
                                    <span class="visually-hidden">Loading...</span>
                                </div>
                            </div>
                        </div>
                        <div class="card-footer">
                            <p class="mb-1 text-center">
                                Masuk: <span id="ai-count-in-${cam.id}" class="fw-bold me-3">0</span>
                                Keluar: <span id="ai-count-out-${cam.id}" class="fw-bold">0</span>
                            </p>
                            <p id="detection-results-${cam.id}" class="text-muted text-center mb-0">${isAiEnabled ? 'Menunggu deteksi...' : 'AI tidak aktif'}</p>
                        </div>
                    </div>
                </div>
            `;
            aiLiveContainer.insertAdjacentHTML('beforeend', cardHtml);
            
            cameraElements[cam.id] = {
                card: document.getElementById(`card-${cam.id}`),
                videoFeed: document.getElementById(`ai-video-feed-${cam.id}`),
                placeholder: document.getElementById(`ai-placeholder-${cam.id}`),
                loadingSpinner: document.getElementById(`ai-loading-spinner-${cam.id}`),
                countIn: document.getElementById(`ai-count-in-${cam.id}`),
                countOut: document.getElementById(`ai-count-out-${cam.id}`),
                detectionResults: document.getElementById(`detection-results-${cam.id}`)
            };
        });
        
        attachEventListeners();
    }

    // Fungsi ini akan dipanggil saat halaman dimuat
    function initializeStreams() {
        cameras.forEach(cam => {
            if (cam.is_ai_enabled) {
                // Tambahkan spinner dan placeholder
                const els = cameraElements[cam.id];
                if (els) {
                    els.loadingSpinner.style.display = 'block';
                    els.placeholder.style.display = 'block';
                    els.placeholder.querySelector('span').textContent = 'Memulai Live View...';
                }
                // Mulai stream untuk kamera yang AI-nya aktif
                socket.emit('start_ai_stream', { 'cam_id': cam.id });
                console.log(`Mengirim 'start_ai_stream' untuk kamera ${cam.id} karena AI aktif.`);
            }
        });
    }

    function attachEventListeners() {
        document.querySelectorAll('.ai-toggle').forEach(toggle => {
            toggle.addEventListener('change', handleToggleChange);
        });
        layoutButtons.forEach(button => {
            button.addEventListener('click', handleLayoutChange);
        });
    }

    function handleToggleChange(e) {
        const camId = parseInt(e.target.dataset.camId);
        const isEnabled = e.target.checked;
        
        // Perbarui status AI di database melalui server
        socket.emit('update_ai_status', { 'cam_id': camId, 'is_enabled': isEnabled });
        if (!isAdmin) {
            e.target.checked = !e.target.checked;
            alert('Anda tidak memiliki izin untuk menghentikan AI stream.');
            return;
        }
        const els = cameraElements[camId];
        if (els) {
            if (isEnabled) {
                // Langsung minta stream AI dari server
                socket.emit('start_ai_stream', { 'cam_id': camId });
                console.log(`Mengirim 'start_ai_stream' untuk kamera ${camId} setelah diaktifkan.`);

                // Tampilkan spinner saat menunggu stream
                els.videoFeed.style.display = 'none';
                els.loadingSpinner.style.display = 'block';
                els.placeholder.style.display = 'block';
                els.placeholder.querySelector('span').textContent = 'Memulai Live View...';
            } else {
                // Minta server untuk menghentikan stream
                socket.emit('stop_ai_stream', { 'cam_id': camId });
                console.log(`Mengirim 'stop_ai_stream' untuk kamera ${camId} setelah dinonaktifkan.`);

                els.videoFeed.src = ''; // Kosongkan src untuk menghentikan stream
                els.videoFeed.style.display = 'none';
                els.loadingSpinner.style.display = 'none';
                els.placeholder.style.display = 'block';
                els.placeholder.querySelector('span').textContent = 'AI tidak aktif';
                els.detectionResults.textContent = 'AI tidak aktif';
            }
        }
    }
    
    // ... (Fungsi handleLayoutChange() tidak berubah) ...
    function handleLayoutChange(e) {
        layoutButtons.forEach(btn => btn.classList.remove('active'));
        e.target.classList.add('active');
        const gridSize = parseInt(e.target.dataset.grid, 10);
        
        let colClass;
        switch (gridSize) {
            case 1:
                colClass = 'col-md-12';
                break;
            case 4:
                colClass = 'col-lg-6 col-md-12';
                break;
            case 9:
                colClass = 'col-lg-4 col-md-6';
                break;
            default:
                colClass = 'col-lg-6 col-md-12';
        }
    
        for (const camId in cameraElements) {
            const card = cameraElements[camId].card;
            if (card) {
                card.classList.remove('col-md-12', 'col-lg-6', 'col-md-6', 'col-lg-4');
                const classesToAdd = colClass.split(' ');
                card.classList.add(...classesToAdd);
            }
        }
    }

    // --- Socket.IO Listeners ---

    // Ganti event listener 'initial_status' dengan logika yang lebih sederhana
    // Karena 'routes.py' sudah mengirimkan ini saat 'connect'
    socket.on('initial_status', (data) => {
        cameras = data;
        renderCameraCards();
        handleLayoutChange({ target: document.querySelector('[data-grid].active') || layoutButtons[1] });
        initializeStreams(); // Panggil fungsi ini setelah cards dirender
    });

    socket.on('ai_frame', function(data) {
        const videoFeed = document.getElementById(`ai-video-feed-${data.cam_id}`);
        const loadingSpinner = document.getElementById(`ai-loading-spinner-${data.cam_id}`);
        const placeholder = document.getElementById(`ai-placeholder-${data.cam_id}`);
        
        if (videoFeed && loadingSpinner && placeholder) {
            videoFeed.src = 'data:image/jpeg;base64,' + data.frame;
            videoFeed.style.display = 'block';
            loadingSpinner.style.display = 'none';
            placeholder.style.display = 'none';
        }
    });

    socket.on('ai_count_update', (data) => {
        const els = cameraElements[data.cam_id];
        if (els) {
            els.countIn.textContent = data.counts.in;
            els.countOut.textContent = data.counts.out;
        }
    });

    socket.on('ai_status', function(data) {
        const els = cameraElements[data.cam_id];
        if (els) {
            els.detectionResults.textContent = data.message;
            if (data.type === 'info') {
                els.loadingSpinner.style.display = 'none';
                els.placeholder.style.display = 'block';
                els.placeholder.querySelector('span').textContent = data.message;
            } else if (data.type === 'error') {
                els.loadingSpinner.style.display = 'none';
                els.placeholder.style.display = 'block';
                els.placeholder.querySelector('span').textContent = `Error: ${data.message}`;
                els.videoFeed.style.display = 'none';
            }
        }
    });

    // Tidak perlu lagi memanggil 'request_initial_status'
    // karena 'routes.py' akan mengirimkan data secara otomatis saat koneksi dibuat
});