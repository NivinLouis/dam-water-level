"""
Dam Water Level Monitoring Server
Receives ESP-CAM stream, processes seven-segment display OCR, and serves dashboard.
"""

import os
import time
import threading
import base64
from datetime import datetime
from flask import Flask, render_template, Response, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
import cv2
import numpy as np

from ocr_processor import (
    SevenSegmentOCR, 
    read_water_level_from_frame, 
    reset_ocr_bounds
)
from ocr_config import (
    get_config, update_config, OCR_CONFIG,
    get_dam_config, update_dam_config, calculate_water_level, DAM_CONFIG,
    get_hydraulics_config, update_hydraulics_config, HYDRAULICS_CONFIG,
    calculate_spillway_discharge, calculate_outlet_discharge,
    calculate_total_discharge, calculate_inflow, calculate_all_hydraulics,
    calculate_gate_rotations, calculate_gate_open_time
)
from config_manager import (
    load_config as load_config_file, 
    save_config as save_config_file,
    update_config_section,
    get_config_section,
    reset_to_defaults,
    apply_config_to_modules
)
from history_logger import (
    add_reading as log_reading,
    get_history_filtered,
    export_to_csv,
    export_to_json,
    get_history_stats,
    clear_history,
    save_history
)

# Initialize Flask app
app = Flask(__name__, static_folder='.', template_folder='.')
app.config['SECRET_KEY'] = 'dam-monitoring-secret-key'

# Initialize SocketIO with threading (more compatible on Windows)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
class CameraState:
    def __init__(self):
        self.frame = None
        self.last_reading = None
        self.last_reading_time = None
        self.is_connected = False
        self.esp_cam_url = "http://10.188.122.133:81/stream"
        self.ocr = SevenSegmentOCR(debug=False)
        self.lock = threading.Lock()
        self.reading_history = []  # Store last 100 readings
        
camera_state = CameraState()


# ==================== Routes ====================

@app.route('/')
def index():
    """Serve the main dashboard."""
    return send_from_directory('.', 'index.html')


@app.route('/styles.css')
def styles():
    """Serve CSS file."""
    return send_from_directory('.', 'styles.css')


@app.route('/app.js')
def app_js():
    """Serve JavaScript file."""
    return send_from_directory('.', 'app.js')


@app.route('/water_level_animation.mp4')
def water_level_animation():
    """Serve dam water level animation video."""
    return send_from_directory('.', 'water_level_animation.mp4')


@app.route('/api/status')
def get_status():
    """Get current system status including water level calculation."""
    with camera_state.lock:
        last_reading = camera_state.last_reading
        last_time = camera_state.last_reading_time
        connected = camera_state.is_connected
        esp_url = camera_state.esp_cam_url
    
    result = {
        'connected': connected,
        'last_distance_reading': last_reading,
        'last_reading_time': last_time,
        'esp_cam_url': esp_url,
        'dam_name': DAM_CONFIG.get('dam_name', 'Dam Monitor')
    }
    
    # Add water level calculation if we have a reading
    if last_reading is not None:
        water_level_data = calculate_water_level(last_reading)
        result.update({
            'water_level': water_level_data['water_level'],
            'percentage': water_level_data['percentage'],
            'status': water_level_data['status'],
            'status_message': water_level_data['status_message'],
            'unit': water_level_data['unit']
        })
    
    return jsonify(result)


