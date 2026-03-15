
let readings = [];
let blockchain = [];
let acknowledgedAlerts = false;
let chartInstances = {};

// Gate operation defaults
const DEFAULT_GATE_PITCH = 0.02; // m per rotation, matches HYDRAULICS_CONFIG.gate_screw_pitch

// Reservoir automation settings (can be tuned for a real dam)
const SAFE_STORAGE_PERCENT = 90.0;        // Safe threshold P_th (%)
const RESERVOIR_CAPACITY_M3 = 500000.0;   // Total storage capacity C (m³)

// Water level animation / automation state
let lastWaterLevelPercent = null;
let lastExcessPercent = 0.0;
let lastExcessVolumeM3 = 0.0;

// OCR State
let socket = null;
let isConnected = false;
let isCameraConnected = false;
let lastOcrReading = null;
let ocrReadingHistory = [];
let videoFeedInterval = null;

const THRESHOLDS = {
    levelHigh: 75,
    flowLow: 60,
    flowHigh: 260
};

const NORMALIZATION_RANGES = {
    level: { min: 0, max: 100 },
    flow: { min: 0, max: 400 }
};

function initializeApp() {
    createGenesisBlock();
    setupEventListeners();
    setupWebSocket();
    updateAllUI();
}

// ==================== WebSocket Setup ====================

function setupWebSocket() {
    // Connect to Flask-SocketIO server
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        updateConnectionStatus(true);
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        updateConnectionStatus(false);
    });
    
    socket.on('camera_status', (data) => {
        console.log('Camera status:', data);
        isConnected = data.connected;
        updateConnectionStatus(data.connected);
        
        if (data.last_reading !== null) {
            // Last reading from status is the raw distance; show it on the Live OCR card
            updateLiveOcrDistance(data.last_reading);
        }
    });
    
    socket.on('new_reading', (data) => {
        console.log('New OCR reading:', data);
        // Use water_level (calculated) for display, distance is the raw reading
        const displayValue = data.water_level !== undefined ? data.water_level : data.distance;
        updateOcrReading(displayValue, data.timestamp, data);
        
        // Always show the raw distance reading on the Live OCR card
        updateLiveOcrDistance(data.distance);
        
        // Add to history
        ocrReadingHistory.push({
            value: displayValue,
            distance: data.distance,
            water_level: data.water_level,
            percentage: data.percentage,
            status: data.status,
            timestamp: new Date(data.timestamp)
        });
        
        // Keep only last 50 readings
        if (ocrReadingHistory.length > 50) {
            ocrReadingHistory = ocrReadingHistory.slice(-50);
        }
        
        updateOcrHistoryChart();
    });
    
    socket.on('ocr_result', (data) => {
        console.log('OCR test result:', data);
        displayOcrResult(data);
    });
    
    socket.on('stream_started', (data) => {
        console.log('Stream started:', data.url);
        // Start MJPEG feed (prevents caching)
        startVideoFeed();
    });
}

function updateConnectionStatus(connected) {
    isCameraConnected = connected;
    
    // Update feed overlay badge
    const feedStatus = document.getElementById('feedStatus');
    if (feedStatus) {
        feedStatus.className = 'connection-badge ' + (connected ? 'connected' : 'disconnected');
        feedStatus.textContent = connected ? 'Connected' : 'Disconnected';
    }
    
    // Update KPI status
    const kpiStatus = document.getElementById('kpiLevelOcrStatus');
    if (kpiStatus) {
        if (connected) {
            kpiStatus.textContent = 'Live from ESP-CAM';
            kpiStatus.style.color = '#00aa66';
        } else {
            kpiStatus.textContent = 'Waiting for camera';
            kpiStatus.style.color = '#888888';
        }
    }
    
    // Update OCR status
    const ocrStatus = document.getElementById('ocrStatus');
    if (ocrStatus) {
        ocrStatus.textContent = connected ? 'Reading from camera...' : 'Waiting for camera';
    }
    
    // Start/stop video feed
    if (connected) {
        startVideoFeed();
    } else {
        stopVideoFeed();
    }
}

function startVideoFeed() {
    const videoEl = document.getElementById('liveVideoFeed');
    if (videoEl) {
        // Add timestamp to prevent caching
        videoEl.src = '/video_feed?' + new Date().getTime();
    }
}

function stopVideoFeed() {
    const videoEl = document.getElementById('liveVideoFeed');
    if (videoEl) {
        videoEl.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='480' viewBox='0 0 640 480'%3E%3Crect fill='%23222' width='640' height='480'/%3E%3Ctext x='320' y='240' text-anchor='middle' fill='%23666' font-family='sans-serif' font-size='20'%3ENo Camera Feed%3C/text%3E%3C/svg%3E";
    }
}

function updateLiveOcrDistance(distance) {
    const liveOcrValue = document.getElementById('liveOcrValue');
    if (!liveOcrValue) return;
    
    if (distance === null || distance === undefined || isNaN(distance)) {
        liveOcrValue.textContent = '---.---';
        return;
    }
    
    liveOcrValue.textContent = distance.toFixed(3);
}

function updateOcrReading(value, timestamp, extraData = null) {
    lastOcrReading = value;
    
    // Format value with 3 decimal places
    const formattedValue = value !== null && value !== undefined ? value.toFixed(3) : '---.---';
    
    // Update small OCR value in manual input panel
    const ocrValueSmall = document.getElementById('ocrValueSmall');
    if (ocrValueSmall) {
        ocrValueSmall.textContent = formattedValue;
    }
    
    // Update KPI
    const kpiLevelOcr = document.getElementById('kpiLevelOcr');
    if (kpiLevelOcr) {
        kpiLevelOcr.textContent = formattedValue;
    }
    
    // Update KPI status with water level status if available
    const kpiLevelOcrStatus = document.getElementById('kpiLevelOcrStatus');
    if (kpiLevelOcrStatus && extraData) {
        if (extraData.status_message) {
            kpiLevelOcrStatus.textContent = extraData.status_message;
            // Color based on status
            switch (extraData.status) {
                case 'critical':
                    kpiLevelOcrStatus.style.color = '#dd3333';
                    break;
                case 'warning':
                    kpiLevelOcrStatus.style.color = '#ff9933';
                    break;
                case 'low':
                    kpiLevelOcrStatus.style.color = '#ff9933';
                    break;
                default:
                    kpiLevelOcrStatus.style.color = '#00aa66';
            }
        }
    }
    
    // Update last update time
    const lastUpdateTime = document.getElementById('lastUpdateTime');
    if (lastUpdateTime && timestamp) {
        lastUpdateTime.textContent = new Date(timestamp).toLocaleTimeString();
    }
    
    // Update status
    const ocrStatus = document.getElementById('ocrStatus');
    if (ocrStatus) {
        ocrStatus.textContent = 'Reading successfully';
        ocrStatus.style.color = '#00aa66';
    }
}

function displayOcrResult(data) {
    if (data.success && data.reading !== null) {
        const formattedValue = data.reading.toFixed(3);
        lastOcrReading = data.reading;
        
        // Update Live OCR card near video
        const liveOcrValue = document.getElementById('liveOcrValue');
        if (liveOcrValue) {
            liveOcrValue.textContent = formattedValue;
        }
        
        // Update small display
        const ocrValueSmall = document.getElementById('ocrValueSmall');
        if (ocrValueSmall) {
            ocrValueSmall.textContent = formattedValue;
        }
        
        // Update KPI
        const kpiLevelOcr = document.getElementById('kpiLevelOcr');
        if (kpiLevelOcr) {
            kpiLevelOcr.textContent = formattedValue;
        }
        
        const kpiLevelOcrStatus = document.getElementById('kpiLevelOcrStatus');
        if (kpiLevelOcrStatus) {
            kpiLevelOcrStatus.textContent = 'From test image';
            kpiLevelOcrStatus.style.color = '#0066cc';
        }
        
        // Update status
        const ocrStatus = document.getElementById('ocrStatus');
        if (ocrStatus) {
            ocrStatus.textContent = 'Test successful: ' + formattedValue + ' m';
            ocrStatus.style.color = '#00aa66';
        }
        
        // Update last update time
        const lastUpdateTime = document.getElementById('lastUpdateTime');
        if (lastUpdateTime) {
            lastUpdateTime.textContent = new Date(data.timestamp).toLocaleTimeString();
        }
        
        // Show annotated image in video feed area
        if (data.annotated_image) {
            const videoEl = document.getElementById('liveVideoFeed');
            if (videoEl) {
                videoEl.src = data.annotated_image;
            }
        }

        // If we are connected to a live stream, resume it shortly after showing the snapshot
        if (isCameraConnected) {
            setTimeout(() => {
                try { startVideoFeed(); } catch (e) { /* ignore */ }
            }, 1500);
        }
        
        alert('OCR Test Successful!\nDetected: ' + formattedValue + ' m');
    } else {
        alert('OCR Test Failed. Could not read the display.');
        
        const ocrStatus = document.getElementById('ocrStatus');
        if (ocrStatus) {
            ocrStatus.textContent = 'Test failed';
            ocrStatus.style.color = '#dd3333';
        }
    }
}

