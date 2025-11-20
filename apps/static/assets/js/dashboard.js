/**
 * dashboard.js
 *
 * Skrip ini menginisialisasi grafik batang harian, mendengarkan pembaruan data
 * real-time untuk label hitungan langsung dan log, dan memperbarui visualisasi dashboard.
 */

document.addEventListener('DOMContentLoaded', function() {
    const chartContainer = document.getElementById('peopleCountingChart');
    const liveCountsContainer = document.getElementById('camera-labels');
    const alarmLogContainer = document.getElementById('alarm-log');
    const countingLogContainer = document.getElementById('counting-log');
    let peopleCountingChart = null;
    
    // Pastikan variabel global 'cameras' dari Jinja ada dan berisi array.
    if (typeof cameras === 'undefined' || !Array.isArray(cameras) || cameras.length === 0) {
        console.error("Kesalahan: Variabel 'cameras' tidak ditemukan, kosong, atau bukan array.");
        if (chartContainer) {
            chartContainer.innerHTML = '<p class="text-center text-gray-500 font-medium">Tidak ada kamera yang terdaftar atau data belum dimuat. Periksa konfigurasi backend Anda.</p>';
        }
        if (liveCountsContainer) {
            liveCountsContainer.innerHTML = '<p class="text-center text-gray-500">Tidak ada data hitungan yang tersedia.</p>';
        }
        return;
    }

    // Inisialisasi koneksi Socket.IO
    const socket = io('/dashboard');

    /**
     * Inisialisasi grafik batang. Ini hanya akan dipanggil satu kali.
     */
    function initializeChart() {
        if (!chartContainer) return;
        
        const ctx = chartContainer.getContext('2d');
        peopleCountingChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Total Masuk',
                        data: [],
                        backgroundColor: 'rgba(59, 130, 246, 0.8)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Total Keluar',
                        data: [],
                        backgroundColor: 'rgba(239, 68, 68, 0.8)',
                        borderColor: 'rgba(239, 68, 68, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Kamera'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Jumlah Orang'
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    title: {
                        display: true,
                        text: 'Total Masuk dan Keluar Hari Ini'
                    }
                }
            }
        });
    }

    /**
     * Memperbarui data grafik dengan data hitungan baru.
     * @param {Object} countsData Data hitungan per kamera.
     */
    function updateChartData(countsData) {
        if (!peopleCountingChart) return;
        
        const inCounts = [];
        const outCounts = [];
        const labels = [];
        
        cameras.forEach(cam => {
            const camLabel = cam.location ? `${cam.name} (${cam.location})` : cam.name;
            labels.push(camLabel);
            
            const counts = countsData[cam.id] || { in: 0, out: 0 };
            inCounts.push(counts.in);
            outCounts.push(counts.out);
        });

        peopleCountingChart.data.labels = labels;
        peopleCountingChart.data.datasets[0].data = inCounts;
        peopleCountingChart.data.datasets[1].data = outCounts;
        peopleCountingChart.update(); // Perintah kunci untuk memperbarui grafik
    }

    // Panggil fungsi inisialisasi grafik saat halaman dimuat
    initializeChart();

    // Socket.IO Listeners
    socket.on('dashboard_data_update', function(data) {
        // Perbarui UI hitungan langsung
        if (data.chart_data) {
            updateLiveCountsUI(data.chart_data);
            // Panggil fungsi pembaruan grafik di sini
            updateChartData(data.chart_data);
        }

        // Perbarui log
        updateLogsUI(data);
    });

    socket.on('initial_dashboard_data', function(data) {
        // Data awal saat koneksi pertama
        if (data.chart_data) {
            updateLiveCountsUI(data.chart_data);
            updateChartData(data.chart_data);
        }
        updateLogsUI(data);
    });

    /**
     * Memperbarui label hitungan langsung di bawah grafik.
     * @param {Object} countsData Objek yang berisi data hitungan per kamera.
     */
    function updateLiveCountsUI(countsData) {
        liveCountsContainer.innerHTML = '';
        
        if (Object.keys(countsData).length === 0) {
            liveCountsContainer.innerHTML = '<p class="text-center text-gray-500">Menunggu data hitungan...</p>';
            return;
        }

        cameras.forEach(cam => {
            const counts = countsData[cam.id] || { in: 0, out: 0 };
            const countIn = counts.in || 0;
            const countOut = counts.out || 0;
            const netCount = countIn - countOut;

            const element = document.createElement('div');
            element.className = 'inline-block px-4 py-2 m-1 text-sm font-semibold rounded-full bg-blue-100 text-blue-800 shadow-md';
            element.textContent = `${cam.name}: Masuk: ${countIn}, Keluar: ${countOut}`;
            liveCountsContainer.appendChild(element);
        });
    }

    /**
     * Memperbarui log alarm dan hitungan orang.
     * @param {Object} logsData Objek yang berisi data log.
     */
    function updateLogsUI(logsData) {
        // Logika untuk log alarm
        if (logsData.alarm_logs && logsData.alarm_logs.length > 0) {
            alarmLogContainer.innerHTML = '';
            logsData.alarm_logs.forEach(log => {
                const p = document.createElement('p');
                p.className = 'text-sm text-red-600'; // Tambahkan gaya untuk alarm
                p.textContent = log;
                alarmLogContainer.appendChild(p);
            });
        } else {
            alarmLogContainer.innerHTML = '<p class="text-gray-500">Tidak ada log alarm.</p>';
        }

        // Logika untuk log hitungan orang
        if (logsData.counting_logs && logsData.counting_logs.length > 0) {
            countingLogContainer.innerHTML = '';
            logsData.counting_logs.forEach(log => {
                const p = document.createElement('p');
                p.className = 'text-sm text-blue-600'; // Tambahkan gaya untuk counting
                p.textContent = log;
                countingLogContainer.appendChild(p);
            });
        } else {
            countingLogContainer.innerHTML = '<p class="text-gray-500">Tidak ada log hitungan.</p>';
        }
    }
});