$(document).ready(function() {
    // Membangun koneksi Socket.IO ke server
    const socket = io();
    
    // Variabel lokal untuk menyimpan data kamera yang diterima dari server
    let cameras = [];

    // Fungsi untuk merender tabel pengaturan alarm
    function renderAlarmTable() {
        // Mengambil referensi ke body tabel dengan ID 'alarm-table'
        const tableBody = $('#alarm-table tbody');
        // Membersihkan konten lama di dalam tabel untuk menghindari duplikasi
        tableBody.empty();

        // Cek jika tidak ada data kamera yang diterima
        if (cameras.length === 0) {
            tableBody.append('<tr><td colspan="4" class="text-center">Tidak ada kamera yang terdaftar.</td></tr>');
            return;
        }

        // Loop melalui setiap objek kamera dalam array
        cameras.forEach(camera => {
            // Membuat baris HTML untuk setiap kamera menggunakan template string
            const rowHtml = `
                <tr data-cam-id="${camera.id}">
                    <td>
                        <b>Kamera ${camera.id}</b> <br>
                        <small>${camera.rtsp_url}</small>
                    </td>
                    <td>
                        <div class="form-group">
                            <input 
                                type="text" 
                                class="form-control" 
                                name="trigger_${camera.id}" 
                                value="${camera.alarm_trigger || ''}"
                                placeholder="Contoh: person, no_helmet, smoke"
                            >
                        </div>
                    </td>
                    <td>
                        <div class="form-group">
                            <textarea class="form-control" name="action_${camera.id}" rows="3" placeholder="Contoh: Kirim sinyal ke NVR atau jalankan skrip API...">${camera.alarm_action || ''}</textarea>
                        </div>
                    </td>
                    <td class="text-center">
                        <button class="btn btn-primary btn-sm">Simpan</button>
                    </td>
                </tr>
            `;
            // Menambahkan baris yang baru dibuat ke body tabel
            tableBody.append(rowHtml);
        });

        // Memasang event listener ke tombol "Simpan" setelah elemen dibuat
        $('table#alarm-table button.btn-primary').on('click', function(e) {
            e.preventDefault();
            const $row = $(this).closest('tr');
            const camId = $row.data('cam-id');
            const trigger = $row.find('input[name^="trigger_"]').val(); // Mengambil nilai dari input
            const actionCode = $row.find('textarea').val();
            
            // Mengirim data pengaturan alarm ke server melalui Socket.IO
            socket.emit('save_alarm_settings', {
                cam_id: camId,
                trigger: trigger,
                action_code: actionCode
            });

            // Memberikan umpan balik visual kepada pengguna
            $(this).text('Saving...').addClass('disabled');
        });
    }

    // --- Event Listener Socket.IO ---

    // Mendengarkan event 'initial_alarm_data' dari server.
    socket.on('initial_alarm_data', function(data) {
        cameras = data;
        renderAlarmTable();
    });

    // Mendengarkan event 'alarm_settings_saved' dari server
    socket.on('alarm_settings_saved', function(data) {
        const $button = $(`tr[data-cam-id="${data.cam_id}"]`).find('button');
        $button.text('Simpan').removeClass('disabled');
        alert('Pengaturan alarm berhasil disimpan!');
    });

    // Menangani pesan kesalahan dari server
    socket.on('error_message', function(data) {
        alert('Error: ' + data.message);
        console.error('Server Error:', data.message);
    });
    
    // --- Inisialisasi ---
    
    // Meminta data kamera dari server saat halaman dimuat
    socket.emit('request_alarm_data');

    console.log("Skrip alarm_handler.js berhasil dimuat.");
});