// ==================== OCR History Chart ====================

function updateOcrHistoryChart() {
    const ctx = document.getElementById('ocrHistoryChart');
    if (!ctx) return;
    
    const labels = ocrReadingHistory.map(r => r.timestamp.toLocaleTimeString());
    const data = ocrReadingHistory.map(r => r.value);
    
    if (chartInstances.ocrHistoryChart) {
        chartInstances.ocrHistoryChart.data.labels = labels;
        chartInstances.ocrHistoryChart.data.datasets[0].data = data;
        chartInstances.ocrHistoryChart.update();
    } else {
        chartInstances.ocrHistoryChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'OCR Water Level (m)',
                    data: data,
                    borderColor: '#0066cc',
                    backgroundColor: 'rgba(0, 102, 204, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 3,
                    pointBackgroundColor: '#0066cc'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    title: {
                        display: true,
                        text: 'Real-time OCR Readings from ESP-CAM'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Water Level (m)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    }
                }
            }
        });
    }
}

// ==================== Blockchain Functions ====================

function cyrb53(str, seed = 0) {
    let h1 = 0xdeadbeef ^ seed, h2 = 0x41c6ce57 ^ seed;
    for (let i = 0; i < str.length; i++) {
        let ch = str.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1>>>16), 2246822507) ^ Math.imul(h2 ^ (h2>>>13), 3266489917);
    h2 = Math.imul(h2 ^ (h2>>>16), 2246822507) ^ Math.imul(h1 ^ (h1>>>13), 3266489917);
    return (4294967296 * (2097151 & h2) + (h1>>>0)).toString(16);
}

function hashBlock(block) {
    const data = JSON.stringify({
        index: block.index,
        timestamp: block.timestamp,
        readings: block.readings,
        previousHash: block.previousHash,
        nonce: block.nonce
    });
    return cyrb53(data);
}

function createGenesisBlock() {
    const genesisBlock = {
        index: 0,
        timestamp: new Date().toISOString(),
        readings: [],
        previousHash: '0',
        nonce: 0,
        hash: ''
    };
    genesisBlock.hash = hashBlock(genesisBlock);
    blockchain.push(genesisBlock);
}

function mineBlock() {
    if (readings.length === 0) {
        alert('No readings to mine. Please add some readings first.');
        return;
    }

    const lastBlock = blockchain[blockchain.length - 1];
    const readingIds = readings.map(r => r.id);

    const newBlock = {
        index: blockchain.length,
        timestamp: new Date().toISOString(),
        readings: readingIds,
        previousHash: lastBlock.hash,
        nonce: 0,
        hash: ''
    };

    for (let i = 0; i < 100; i++) {
        newBlock.nonce = i;
        newBlock.hash = hashBlock(newBlock);
        if (newBlock.hash.startsWith('00')) {
            break;
        }
    }

    blockchain.push(newBlock);
    updateBlockchainUI();
}

function validateChain() {
    for (let i = 1; i < blockchain.length; i++) {
        const currentBlock = blockchain[i];
        const previousBlock = blockchain[i - 1];

        if (currentBlock.previousHash !== previousBlock.hash) {
            return false;
        }

        const recomputedHash = hashBlock(currentBlock);
        if (recomputedHash !== currentBlock.hash) {
            return false;
        }
    }
    return true;
}

// ==================== Event Listeners ====================

function setupEventListeners() {
    document.getElementById('inputForm').addEventListener('submit', handleAddReading);
    document.getElementById('clearAllBtn').addEventListener('click', handleClearAll);
    document.getElementById('downloadCsvBtn').addEventListener('click', downloadCsv);
    document.getElementById('mineBlockBtn').addEventListener('click', mineBlock);
    document.getElementById('validateChainBtn').addEventListener('click', () => {
        const isValid = validateChain();
        const status = isValid ? 'Valid' : 'Invalid';
        alert(`Chain Validation: ${status}`);
        updateBlockchainStatus();
    });
    document.getElementById('acknowledgeAlertsBtn').addEventListener('click', acknowledgeAlerts);
    
    // ESP-CAM Controls
    document.getElementById('connectCamBtn').addEventListener('click', handleConnectCamera);
    document.getElementById('disconnectCamBtn').addEventListener('click', handleDisconnectCamera);
    document.getElementById('testOcrBtn').addEventListener('click', handleTestOcr);
    document.getElementById('testOcrPathBtn').addEventListener('click', handleTestOcrPath);
    document.getElementById('useOcrValueBtn').addEventListener('click', handleUseOcrValue);
    
    // Sensor Simulation Controls
    const sensorSimValue = document.getElementById('sensorSimValue');
    const sensorDisplay = document.getElementById('sensorDisplay');
    if (sensorSimValue && sensorDisplay) {
        sensorSimValue.addEventListener('input', (e) => {
            sensorDisplay.textContent = parseFloat(e.target.value).toFixed(1);
        });
    }
    
    const addSensorReadingBtn = document.getElementById('addSensorReadingBtn');
    if (addSensorReadingBtn) {
        addSensorReadingBtn.addEventListener('click', handleAddSensorReading);
    }
}

async function handleTestOcrPath() {
    const pathInput = document.getElementById('testImagePath');
    const imagePath = pathInput.value.trim();
    
    if (!imagePath) {
        alert('Please enter an image path');
        return;
    }
    
    const ocrStatus = document.getElementById('ocrStatus');
    if (ocrStatus) {
        ocrStatus.textContent = 'Testing with: ' + imagePath;
        ocrStatus.style.color = '#666';
    }
    
    try {
        const response = await fetch('/api/test_ocr_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: imagePath })
        });
        
        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server not running or returned invalid response. Start the server with: python app.py');
        }
        
        const data = await response.json();
        
        if (response.ok) {
            displayOcrResult(data);
        } else {
            alert('Error: ' + (data.error || 'Failed to test OCR'));
            if (ocrStatus) {
                ocrStatus.textContent = 'Error: ' + (data.error || 'Test failed');
                ocrStatus.style.color = '#dd3333';
            }
        }
    } catch (error) {
        console.error('Test OCR path error:', error);
        alert('Error: ' + error.message + '\n\nMake sure the server is running:\npython app.py');
        if (ocrStatus) {
            ocrStatus.textContent = 'Server not running';
            ocrStatus.style.color = '#dd3333';
        }
    }
}

function handleDisconnectCamera() {
    stopVideoFeed();
    updateConnectionStatus(false);

    const liveOcrValue = document.getElementById('liveOcrValue');
    if (liveOcrValue) {
        liveOcrValue.textContent = '---.---';
    }
}

function handleConnectCamera() {
    const url = document.getElementById('espCamUrl').value.trim();
    if (!url) {
        alert('Please enter the ESP-CAM stream URL');
        return;
    }
    
    // Emit to server to start processing
    socket.emit('start_stream', { url: url });
    
    // Start MJPEG feed immediately (server will also confirm via stream_started)
    startVideoFeed();
}