@app.route('/api/test_ocr', methods=['POST'])
def test_ocr():
    """
    Test OCR with the static test image.
    Returns the detected reading and annotated image.
    """
    test_image_path = os.path.join(os.path.dirname(__file__), 'static_test_image.png')
    
    if not os.path.exists(test_image_path):
        return jsonify({'error': 'Test image not found'}), 404
    
    # Load and process image
    image = cv2.imread(test_image_path)
    if image is None:
        return jsonify({'error': 'Could not load test image'}), 500
    
    # Process with OCR
    value, annotated = read_water_level_from_frame(image, debug=False)
    
    # Encode annotated image to base64
    _, buffer = cv2.imencode('.jpg', annotated)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({
        'success': value is not None,
        'reading': value,
        'reading_unit': 'm',
        'annotated_image': f'data:image/jpeg;base64,{img_base64}',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/test_ocr_path', methods=['POST'])
def test_ocr_path():
    """
    Test OCR with an image at a specified path.
    """
    data = request.get_json()
    image_path = data.get('path')
    
    if not image_path:
        return jsonify({'error': 'Image path is required'}), 400
    
    if not os.path.exists(image_path):
        return jsonify({'error': f'Image not found: {image_path}'}), 404
    
    # Load and process image
    image = cv2.imread(image_path)
    if image is None:
        return jsonify({'error': f'Could not load image: {image_path}'}), 500
    
    # Reset cached bounds for fresh image analysis
    reset_ocr_bounds()
    
    # Process with OCR
    value, annotated = read_water_level_from_frame(image, debug=False)
    
    # Encode annotated image to base64
    _, buffer = cv2.imencode('.jpg', annotated)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({
        'success': value is not None,
        'reading': value,
        'reading_unit': 'm',
        'image_path': image_path,
        'annotated_image': f'data:image/jpeg;base64,{img_base64}',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/test_ocr_upload', methods=['POST'])
def test_ocr_upload():
    """
    Test OCR with an uploaded image.
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    
    # Read image from upload
    file_bytes = np.frombuffer(file.read(), np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    
    if image is None:
        return jsonify({'error': 'Could not decode image'}), 400
    
    # Reset cached bounds for fresh image analysis
    reset_ocr_bounds()
    
    # Process with OCR
    value, annotated = read_water_level_from_frame(image, debug=False)
    
    # Encode annotated image to base64
    _, buffer = cv2.imencode('.jpg', annotated)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({
        'success': value is not None,
        'reading': value,
        'reading_unit': 'm',
        'annotated_image': f'data:image/jpeg;base64,{img_base64}',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/set_espcam_url', methods=['POST'])
def set_espcam_url():
    """Set the ESP-CAM stream URL."""
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    with camera_state.lock:
        camera_state.esp_cam_url = url
    
    # Start stream processing in background
    socketio.start_background_task(process_esp_cam_stream, url)
    
    return jsonify({'success': True, 'url': url})


@app.route('/api/readings')
def get_readings():
    """Get recent reading history."""
    with camera_state.lock:
        return jsonify({
            'readings': camera_state.reading_history[-100:]
        })


@app.route('/api/ocr_config', methods=['GET'])
def get_ocr_config():
    """Get current OCR configuration."""
    return jsonify(get_config())


@app.route('/api/ocr_config', methods=['POST'])
def set_ocr_config():
    """Update OCR configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No configuration provided'}), 400
    
    update_config(data)
    return jsonify({'success': True, 'config': get_config()})


@app.route('/api/ocr_config/digit_bounds', methods=['POST'])
def set_digit_bounds():
    """
    Set manual digit bounds for OCR.
    Expected format: {"bounds": [[x1_start, x1_end], [x2_start, x2_end], ...]}
    """
    data = request.get_json()
    bounds = data.get('bounds')
    
    if bounds is None:
        # Clear manual bounds, use auto-detection
        update_config({'manual_digit_bounds': None})
        reset_ocr_bounds()  # Reset cached bounds when switching to auto
        return jsonify({'success': True, 'message': 'Manual bounds cleared, using auto-detection'})
    
    if not isinstance(bounds, list):
        return jsonify({'error': 'Bounds must be a list of [x_start, x_end] pairs'}), 400
    
    update_config({'manual_digit_bounds': bounds})
    reset_ocr_bounds()  # Reset cached bounds when setting manual bounds
    return jsonify({'success': True, 'bounds': bounds})


@app.route('/api/ocr_config/reset_bounds', methods=['POST'])
def reset_bounds():
    """
    Reset cached OCR digit boundaries.
    Call this when switching to a new image/stream or if detection seems stuck.
    """
    reset_ocr_bounds()
    return jsonify({'success': True, 'message': 'OCR boundary cache cleared'})


# ==================== Dam Configuration API ====================

@app.route('/api/dam/config', methods=['GET'])
def get_dam_configuration():
    """Get current dam configuration."""
    return jsonify(get_dam_config())


@app.route('/api/dam/config', methods=['POST'])
def set_dam_configuration():
    """
    Update dam configuration.
    Expected format: {
        "device_height": 120.0,
        "min_water_level": 0.0,
        "max_water_level": 120.0,
        "warning_threshold_percent": 80.0,
        "critical_threshold_percent": 90.0,
        "low_water_threshold_percent": 20.0,
        "dam_name": "My Dam",
        "location": "Location description",
        "unit": "m"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No configuration provided'}), 400
    
    # Validate numeric fields
    numeric_fields = [
        'device_height', 'min_water_level', 'max_water_level',
        'warning_threshold_percent', 'critical_threshold_percent', 
        'low_water_threshold_percent'
    ]
    
    for field in numeric_fields:
        if field in data:
            try:
                data[field] = float(data[field])
            except (ValueError, TypeError):
                return jsonify({'error': f'Invalid value for {field}'}), 400
    
    update_dam_config(data)
    return jsonify({'success': True, 'config': get_dam_config()})


@app.route('/api/dam/water_level', methods=['GET'])
def get_current_water_level():
    """
    Get current water level calculation based on last reading.
    Returns the calculated water level, percentage, and status.
    """
    with camera_state.lock:
        last_reading = camera_state.last_reading
        last_time = camera_state.last_reading_time
    
    if last_reading is None:
        return jsonify({
            'error': 'No reading available',
            'has_reading': False
        })
    
    # Calculate water level from distance reading
    result = calculate_water_level(last_reading)
    result['timestamp'] = last_time
    result['has_reading'] = True
    
    return jsonify(result)


@app.route('/api/dam/calculate', methods=['POST'])
def calculate_water_level_api():
    """
    Calculate water level from a given distance reading.
    Expected format: {"distance": 3.5}
    """
    data = request.get_json()
    distance = data.get('distance')
    
    if distance is None:
        return jsonify({'error': 'Distance value is required'}), 400
    
    try:
        distance = float(distance)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid distance value'}), 400
    
    result = calculate_water_level(distance)
    return jsonify(result)


# ==================== Hydraulics API ====================

@app.route('/api/hydraulics/config', methods=['GET'])
def get_hydraulics_configuration():
    """Get current hydraulics configuration."""
    return jsonify(get_hydraulics_config())


@app.route('/api/hydraulics/config', methods=['POST'])
def set_hydraulics_configuration():
    """Update hydraulics configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No configuration provided'}), 400
    
    update_hydraulics_config(data)
    update_config_section('hydraulics', data)
    
    return jsonify({'success': True, 'config': get_hydraulics_config()})


@app.route('/api/hydraulics/spillway', methods=['GET'])
def get_spillway_discharge():
    """Calculate spillway discharge for current water level."""
    water_level = request.args.get('water_level', type=float)
    
    if water_level is None:
        # Use last reading if available
        with camera_state.lock:
            if camera_state.last_reading is not None:
                water_level_data = calculate_water_level(camera_state.last_reading)
                water_level = water_level_data['water_level']
            else:
                return jsonify({'error': 'No water level available'}), 400
    
    result = calculate_spillway_discharge(water_level)
    result['water_level'] = water_level
    return jsonify(result)


@app.route('/api/hydraulics/outlet', methods=['GET'])
def get_outlet_discharge():
    """Calculate outlet discharge for current water level."""
    water_level = request.args.get('water_level', type=float)
    
    if water_level is None:
        with camera_state.lock:
            if camera_state.last_reading is not None:
                water_level_data = calculate_water_level(camera_state.last_reading)
                water_level = water_level_data['water_level']
            else:
                return jsonify({'error': 'No water level available'}), 400
    
    result = calculate_outlet_discharge(water_level)
    result['water_level'] = water_level
    return jsonify(result)


@app.route('/api/hydraulics/discharge', methods=['GET'])
def get_total_discharge():
    """Calculate total discharge (spillway + outlet)."""
    water_level = request.args.get('water_level', type=float)
    
    if water_level is None:
        with camera_state.lock:
            if camera_state.last_reading is not None:
                water_level_data = calculate_water_level(camera_state.last_reading)
                water_level = water_level_data['water_level']
            else:
                return jsonify({'error': 'No water level available'}), 400
    
    result = calculate_total_discharge(water_level)
    result['water_level'] = water_level
    return jsonify(result)


@app.route('/api/hydraulics/inflow', methods=['POST'])
def calculate_inflow_api():
    """
    Calculate inflow from water level change.
    Expected format: {
        "current_level": 5.5,
        "previous_level": 5.4,
        "time_interval": 60,
        "outflow": 10.5  // optional
    }
    """
    data = request.get_json()
    
    current_level = data.get('current_level')
    previous_level = data.get('previous_level')
    time_interval = data.get('time_interval', 60.0)
    outflow = data.get('outflow')  # Optional
    
    if current_level is None or previous_level is None:
        return jsonify({'error': 'current_level and previous_level are required'}), 400
    
    result = calculate_inflow(current_level, previous_level, time_interval, outflow)
    return jsonify(result)


@app.route('/api/hydraulics/all', methods=['GET'])
def get_all_hydraulics():
    """Get all hydraulic calculations for current water level."""
    water_level = request.args.get('water_level', type=float)
    previous_level = request.args.get('previous_level', type=float)
    time_interval = request.args.get('time_interval', 60.0, type=float)
    
    if water_level is None:
        with camera_state.lock:
            if camera_state.last_reading is not None:
                water_level_data = calculate_water_level(camera_state.last_reading)
                water_level = water_level_data['water_level']
            else:
                return jsonify({'error': 'No water level available'}), 400
    
    result = calculate_all_hydraulics(water_level, previous_level, time_interval)
    return jsonify(result)


@app.route('/api/hydraulics/gate', methods=['POST'])
def set_gate_opening():
    """
    Set spillway gate opening.
    Expected format: {"gate_opening": 1.5}
    """
    data = request.get_json()
    gate_opening = data.get('gate_opening')
    
    if gate_opening is None:
        return jsonify({'error': 'gate_opening is required'}), 400
    
    try:
        gate_opening = float(gate_opening)
        if gate_opening < 0:
            return jsonify({'error': 'gate_opening must be non-negative'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid gate_opening value'}), 400
    
    update_hydraulics_config({'gate_opening': gate_opening})
    update_config_section('hydraulics', {'gate_opening': gate_opening})
    
    return jsonify({
        'success': True,
        'gate_opening': gate_opening,
        'message': f'Gate opening set to {gate_opening}m'
    })


@app.route('/api/hydraulics/gate_rotations', methods=['POST'])
def get_gate_rotations():
    """
    Calculate required number of full hand‑wheel rotations to achieve a target
    discharge through the sluice/spillway gate.
    
    Expected format:
    {
        "required_discharge": 0.5,   # m³/s
        "water_level": 5.5,          # m
        "pitch": 0.02                # optional, m per rotation
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_discharge = data.get('required_discharge')
    water_level = data.get('water_level')
    pitch = data.get('pitch')
    
    if required_discharge is None or water_level is None:
        return jsonify({'error': 'required_discharge and water_level are required'}), 400
    
    try:
        required_discharge = float(required_discharge)
        water_level = float(water_level)
        if pitch is not None:
            pitch = float(pitch)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid numeric value in request'}), 400
    
    result = calculate_gate_rotations(
        required_discharge=required_discharge,
        water_level=water_level,
        pitch=pitch
    )
    
    return jsonify(result)


@app.route('/api/hydraulics/gate_open_time', methods=['POST'])
def get_gate_open_time():
    """
    Calculate how long the gate should remain open to pass a target volume
    of water, given a chosen number of full rotations.
    
    Expected format:
    {
        "required_volume": 100.0,  # m³
        "rotations": 10.0,         # N
        "water_level": 5.5,        # m
        "pitch": 0.02              # optional, m per rotation
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_volume = data.get('required_volume')
    rotations = data.get('rotations')
    water_level = data.get('water_level')
    pitch = data.get('pitch')
    
    if required_volume is None or rotations is None or water_level is None:
        return jsonify({
            'error': 'required_volume, rotations, and water_level are required'
        }), 400
    
    try:
        required_volume = float(required_volume)
        rotations = float(rotations)
        water_level = float(water_level)
        if pitch is not None:
            pitch = float(pitch)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid numeric value in request'}), 400
    
    result = calculate_gate_open_time(
        required_volume=required_volume,
        rotations=rotations,
        water_level=water_level,
        pitch=pitch
    )
    
    return jsonify(result)


@app.route('/api/config/all', methods=['GET'])
def get_all_configuration():
    """Get all configuration settings (OCR, Dam)."""
    return jsonify({
        'ocr': get_config(),
        'dam': get_dam_config()
    })


@app.route('/api/config/file', methods=['GET'])
def get_config_from_file():
    """Get all configuration from the config file."""
    config = load_config_file()
    return jsonify(config)


@app.route('/api/config/file', methods=['POST'])
def save_config_to_file():
    """Save configuration to file and apply to modules."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No configuration provided'}), 400
    
    # Update each section if provided
    if 'dam' in data:
        update_config_section('dam', data['dam'])
        update_dam_config(data['dam'])
    
    if 'ocr' in data:
        update_config_section('ocr', data['ocr'])
        update_config(data['ocr'])
    
    if 'hydraulics' in data:
        update_config_section('hydraulics', data['hydraulics'])
        update_hydraulics_config(data['hydraulics'])
    
    if 'esp_cam' in data:
        update_config_section('esp_cam', data['esp_cam'])
    
    return jsonify({'success': True, 'config': load_config_file()})


@app.route('/api/config/reset', methods=['POST'])
def reset_config_to_defaults():
    """Reset all configuration to defaults."""
    config = reset_to_defaults()
    
    # Apply defaults to modules
    if 'dam' in config:
        update_dam_config(config['dam'])
    if 'ocr' in config:
        update_config(config['ocr'])
    
    return jsonify({'success': True, 'config': config})


# ==================== History API ====================

@app.route('/api/history', methods=['GET'])
def get_history():
    """
    Get reading history with optional date filters.
    Query params:
        start_date: YYYY-MM-DD or ISO datetime
        end_date: YYYY-MM-DD or ISO datetime
        limit: Maximum number of entries
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    limit = request.args.get('limit', type=int)
    
    history = get_history_filtered(start_date, end_date, limit)
    return jsonify({
        'entries': history,
        'count': len(history),
        'filters': {
            'start_date': start_date,
            'end_date': end_date,
            'limit': limit
        }
    })


@app.route('/api/history/stats', methods=['GET'])
def get_history_statistics():
    """Get history statistics."""
    stats = get_history_stats()
    return jsonify(stats)


@app.route('/api/history/export/csv', methods=['GET'])
def export_history_csv():
    """
    Export history to CSV file.
    Query params:
        start_date: YYYY-MM-DD or ISO datetime
        end_date: YYYY-MM-DD or ISO datetime
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    csv_content = export_to_csv(start_date, end_date)
    
    # Generate filename with date range
    filename = 'reading_history'
    if start_date:
        filename += f'_from_{start_date}'
    if end_date:
        filename += f'_to_{end_date}'
    filename += '.csv'
    
    response = Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
    return response


@app.route('/api/history/export/json', methods=['GET'])
def export_history_json():
    """
    Export history to JSON file.
    Query params:
        start_date: YYYY-MM-DD or ISO datetime
        end_date: YYYY-MM-DD or ISO datetime
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    json_content = export_to_json(start_date, end_date)
    
    # Generate filename with date range
    filename = 'reading_history'
    if start_date:
        filename += f'_from_{start_date}'
    if end_date:
        filename += f'_to_{end_date}'
    filename += '.json'
    
    response = Response(
        json_content,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
    return response


@app.route('/api/history/clear', methods=['POST'])
def clear_history_api():
    """Clear all reading history."""
    if clear_history():
        return jsonify({'success': True, 'message': 'History cleared'})
    else:
        return jsonify({'error': 'Failed to clear history'}), 500


@app.route('/api/history/save', methods=['POST'])
def save_history_api():
    """Force save history to file."""
    if save_history():
        return jsonify({'success': True, 'message': 'History saved'})
    else:
        return jsonify({'error': 'Failed to save history'}), 500


@app.route('/video_feed')
def video_feed():
    """
    Video streaming route for displaying the camera feed with OCR overlay.
    """
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


# ==================== ESP-CAM Stream Processing ====================

def process_esp_cam_stream(url: str):
    """
    Background task to process ESP-CAM MJPEG stream.
    Runs OCR on each frame and emits readings via WebSocket.
    """
    print(f"Connecting to ESP-CAM at: {url}")
    
    cap = cv2.VideoCapture(url)
    
    if not cap.isOpened():
        print(f"Failed to connect to ESP-CAM at {url}")
        with camera_state.lock:
            camera_state.is_connected = False
        socketio.emit('camera_status', {'connected': False, 'error': 'Failed to connect'})
        return
    
    with camera_state.lock:
        camera_state.is_connected = True
    
    socketio.emit('camera_status', {'connected': True})
    
    frame_count = 0
    ocr_interval_seconds = 5.0  # Take distance_reading every 5 seconds
    last_ocr_time = 0.0
    
    try:
        while True:
            ret, frame = cap.read()
            
            if not ret:
                print("Lost connection to ESP-CAM")
                break
            
            with camera_state.lock:
                camera_state.frame = frame.copy()
            
            # Run OCR periodically (every ~5 seconds)
            frame_count += 1
            now = time.time()
            if now - last_ocr_time >= ocr_interval_seconds:
                last_ocr_time = now
                value, annotated = read_water_level_from_frame(frame)
                
                if value is not None:
                    timestamp = datetime.now().isoformat()
                    
                    # Calculate actual water level from distance reading
                    water_level_data = calculate_water_level(value)
                    
                    # Create reading entry
                    reading_entry = {
                        'distance': value,
                        'water_level': water_level_data['water_level'],
                        'percentage': water_level_data['percentage'],
                        'status': water_level_data['status'],
                        'unit': water_level_data['unit'],
                        'timestamp': timestamp
                    }
                    
                    with camera_state.lock:
                        camera_state.last_reading = value
                        camera_state.last_reading_time = timestamp
                        camera_state.frame = annotated
                        
                        camera_state.reading_history.append(reading_entry)
                        
                        # Keep only last 100 readings in memory
                        if len(camera_state.reading_history) > 100:
                            camera_state.reading_history = camera_state.reading_history[-100:]
                    
                    # Log to persistent history
                    log_reading(reading_entry)
                    
                    # Emit reading to all connected clients with water level calculation
                    socketio.emit('new_reading', {
                        'distance': value,
                        'water_level': water_level_data['water_level'],
                        'percentage': water_level_data['percentage'],
                        'status': water_level_data['status'],
                        'status_message': water_level_data['status_message'],
                        'unit': water_level_data['unit'],
                        'timestamp': timestamp
                    })
            
            # Small delay to prevent overwhelming the system
            time.sleep(0.05)
    
    except Exception as e:
        print(f"Error processing stream: {e}")
    
    finally:
        cap.release()
        with camera_state.lock:
            camera_state.is_connected = False
        socketio.emit('camera_status', {'connected': False})


def generate_frames():
    """
    Generator function for video streaming.
    Yields MJPEG frames from the camera with OCR overlay.
    """
    while True:
        with camera_state.lock:
            frame = camera_state.frame
        
        if frame is not None:
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        time.sleep(0.033)  # ~30 fps


# ==================== WebSocket Events ====================

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print('Client connected')
    
    # Send current status
    with camera_state.lock:
        emit('camera_status', {
            'connected': camera_state.is_connected,
            'last_reading': camera_state.last_reading,
            'last_reading_time': camera_state.last_reading_time
        })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print('Client disconnected')


@socketio.on('request_test_ocr')
def handle_test_ocr():
    """Handle test OCR request via WebSocket."""
    test_image_path = os.path.join(os.path.dirname(__file__), 'static_test_image.png')
    
    if not os.path.exists(test_image_path):
        emit('ocr_result', {'error': 'Test image not found'})
        return
    
    image = cv2.imread(test_image_path)
    if image is None:
        emit('ocr_result', {'error': 'Could not load test image'})
        return
    
    value, annotated = read_water_level_from_frame(image)
    
    # Encode annotated image
    _, buffer = cv2.imencode('.jpg', annotated)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
    
    emit('ocr_result', {
        'success': value is not None,
        'reading': value,
        'unit': 'm',
        'annotated_image': f'data:image/jpeg;base64,{img_base64}',
        'timestamp': datetime.now().isoformat()
    })


@socketio.on('start_stream')
def handle_start_stream(data):
    """Start processing ESP-CAM stream."""
    url = data.get('url')
    if url:
        socketio.start_background_task(process_esp_cam_stream, url)
        emit('stream_started', {'url': url})


# ==================== Main ====================

if __name__ == '__main__':
    print("=" * 50)
    print("Dam Water Level Monitoring Server")
    print("=" * 50)
    print("\nEndpoints:")
    print("  Dashboard:     http://localhost:5000/")
    print("  Video Feed:    http://localhost:5000/video_feed")
    print("  Test OCR:      POST http://localhost:5000/api/test_ocr")
    print("  Status:        GET http://localhost:5000/api/status")
    print("\nWebSocket Events:")
    print("  - new_reading: Emitted when OCR detects a new value")
    print("  - camera_status: Camera connection status updates")
    print("=" * 50)
    
    # Note: debug=False to prevent reloader from starting duplicate processes
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