async function handleTestOcr() {
    const ocrStatus = document.getElementById('ocrStatus');
    if (ocrStatus) {
        ocrStatus.textContent = 'Testing with sample image...';
        ocrStatus.style.color = '#666';
    }
    
    // Request test OCR via WebSocket if connected
    if (socket && socket.connected) {
        socket.emit('request_test_ocr');
        return;
    }
    
    // Fallback to HTTP API
    try {
        const response = await fetch('/api/test_ocr', { method: 'POST' });
        
        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server not running');
        }
        
        const data = await response.json();
        displayOcrResult(data);
    } catch (err) {
        console.error('OCR test failed:', err);
        alert('OCR test failed.\n\nMake sure the server is running:\npython app.py');
        if (ocrStatus) {
            ocrStatus.textContent = 'Server not running';
            ocrStatus.style.color = '#dd3333';
        }
    }
}

function handleUseOcrValue() {
    if (lastOcrReading !== null) {
        document.getElementById('waterLevel').value = lastOcrReading.toFixed(3);
    } else {
        alert('No OCR reading available. Test OCR first or connect camera.');
    }
}

function handleAddReading(e) {
    e.preventDefault();

    const waterLevel = parseFloat(document.getElementById('waterLevel').value);

    const reading = {
        id: readings.length + 1,
        timestamp: new Date().toISOString(),
        level_m: waterLevel
    };

    readings.push(reading);
    updateHydraulicsDisplay(waterLevel);
    document.getElementById('inputForm').reset();
    updateAllUI();
}

function handleClearAll() {
    if (confirm('Are you sure you want to clear all readings? This will reset charts and KPIs.')) {
        readings = [];
        hydraulicsHistory = [];
        acknowledgedAlerts = false;
        updateAllUI();
    }
}

function handleAddSensorReading() {
    const sensorValue = parseFloat(document.getElementById('sensorSimValue').value);
    
    const reading = {
        id: readings.length + 1,
        timestamp: new Date().toISOString(),
        level_m: sensorValue,
        source: 'sensor_simulation'
    };
    
    readings.push(reading);
    updateHydraulicsDisplay(sensorValue);
    updateAllUI();
    
    // Show confirmation
    const statusElement = document.getElementById('ocrStatus');
    if (statusElement) {
        statusElement.textContent = `Sensor reading added: ${sensorValue.toFixed(1)}m`;
        statusElement.style.color = '#00aa66';
    }
}

// ==================== UI Updates ====================

function updateAllUI() {
    updateKPIs();
    updateDashboard();
    updateCharts();
    updateAlerts();
    updateBlockchainUI();
}

function updateKPIs() {
    const latestReading = readings.length > 0 ? readings[readings.length - 1] : null;
    const previousReading = readings.length > 1 ? readings[readings.length - 2] : null;

    if (!latestReading) {
        document.getElementById('kpiLevel').textContent = '-';
        document.getElementById('kpiLevelTrend').textContent = 'No data';
        document.getElementById('kpiAlerts').textContent = '0';
        document.getElementById('kpiAlertsStatus').textContent = 'No alerts';
        return;
    }

    document.getElementById('kpiLevel').textContent = latestReading.level_m.toFixed(2);
    const levelTrend = getTrend(previousReading?.level_m, latestReading.level_m);
    document.getElementById('kpiLevelTrend').textContent = levelTrend;

    const alerts = getActiveAlerts(latestReading);
    document.getElementById('kpiAlerts').textContent = alerts.length;
    const alertStatus = alerts.length === 0 ? 'No alerts' : `${alerts.length} active`;
    document.getElementById('kpiAlertsStatus').textContent = alertStatus;
}

function getTrend(previous, current) {
    if (previous === undefined || previous === null) return 'No previous data';
    const diff = current - previous;
    if (Math.abs(diff) < 0.01) return 'Stable';
    return diff > 0 ? 'Rising' : 'Falling';
}

// ==================== Reservoir Dashboard ====================

function updateDashboard() {
    // Get the latest reading
    const latestReading = readings.length > 0 ? readings[readings.length - 1] : null;
    
    if (!latestReading) {
        // No data yet, show default values
        document.getElementById('liveLevel').textContent = '-- %';
        document.getElementById('excessPercent').textContent = '0 %';
        document.getElementById('excessVolume').textContent = '0 m³';
        updateDashboardCardStates(0);
        return;
    }
    
    // Get configuration values
    const maxWaterLevel = currentConfig?.dam?.max_water_level || 120.0;
    const minWaterLevel = currentConfig?.dam?.min_water_level || 0.0;
    const safeThreshold = currentConfig?.dam?.critical_threshold_percent || SAFE_STORAGE_PERCENT;
    const reservoirCapacity = RESERVOIR_CAPACITY_M3; // Can be extended to use config if needed
    
    // Calculate Live Level (%)
    // Linear mapping from min to max water level to 0-100%
    const actualWaterRange = maxWaterLevel - minWaterLevel;
    const currentWaterAboveMin = latestReading.level_m - minWaterLevel;
    const liveLevel = (currentWaterAboveMin / actualWaterRange) * 100;
    
    // Clamp to 0-100
    const liveLevelClamped = Math.max(0, Math.min(100, liveLevel));
    
    // Calculate Excess
    let excessPercentage = 0;
    let excessVolume = 0;
    
    if (liveLevelClamped > safeThreshold) {
        excessPercentage = liveLevelClamped - safeThreshold;
        excessVolume = (excessPercentage / 100) * reservoirCapacity;
    }
    
    // Update dashboard cards
    document.getElementById('liveLevel').textContent = liveLevelClamped.toFixed(1) + ' %';
    document.getElementById('safeThreshold').textContent = safeThreshold.toFixed(0) + ' %';
    document.getElementById('excessPercent').textContent = excessPercentage.toFixed(1) + ' %';
    document.getElementById('excessVolume').textContent = excessVolume.toFixed(0) + ' m³';
    
    // Update card states based on level
    updateDashboardCardStates(liveLevelClamped, safeThreshold);
    
    // Store for potential use
    lastWaterLevelPercent = liveLevelClamped;
    lastExcessPercent = excessPercentage;
    lastExcessVolumeM3 = excessVolume;
}

function updateDashboardCardStates(liveLevel, safeThreshold = 90) {
    // Get card elements
    const liveLevelCard = document.querySelector('.dashboard-card:nth-of-type(1)');
    const safeThresholdCard = document.querySelector('.dashboard-card:nth-of-type(2)');
    const excessPercentCard = document.querySelector('.dashboard-card:nth-of-type(3)');
    const excessVolumeCard = document.querySelector('.dashboard-card:nth-of-type(4)');
    
    // Remove all state classes
    [liveLevelCard, safeThresholdCard, excessPercentCard, excessVolumeCard].forEach(card => {
        if (card) {
            card.classList.remove('warning', 'critical', 'safe');
        }
    });
    
    // Apply state based on live level
    // Critical at 95% or more above safe threshold
    const criticalThreshold = Math.min(95, safeThreshold + 5);
    // Warning between 85% and critical
    const warningThreshold = Math.max(safeThreshold + 2, 85);
    
    if (liveLevel >= criticalThreshold) {
        // Critical
        liveLevelCard?.classList.add('critical');
        excessPercentCard?.classList.add('critical');
        excessVolumeCard?.classList.add('critical');
    } else if (liveLevel >= warningThreshold) {
        // Warning
        liveLevelCard?.classList.add('warning');
        excessPercentCard?.classList.add('warning');
        excessVolumeCard?.classList.add('warning');
    } else {
        // Safe
        liveLevelCard?.classList.add('safe');
    }
    
    // Safe threshold is always static
    safeThresholdCard?.classList.add('safe');
}

function getActiveAlerts(reading) {
    const alerts = [];

    if (reading.level_m > THRESHOLDS.levelHigh) {
        alerts.push({
            type: 'High Water Level',
            parameter: 'Water Level',
            value: reading.level_m,
            threshold: THRESHOLDS.levelHigh,
            message: `Water level ${reading.level_m}m exceeds threshold ${THRESHOLDS.levelHigh}m`
        });
    }

    return acknowledgedAlerts ? [] : alerts;
}

function updateAlerts() {
    const latestReading = readings.length > 0 ? readings[readings.length - 1] : null;
    const alerts = latestReading ? getActiveAlerts(latestReading) : [];

    document.getElementById('alertBadge').textContent = alerts.length;

    const container = document.getElementById('alertsContainer');
    const acknowledgeBtn = document.getElementById('acknowledgeAlertsBtn');

    if (alerts.length === 0) {
        container.innerHTML = '<p class="no-alerts">No alerts</p>';
        acknowledgeBtn.style.display = 'none';
    } else {
        acknowledgeBtn.style.display = 'block';
        container.innerHTML = alerts.map((alert, idx) => `
            <div class="alert-item">
                <div class="alert-info">
                    <div class="alert-time">${new Date(latestReading.timestamp).toLocaleTimeString()}</div>
                    <div class="alert-message">${alert.type}</div>
                    <div class="alert-detail">${alert.message}</div>
                </div>
            </div>
        `).join('');
    }
}

function acknowledgeAlerts() {
    acknowledgedAlerts = true;
    updateAlerts();
    document.getElementById('kpiAlerts').textContent = '0';
    document.getElementById('kpiAlertsStatus').textContent = 'No alerts';
}

function updateCharts() {
    updateLevelChart();
    updateSpillwayChart();
    updateOutletChart();
    updateTotalOutflowChart();
    updateRuleCurveChart();
}

function updateLevelChart() {
    const ctx = document.getElementById('levelChart');
    if (!ctx) return;

    const data = readings.map(r => ({
        x: new Date(r.timestamp).toLocaleTimeString(),
        y: r.level_m
    }));

    if (chartInstances.levelChart) {
        chartInstances.levelChart.data.labels = data.map(d => d.x);
        chartInstances.levelChart.data.datasets[0].data = data.map(d => d.y);
        chartInstances.levelChart.update();
    } else {
        chartInstances.levelChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.x),
                datasets: [{
                    label: 'Water Level (m)',
                    data: data.map(d => d.y),
                    borderColor: '#0066cc',
                    backgroundColor: 'rgba(0, 102, 204, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }
}

// Hydraulics history for discharge-over-time charts (filled when API returns)
let hydraulicsHistory = [];
const HYDRAULICS_HISTORY_MAX = 50;

function updateSpillwayChart() {
    const ctx = document.getElementById('spillwayChart');
    if (!ctx) return;

    const data = hydraulicsHistory.map(h => ({
        x: new Date(h.timestamp).toLocaleTimeString(),
        y: h.spillway
    }));

    if (chartInstances.spillwayChart) {
        chartInstances.spillwayChart.data.labels = data.map(d => d.x);
        chartInstances.spillwayChart.data.datasets[0].data = data.map(d => d.y);
        chartInstances.spillwayChart.update();
    } else {
        chartInstances.spillwayChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.x),
                datasets: [{
                    label: 'Spillway Discharge (m³/s)',
                    data: data.map(d => d.y),
                    borderColor: '#0066cc',
                    backgroundColor: 'rgba(0, 102, 204, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: true, position: 'top' } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }
}

function updateOutletChart() {
    const ctx = document.getElementById('outletChart');
    if (!ctx) return;

    const data = hydraulicsHistory.map(h => ({
        x: new Date(h.timestamp).toLocaleTimeString(),
        y: h.outlet
    }));

    if (chartInstances.outletChart) {
        chartInstances.outletChart.data.labels = data.map(d => d.x);
        chartInstances.outletChart.data.datasets[0].data = data.map(d => d.y);
        chartInstances.outletChart.update();
    } else {
        chartInstances.outletChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.x),
                datasets: [{
                    label: 'Outlet Discharge (m³/s)',
                    data: data.map(d => d.y),
                    borderColor: '#00aa66',
                    backgroundColor: 'rgba(0, 170, 102, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: true, position: 'top' } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }
}

function updateTotalOutflowChart() {
    const ctx = document.getElementById('totalOutflowChart');
    if (!ctx) return;

    const data = hydraulicsHistory.map(h => ({
        x: new Date(h.timestamp).toLocaleTimeString(),
        y: h.total
    }));

    if (chartInstances.totalOutflowChart) {
        chartInstances.totalOutflowChart.data.labels = data.map(d => d.x);
        chartInstances.totalOutflowChart.data.datasets[0].data = data.map(d => d.y);
        chartInstances.totalOutflowChart.update();
    } else {
        chartInstances.totalOutflowChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.x),
                datasets: [{
                    label: 'Total Outflow (m³/s)',
                    data: data.map(d => d.y),
                    borderColor: '#9944cc',
                    backgroundColor: 'rgba(153, 68, 204, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: true, position: 'top' } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }
}

function normalize(value, range) {
    const { min, max } = range;
    const normalized = ((value - min) / (max - min)) * 100;
    return Math.max(0, Math.min(100, normalized));
}

function formatDateLabel(date) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const d = new Date(date);
    const day = String(d.getDate()).padStart(2, '0');
    const month = months[d.getMonth()];
    return `${day}-${month}`;
}

function updateRuleCurveChart() {
    const ctx = document.getElementById('ruleCurveChart');
    if (!ctx) return;

    const labels = readings.map(r => formatDateLabel(r.timestamp));
    const data = readings.map(r => r.level_m);

    if (chartInstances.ruleCurveChart) {
        chartInstances.ruleCurveChart.data.labels = labels;
        chartInstances.ruleCurveChart.data.datasets[0].data = data;
        chartInstances.ruleCurveChart.update();
    } else {
        chartInstances.ruleCurveChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Observed Level (Manual Readings)',
                    data: data,
                    borderColor: '#87ceeb',
                    backgroundColor: 'rgba(135, 206, 235, 0.2)',
                    tension: 0.3,
                    fill: true,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Water Level in Meters'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Date'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Water Level (m)'
                        }
                    }
                }
            }
        });
    }
}

function updateBlockchainUI() {
    updateBlockchainStatus();
    updateBlockchainTimeline();
    updateTransactionTable();
}

function updateBlockchainStatus() {
    const isValid = validateChain();
    const status = isValid ? 'Valid' : 'Invalid';
    const statusColor = isValid ? '#00aa66' : '#dd3333';

    const statusEl = document.getElementById('chainStatus');
    statusEl.innerHTML = `Chain Length: ${blockchain.length} | Status: <span style="color: ${statusColor}; font-weight: bold;">${status}</span>`;
}

function updateBlockchainTimeline() {
    const timeline = document.getElementById('blockchainTimeline');
    timeline.innerHTML = blockchain.map((block, idx) => `
        <div class="block-item">
            <div class="block-index">Block #${block.index}</div>
            <div class="block-hash">Hash: ${block.hash.substring(0, 12)}...</div>
            <div class="block-time">${new Date(block.timestamp).toLocaleString()}</div>
            <div class="block-time">Readings: ${block.readings.length}</div>
        </div>
    `).join('');
}

function updateTransactionTable() {
    const tbody = document.querySelector('#transactionTable tbody');

    if (readings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-data">No readings yet</td></tr>';
        return;
    }

    tbody.innerHTML = readings.map(reading => {
        let blockIndex = 'Pending';
        for (let block of blockchain) {
            if (block.readings.includes(reading.id)) {
                blockIndex = block.index;
                break;
            }
        }

        return `
            <tr>
                <td>${reading.id}</td>
                <td>${new Date(reading.timestamp).toLocaleString()}</td>
                <td>${reading.level_m.toFixed(2)}</td>
                <td>${blockIndex}</td>
            </tr>
        `;
    }).join('');
}

function downloadCsv() {
    if (readings.length === 0) {
        alert('No readings to download');
        return;
    }

    const headers = ['reading_id', 'timestamp', 'level_m', 'block_index'];
    const rows = readings.map(reading => {
        let blockIndex = 'Pending';
        for (let block of blockchain) {
            if (block.readings.includes(reading.id)) {
                blockIndex = block.index;
                break;
            }
        }

        return [
            reading.id,
            reading.timestamp,
            reading.level_m.toFixed(2),
            blockIndex
        ];
    });

    const csvContent = [
        headers.join(','),
        ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);

    link.setAttribute('href', url);
    link.setAttribute('download', 'manual_dam_readings.csv');
    link.click();

    URL.revokeObjectURL(url);
}

// ==================== Settings Modal ====================

let currentConfig = {};

function setupSettingsListeners() {
    // Settings button
    const settingsBtn = document.getElementById('settingsBtn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', openSettingsModal);
    }
    
    // Close button
    const closeBtn = document.getElementById('closeSettingsBtn');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeSettingsModal);
    }
    
    // Click outside to close
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeSettingsModal();
            }
        });
    }
    
    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            switchTab(tabId);
        });
    });
    
    // Save button
    const saveBtn = document.getElementById('saveSettingsBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveSettings);
    }
    
    // Reset defaults button
    const resetBtn = document.getElementById('resetDefaultsBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetToDefaults);
    }
    
    // Reset OCR bounds button
    const resetOcrBtn = document.getElementById('resetOcrBoundsBtn');
    if (resetOcrBtn) {
        resetOcrBtn.addEventListener('click', resetOcrBounds);
    }
    
}

function openSettingsModal() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.classList.add('active');
        loadSettings();
    }
}

function closeSettingsModal() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function switchTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === tabId);
    });
}

async function loadSettings() {
    try {
        const response = await fetch('/api/config/file');
        if (!response.ok) throw new Error('Failed to load settings');
        
        currentConfig = await response.json();
        populateSettingsForm(currentConfig);
    } catch (error) {
        console.error('Error loading settings:', error);
        alert('Failed to load settings: ' + error.message);
    }
}

function populateSettingsForm(config) {
    // Dam settings
    if (config.dam) {
        setInputValue('cfgDamName', config.dam.dam_name);
        setInputValue('cfgLocation', config.dam.location);
        setInputValue('cfgDeviceHeight', config.dam.device_height);
        setInputValue('cfgMinWaterLevel', config.dam.min_water_level);
        setInputValue('cfgMaxWaterLevel', config.dam.max_water_level);
        setInputValue('cfgUnit', config.dam.unit);
        setInputValue('cfgCriticalThreshold', config.dam.critical_threshold_percent);
        setInputValue('cfgWarningThreshold', config.dam.warning_threshold_percent);
        setInputValue('cfgLowThreshold', config.dam.low_water_threshold_percent);
        
        // Update dam name in header
        const header = document.getElementById('damNameHeader');
        if (header && config.dam.dam_name) {
            header.textContent = config.dam.dam_name;
        }
    }
    
    // OCR settings
    if (config.ocr) {
        if (config.ocr.roi) {
            setInputValue('cfgRoiXStart', config.ocr.roi.x_start_pct);
            setInputValue('cfgRoiXEnd', config.ocr.roi.x_end_pct);
            setInputValue('cfgRoiYStart', config.ocr.roi.y_start_pct);
            setInputValue('cfgRoiYEnd', config.ocr.roi.y_end_pct);
        }
        setInputValue('cfgDecimalPosition', config.ocr.decimal_position);
        setInputValue('cfgDigitsAfterDecimal', config.ocr.expected_digits_after_decimal);
    }
    
    // Hydraulics settings
    if (config.hydraulics) {
        setInputValue('cfgReservoirArea', config.hydraulics.reservoir_area);
        setInputValue('cfgSpillwayCrest', config.hydraulics.spillway_crest_level);
        setInputValue('cfgSpillwayLength', config.hydraulics.spillway_length);
        setInputValue('cfgSpillwayCoeff', config.hydraulics.spillway_coefficient);
        setInputValue('cfgNumGates', config.hydraulics.num_spillway_gates);
        setInputValue('cfgGateWidth', config.hydraulics.gate_width);
        setInputValue('cfgGateCoeff', config.hydraulics.gate_coefficient);
        setInputValue('cfgGateOpening', config.hydraulics.gate_opening);
        setInputValue('cfgOutletArea', config.hydraulics.outlet_area);
        setInputValue('cfgOutletCoeff', config.hydraulics.outlet_coefficient);
        setInputValue('cfgOutletLevel', config.hydraulics.outlet_level);
        setInputValue('cfgManualInflow', config.hydraulics.manual_inflow);
        setInputValue('cfgManualOutflow', config.hydraulics.manual_outflow);
        
        const useCalcDischarge = document.getElementById('cfgUseCalcDischarge');
        if (useCalcDischarge) {
            useCalcDischarge.checked = config.hydraulics.use_calculated_discharge !== false;
        }
        const useCalcSpillway = document.getElementById('cfgUseCalcSpillway');
        if (useCalcSpillway) {
            useCalcSpillway.checked = config.hydraulics.use_calculated_spillway !== false;
        }
        
        // Update gate opening input on main page
        const gateInput = document.getElementById('gateOpeningInput');
        if (gateInput) {
            gateInput.value = config.hydraulics.gate_opening || 0;
        }
    }
    
    // ESP-CAM settings
    if (config.esp_cam) {
        setInputValue('cfgEspCamUrl', config.esp_cam.url);
        const autoConnect = document.getElementById('cfgAutoConnect');
        if (autoConnect) {
            autoConnect.checked = config.esp_cam.auto_connect || false;
        }
    }
}

function setInputValue(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
        el.value = value;
    }
}

function getInputValue(id, type = 'string') {
    const el = document.getElementById(id);
    if (!el) return null;
    
    const value = el.value.trim();
    if (value === '') return null;
    
    if (type === 'number') {
        return parseFloat(value);
    } else if (type === 'int') {
        return parseInt(value, 10);
    }
    return value;
}

async function saveSettings() {
    const config = {
        dam: {
            dam_name: getInputValue('cfgDamName') || 'Dam Water Level Monitor',
            location: getInputValue('cfgLocation') || '',
            device_height: getInputValue('cfgDeviceHeight', 'number') || 120.0,
            min_water_level: getInputValue('cfgMinWaterLevel', 'number') || 0.0,
            max_water_level: getInputValue('cfgMaxWaterLevel', 'number') || 120.0,
            unit: getInputValue('cfgUnit') || 'm',
            critical_threshold_percent: getInputValue('cfgCriticalThreshold', 'number') || 90.0,
            warning_threshold_percent: getInputValue('cfgWarningThreshold', 'number') || 80.0,
            low_water_threshold_percent: getInputValue('cfgLowThreshold', 'number') || 20.0
        },
        ocr: {
            roi: {
                x_start_pct: getInputValue('cfgRoiXStart', 'number') || 0.28,
                x_end_pct: getInputValue('cfgRoiXEnd', 'number') || 0.78,
                y_start_pct: getInputValue('cfgRoiYStart', 'number') || 0.78,
                y_end_pct: getInputValue('cfgRoiYEnd', 'number') || 0.98
            },
            decimal_position: getInputValue('cfgDecimalPosition', 'int') || 1,
            expected_digits_after_decimal: getInputValue('cfgDigitsAfterDecimal', 'int') || 3
        },
        hydraulics: {
            reservoir_area: getInputValue('cfgReservoirArea', 'number') || 1000.0,
            spillway_crest_level: getInputValue('cfgSpillwayCrest', 'number') || 8.0,
            spillway_length: getInputValue('cfgSpillwayLength', 'number') || 10.0,
            spillway_coefficient: getInputValue('cfgSpillwayCoeff', 'number') || 1.84,
            num_spillway_gates: getInputValue('cfgNumGates', 'int') || 3,
            gate_width: getInputValue('cfgGateWidth', 'number') || 3.0,
            gate_coefficient: getInputValue('cfgGateCoeff', 'number') || 0.6,
            gate_opening: getInputValue('cfgGateOpening', 'number') || 0.0,
            outlet_area: getInputValue('cfgOutletArea', 'number') || 2.0,
            outlet_coefficient: getInputValue('cfgOutletCoeff', 'number') || 0.62,
            outlet_level: getInputValue('cfgOutletLevel', 'number') || 2.0,
            manual_inflow: getInputValue('cfgManualInflow', 'number') || 0.0,
            manual_outflow: getInputValue('cfgManualOutflow', 'number') || 0.0,
            use_calculated_discharge: document.getElementById('cfgUseCalcDischarge')?.checked !== false,
            use_calculated_spillway: document.getElementById('cfgUseCalcSpillway')?.checked !== false
        },
        esp_cam: {
            url: getInputValue('cfgEspCamUrl') || '',
            auto_connect: document.getElementById('cfgAutoConnect')?.checked || false
        }
    };
    
    try {
        const response = await fetch('/api/config/file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        if (!response.ok) throw new Error('Failed to save settings');
        
        const result = await response.json();
        currentConfig = result.config;
        
        // Update header with new dam name
        const header = document.getElementById('damNameHeader');
        if (header && config.dam.dam_name) {
            header.textContent = config.dam.dam_name;
        }
        
        alert('Settings saved successfully!');
        closeSettingsModal();
    } catch (error) {
        console.error('Error saving settings:', error);
        alert('Failed to save settings: ' + error.message);
    }
}

async function resetToDefaults() {
    if (!confirm('Are you sure you want to reset all settings to defaults?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/config/reset', {
            method: 'POST'
        });
        
        if (!response.ok) throw new Error('Failed to reset settings');
        
        const result = await response.json();
        currentConfig = result.config;
        populateSettingsForm(currentConfig);
        
        alert('Settings reset to defaults!');
    } catch (error) {
        console.error('Error resetting settings:', error);
        alert('Failed to reset settings: ' + error.message);
    }
}

async function resetOcrBounds() {
    try {
        const response = await fetch('/api/ocr_config/reset_bounds', {
            method: 'POST'
        });
        
        if (!response.ok) throw new Error('Failed to reset OCR bounds');
        
        alert('OCR boundaries reset!');
    } catch (error) {
        console.error('Error resetting OCR bounds:', error);
        alert('Failed to reset OCR bounds: ' + error.message);
    }
}

// Load settings on page load to get dam name
async function loadInitialSettings() {
    try {
        const response = await fetch('/api/config/file');
        if (!response.ok) return;
        
        const config = await response.json();
        
        // Update dam name in header
        if (config.dam && config.dam.dam_name) {
            const header = document.getElementById('damNameHeader');
            if (header) {
                header.textContent = config.dam.dam_name;
            }
        }
        
        // Auto-connect to camera if configured
        if (config.esp_cam && config.esp_cam.auto_connect && config.esp_cam.url) {
            const urlInput = document.getElementById('espCamUrl');
            if (urlInput) {
                urlInput.value = config.esp_cam.url;
            }
            // Trigger connect after a short delay
            setTimeout(() => {
                handleConnectCamera();
            }, 1000);
        }
    } catch (error) {
        console.error('Error loading initial settings:', error);
    }
}

// ==================== History Export Functions ====================

function setupHistoryListeners() {
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const exportJsonBtn = document.getElementById('exportJsonBtn');
    const previewBtn = document.getElementById('previewHistoryBtn');
    const clearBtn = document.getElementById('clearHistoryBtn');
    
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', () => exportHistory('csv'));
    }
    if (exportJsonBtn) {
        exportJsonBtn.addEventListener('click', () => exportHistory('json'));
    }
    if (previewBtn) {
        previewBtn.addEventListener('click', previewHistory);
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', clearHistoryData);
    }
    
    // Load history stats on page load
    loadHistoryStats();
}

async function loadHistoryStats() {
    try {
        const response = await fetch('/api/history/stats');
        if (!response.ok) return;
        
        const stats = await response.json();
        
        const totalEl = document.getElementById('historyTotalEntries');
        const rangeEl = document.getElementById('historyDateRange');
        
        if (totalEl) {
            totalEl.textContent = stats.total_entries || 0;
        }
        
        if (rangeEl) {
            if (stats.oldest_entry && stats.newest_entry) {
                const oldest = new Date(stats.oldest_entry).toLocaleDateString();
                const newest = new Date(stats.newest_entry).toLocaleDateString();
                rangeEl.textContent = `${oldest} to ${newest} (${stats.date_range_days || 0} days)`;
            } else {
                rangeEl.textContent = 'No data';
            }
        }
    } catch (error) {
        console.error('Error loading history stats:', error);
    }
}

function getDateFilters() {
    const startDate = document.getElementById('historyStartDate')?.value || '';
    const endDate = document.getElementById('historyEndDate')?.value || '';
    return { startDate, endDate };
}

async function exportHistory(format) {
    const { startDate, endDate } = getDateFilters();
    
    let url = `/api/history/export/${format}?`;
    if (startDate) url += `start_date=${startDate}&`;
    if (endDate) url += `end_date=${endDate}&`;
    
    // Open download in new tab/trigger download
    window.location.href = url;
    
    // Show feedback
    const btn = format === 'csv' ? 
        document.getElementById('exportCsvBtn') : 
        document.getElementById('exportJsonBtn');
    
    if (btn) {
        const originalText = btn.textContent;
        btn.textContent = 'Downloading...';
        btn.disabled = true;
        
        setTimeout(() => {
            btn.textContent = originalText;
            btn.disabled = false;
        }, 2000);
    }
}

async function previewHistory() {
    const { startDate, endDate } = getDateFilters();
    
    let url = `/api/history?limit=20`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;
    
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load history');
        
        const data = await response.json();
        
        const preview = document.getElementById('historyPreview');
        const tbody = document.querySelector('#historyPreviewTable tbody');
        
        if (preview && tbody) {
            if (data.entries && data.entries.length > 0) {
                tbody.innerHTML = data.entries.map(entry => `
                    <tr>
                        <td>${new Date(entry.timestamp).toLocaleString()}</td>
                        <td>${entry.distance?.toFixed(3) || '--'}</td>
                        <td>${entry.water_level?.toFixed(3) || '--'}</td>
                        <td>${entry.percentage?.toFixed(1) || '--'}%</td>
                        <td>${entry.status || '--'}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="no-data">No data for selected range</td></tr>';
            }
            
            preview.style.display = 'block';
        }
        
        // Update count display
        const countInfo = document.createElement('span');
        countInfo.textContent = ` (showing ${data.entries.length} of ${data.count} filtered entries)`;
        
    } catch (error) {
        console.error('Error loading history preview:', error);
        alert('Failed to load history: ' + error.message);
    }
}

async function clearHistoryData() {
    if (!confirm('Are you sure you want to clear all reading history? This cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/history/clear', {
            method: 'POST'
        });
        
        if (!response.ok) throw new Error('Failed to clear history');
        
        alert('History cleared successfully');
        loadHistoryStats();
        
        // Hide preview if visible
        const preview = document.getElementById('historyPreview');
        if (preview) {
            preview.style.display = 'none';
        }
    } catch (error) {
        console.error('Error clearing history:', error);
        alert('Failed to clear history: ' + error.message);
    }
}

// ==================== Hydraulics Functions ====================

let lastWaterLevel = null;
let previousWaterLevel = null;
let lastLevelUpdateTime = null;

function setupHydraulicsListeners() {
    // Gate control button
    const setGateBtn = document.getElementById('setGateBtn');
    if (setGateBtn) {
        setGateBtn.addEventListener('click', handleSetGate);
    }

    // Gate rotation / time calculators
    const calcRotationsBtn = document.getElementById('calcRotationsBtn');
    if (calcRotationsBtn) {
        calcRotationsBtn.addEventListener('click', handleCalcGateRotations);
    }

    const calcOpenTimeBtn = document.getElementById('calcOpenTimeBtn');
    if (calcOpenTimeBtn) {
        calcOpenTimeBtn.addEventListener('click', handleCalcGateOpenTime);
    }
}

async function handleSetGate() {
    const gateInput = document.getElementById('gateOpeningInput');
    const gateStatus = document.getElementById('gateStatus');
    
    if (!gateInput) return;
    
    const gateOpening = parseFloat(gateInput.value) || 0;
    
    try {
        const response = await fetch('/api/hydraulics/gate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gate_opening: gateOpening })
        });
        
        if (!response.ok) throw new Error('Failed to set gate');
        
        const result = await response.json();
        if (gateStatus) {
            gateStatus.textContent = result.message;
            setTimeout(() => { gateStatus.textContent = ''; }, 3000);
        }
        
        // Refresh hydraulics display
        updateHydraulicsDisplay();
    } catch (error) {
        console.error('Error setting gate:', error);
        if (gateStatus) {
            gateStatus.textContent = 'Error: ' + error.message;
            gateStatus.style.color = '#dd3333';
        }
    }
}

async function updateHydraulicsDisplay(waterLevel = null) {
    // Use provided water level or last known
    const level = waterLevel || lastWaterLevel;
    if (level === null) return;
    
    try {
        // Calculate time interval for inflow calculation
        let timeInterval = 60;
        if (lastLevelUpdateTime) {
            timeInterval = (Date.now() - lastLevelUpdateTime) / 1000;
        }
        
        let url = `/api/hydraulics/all?water_level=${level}`;
        if (previousWaterLevel !== null) {
            url += `&previous_level=${previousWaterLevel}&time_interval=${timeInterval}`;
        }
        
        const response = await fetch(url);
        if (!response.ok) return;
        
        const data = await response.json();

        // Append to hydraulics history for discharge-over-time charts
        hydraulicsHistory.push({
            timestamp: new Date().toISOString(),
            waterLevel: level,
            spillway: (data.spillway && data.spillway.total_spillway_discharge != null) ? data.spillway.total_spillway_discharge : 0,
            outlet: (data.outlet && data.outlet.outlet_discharge != null) ? data.outlet.outlet_discharge : 0,
            total: (data.total_discharge != null) ? data.total_discharge : 0
        });
        if (hydraulicsHistory.length > HYDRAULICS_HISTORY_MAX) {
            hydraulicsHistory = hydraulicsHistory.slice(-HYDRAULICS_HISTORY_MAX);
        }
        updateSpillwayChart();
        updateOutletChart();
        updateTotalOutflowChart();
        
        // Update spillway display
        const kpiSpillway = document.getElementById('kpiSpillway');
        const kpiSpillwayStatus = document.getElementById('kpiSpillwayStatus');
        if (kpiSpillway && data.spillway) {
            kpiSpillway.textContent = data.spillway.total_spillway_discharge.toFixed(2);
            if (kpiSpillwayStatus) {
                kpiSpillwayStatus.textContent = data.spillway.discharge_type || 'No overflow';
                if (data.spillway.head_over_crest > 0) {
                    kpiSpillwayStatus.textContent += ` (Head: ${data.spillway.head_over_crest.toFixed(2)}m)`;
                }
            }
        }
        
        // Update outlet display
        const kpiOutlet = document.getElementById('kpiOutlet');
        const kpiOutletStatus = document.getElementById('kpiOutletStatus');
        if (kpiOutlet && data.outlet) {
            kpiOutlet.textContent = data.outlet.outlet_discharge.toFixed(2);
            if (kpiOutletStatus) {
                kpiOutletStatus.textContent = `Head: ${data.outlet.head_above_outlet.toFixed(2)}m`;
            }
        }
        
        // Update total outflow
        const kpiTotalOutflow = document.getElementById('kpiTotalOutflow');
        const kpiOutflowStatus = document.getElementById('kpiOutflowStatus');
        if (kpiTotalOutflow) {
            kpiTotalOutflow.textContent = data.total_discharge.toFixed(2);
            if (kpiOutflowStatus) {
                kpiOutflowStatus.textContent = 'Spillway + Outlet';
            }
        }
        
    } catch (error) {
        console.error('Error updating hydraulics:', error);
    }
}

// -------- Sluice gate rotations (N) and open time (t) --------

function getWaterLevelForGateInput(inputId) {
    const inputEl = document.getElementById(inputId);
    const raw = inputEl ? inputEl.value.trim() : '';
    if (raw !== '') {
        const v = parseFloat(raw);
        if (!isNaN(v)) return v;
    }
    // Fallback: use last OCR-based water level if available
    if (lastWaterLevel !== null && lastWaterLevel !== undefined) {
        return lastWaterLevel;
    }
    return null;
}

function getPitchForGateInput(inputId) {
    const inputEl = document.getElementById(inputId);
    const raw = inputEl ? inputEl.value.trim() : '';
    if (raw === '') return DEFAULT_GATE_PITCH;
    const v = parseFloat(raw);
    return isNaN(v) || v <= 0 ? DEFAULT_GATE_PITCH : v;
}

async function handleCalcGateRotations() {
    const dischargeInput = document.getElementById('gateTargetDischarge');
    const rotationsValueEl = document.getElementById('gateRotationsValue');
    const rotationsMsgEl = document.getElementById('gateRotationsMessage');

    const q = dischargeInput ? parseFloat(dischargeInput.value) : NaN;
    if (isNaN(q) || q < 0) {
        alert('Enter a valid non‑negative discharge Q (m³/s).');
        return;
    }

    const waterLevel = getWaterLevelForGateInput('gateWaterLevel');
    if (waterLevel === null) {
        alert('Water level H is required. Use OCR reading or enter manually.');
        return;
    }

    const pitch = getPitchForGateInput('gatePitch');

    try {
        const body = {
            required_discharge: q,
            water_level: waterLevel,
            pitch: pitch
        };

        const response = await fetch('/api/hydraulics/gate_rotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to calculate rotations');
        }

        if (rotationsValueEl) {
            rotationsValueEl.textContent = data.rotations != null ? data.rotations.toFixed(3) : '--';
        }

        const kpiRotations = document.getElementById('kpiRotations');
        const kpiRotationsStatus = document.getElementById('kpiRotationsStatus');
        if (kpiRotations) {
            kpiRotations.textContent = data.rotations != null ? data.rotations.toFixed(3) : '--';
        }
        if (kpiRotationsStatus) {
            kpiRotationsStatus.textContent = data.message || 'For target discharge Q';
        }

        if (rotationsMsgEl) {
            rotationsMsgEl.textContent = data.message || '';
            rotationsMsgEl.style.color = data.valid ? '#00aa66' : '#dd3333';
        }

        // Pre‑fill N for open‑time calculator
        const nInput = document.getElementById('gateRotationsForTime');
        if (nInput && data.rotations != null) {
            nInput.value = data.rotations.toFixed(3);
        }

        // Also mirror water level / pitch into right‑hand inputs if empty
        const hTimeInput = document.getElementById('gateWaterLevelTime');
        if (hTimeInput && !hTimeInput.value) {
            hTimeInput.value = waterLevel.toFixed(3);
        }
        const pTimeInput = document.getElementById('gatePitchTime');
        if (pTimeInput && !pTimeInput.value) {
            pTimeInput.value = pitch.toFixed(3);
        }
    } catch (error) {
        console.error('Error calculating gate rotations:', error);
        if (rotationsMsgEl) {
            rotationsMsgEl.textContent = 'Error: ' + error.message;
            rotationsMsgEl.style.color = '#dd3333';
        }
    }
}

async function handleCalcGateOpenTime() {
    const volumeInput = document.getElementById('gateTargetVolume');
    const rotationsInput = document.getElementById('gateRotationsForTime');
    const timeValueEl = document.getElementById('gateOpenTimeValue');
    const timeMsgEl = document.getElementById('gateOpenTimeMessage');

    const V = volumeInput ? parseFloat(volumeInput.value) : NaN;
    if (isNaN(V) || V < 0) {
        alert('Enter a valid non‑negative volume V (m³).');
        return;
    }

    let N = rotationsInput ? parseFloat(rotationsInput.value) : NaN;
    if (isNaN(N) || N <= 0) {
        // Try to use last calculated N shown on the left
        const shownN = document.getElementById('gateRotationsValue')?.textContent || '';
        const parsedShown = parseFloat(shownN);
        if (!isNaN(parsedShown) && parsedShown > 0) {
            N = parsedShown;
        } else {
            alert('Rotations N is required. Calculate N first or enter manually.');
            return;
        }
    }

    const waterLevel = getWaterLevelForGateInput('gateWaterLevelTime');
    if (waterLevel === null) {
        alert('Water level H is required. Use OCR reading or enter manually.');
        return;
    }

    const pitch = getPitchForGateInput('gatePitchTime');

    try {
        const body = {
            required_volume: V,
            rotations: N,
            water_level: waterLevel,
            pitch: pitch
        };

        const response = await fetch('/api/hydraulics/gate_open_time', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to calculate open time');
        }

        if (timeValueEl) {
            timeValueEl.textContent = data.open_time != null ? data.open_time.toFixed(1) : '--';
        }

        const kpiOpenTime = document.getElementById('kpiOpenTime');
        const kpiOpenTimeStatus = document.getElementById('kpiOpenTimeStatus');
        if (kpiOpenTime) {
            kpiOpenTime.textContent = data.open_time != null ? data.open_time.toFixed(1) : '--';
        }
        if (kpiOpenTimeStatus) {
            const seconds = data.open_time || 0;
            const prettyTime = seconds >= 60
                ? `${Math.floor(seconds / 60)} min ${(seconds % 60).toFixed(0)} s`
                : `${seconds.toFixed(1)} s`;
            kpiOpenTimeStatus.textContent = (data.message || 'OK') + (data.open_time != null ? ` (${prettyTime})` : '');
        }

        if (timeMsgEl) {
            const seconds = data.open_time || 0;
            const minutes = Math.floor(seconds / 60);
            const remSeconds = seconds % 60;
            const prettyTime = minutes > 0
                ? `${minutes} min ${remSeconds.toFixed(0)} s`
                : `${seconds.toFixed(1)} s`;

            const dischargeText = data.discharge != null ? `Q ≈ ${data.discharge.toFixed(3)} m³/s.` : '';
            timeMsgEl.textContent = (data.message || 'OK') + `  Gate open time ≈ ${prettyTime}. ${dischargeText}`;
            timeMsgEl.style.color = data.valid ? '#00aa66' : '#dd3333';
        }
    } catch (error) {
        console.error('Error calculating gate open time:', error);
        if (timeMsgEl) {
            timeMsgEl.textContent = 'Error: ' + error.message;
            timeMsgEl.style.color = '#dd3333';
        }
    }
}

// -------- Dam water level animation video --------

function updateWaterLevelAnimation(extraData = null) {
    const percentSpan = document.getElementById('waterLevelPercent');
    const videoEl = document.getElementById('waterLevelAnimation');
    const aiFillEl = document.getElementById('aiWaterFill');
    const aiLevelLabel = document.getElementById('aiWaterLevelLabel');
    const aiStatusLabel = document.getElementById('aiWaterStatusLabel');
    const safeLabel = document.getElementById('safeThresholdLabel');
    const excessPercentLabel = document.getElementById('excessPercentLabel');
    const excessVolumeLabel = document.getElementById('excessVolumeLabel');

    if (!percentSpan && !videoEl && !aiFillEl) return;

    let pct = null;
    if (extraData && typeof extraData.percentage === 'number') {
        pct = extraData.percentage;
        lastWaterLevelPercent = pct;
    } else if (lastWaterLevelPercent !== null) {
        pct = lastWaterLevelPercent;
    }

    if (pct === null) return;

    // Update percentage metric on dashboard
    if (percentSpan) {
        percentSpan.textContent = pct.toFixed(1);
    }

    // Compute excess storage relative to safe threshold and capacity
    const clamped = Math.max(0, Math.min(100, pct));
    const excessPercent = Math.max(0, clamped - SAFE_STORAGE_PERCENT);
    const excessVolumeM3 = (excessPercent / 100.0) * RESERVOIR_CAPACITY_M3;
    lastExcessPercent = excessPercent;
    lastExcessVolumeM3 = excessVolumeM3;

    // Auto-fill gate operation volume (V_excess) when positive
    if (excessVolumeM3 > 0) {
        const gateVolumeInput = document.getElementById('gateTargetVolume');
        if (gateVolumeInput) {
            gateVolumeInput.value = excessVolumeM3.toFixed(0);
        }
    }

    // Update AI-based dam fill and labels
    if (aiFillEl || aiLevelLabel || aiStatusLabel || safeLabel || excessPercentLabel || excessVolumeLabel) {

        if (aiFillEl) {
            aiFillEl.style.height = clamped + '%';

            // Color based on status if available
            let color = '#00aa66'; // normal
            if (extraData && extraData.status) {
                switch (extraData.status) {
                    case 'critical':
                        color = '#dd3333';
                        break;
                    case 'warning':
                        color = '#ff9933';
                        break;
                    case 'low':
                        color = '#0066cc';
                        break;
                    default:
                        color = '#00aa66';
                }
            }
            aiFillEl.style.background = `linear-gradient(to top, ${color}, rgba(0,0,0,0.2))`;
        }

        if (aiLevelLabel) {
            aiLevelLabel.textContent = clamped.toFixed(1) + ' %';
        }

        if (safeLabel) {
            safeLabel.textContent = SAFE_STORAGE_PERCENT.toFixed(0) + ' %';
        }

        if (excessPercentLabel) {
            excessPercentLabel.textContent = excessPercent.toFixed(1) + ' %';
        }

        if (excessVolumeLabel) {
            excessVolumeLabel.textContent = excessVolumeM3.toFixed(0) + ' m³';
        }

        if (aiStatusLabel) {
            if (extraData && extraData.status_message) {
                // Append automation hint if we have excess
                if (excessPercent > 0 && excessVolumeM3 > 0) {
                    aiStatusLabel.textContent = `${extraData.status_message} | Exceeded by ${excessPercent.toFixed(1)}%. Discharge ~${excessVolumeM3.toFixed(0)} m³.`;
                } else {
                    aiStatusLabel.textContent = extraData.status_message;
                }
            } else {
                if (excessPercent > 0 && excessVolumeM3 > 0) {
                    aiStatusLabel.textContent = `Level exceeded safe ${SAFE_STORAGE_PERCENT.toFixed(0)}% by ${excessPercent.toFixed(1)}%. Discharge ~${excessVolumeM3.toFixed(0)} m³.`;
                } else {
                    aiStatusLabel.textContent = 'Live level visual based on OCR measurements.';
                }
            }
        }
    }

    // Map percentage (0–100%) to video timeline (0–duration)
    if (videoEl && !isNaN(videoEl.duration) && videoEl.duration > 0) {
        const clamped = Math.max(0, Math.min(100, pct));
        const targetTime = (clamped / 100) * videoEl.duration;
        try {
            videoEl.currentTime = targetTime;
        } catch (e) {
            // Ignore seek errors (e.g., if metadata not ready yet)
        }
    } else if (videoEl) {
        // If metadata not loaded yet, update after it loads
        videoEl.addEventListener(
            'loadedmetadata',
            () => {
                if (lastWaterLevelPercent !== null && !isNaN(videoEl.duration) && videoEl.duration > 0) {
                    const clamped = Math.max(0, Math.min(100, lastWaterLevelPercent));
                    videoEl.currentTime = (clamped / 100) * videoEl.duration;
                }
            },
            { once: true }
        );
    }
}

// Hook into water level updates
const originalUpdateOcrReading = updateOcrReading;
updateOcrReading = function(value, timestamp, extraData = null) {
    originalUpdateOcrReading(value, timestamp, extraData);
    
    // Track water levels for inflow calculation
    if (value !== null && value !== undefined) {
        previousWaterLevel = lastWaterLevel;
        lastWaterLevel = value;
        lastLevelUpdateTime = Date.now();
        
        // Update hydraulics display
        updateHydraulicsDisplay(value);
    }

    // Update dam water level animation and dashboard percentage metric
    updateWaterLevelAnimation(extraData);
};

// Add to initialization
const originalInitializeApp = initializeApp;
initializeApp = function() {
    originalInitializeApp();
    setupSettingsListeners();
    setupHydraulicsListeners();
    setupHistoryListeners();
    loadInitialSettings();
};

document.addEventListener('DOMContentLoaded', initializeApp);
