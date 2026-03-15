"""
OCR and Dam Configuration for Water Level Monitoring
Adjust these values to match your specific setup.
"""

# Display value range: 0.000m to 250.000m
# Format can be X.XXX, XX.XXX, or XXX.XXX depending on value

# Dam/Installation Configuration
DAM_CONFIG = {
    # Device mounting height (in meters)
    # This is the height at which the laser meter is fixed above the dam bottom
    "device_height": 120.0,
    
    # Minimum water level (dam bottom reference, usually 0)
    "min_water_level": 0.0,
    
    # Maximum water level (full capacity)
    "max_water_level": 120.0,
    
    # Warning threshold (percentage of max capacity)
    "warning_threshold_percent": 80.0,
    
    # Critical threshold (percentage of max capacity)  
    "critical_threshold_percent": 90.0,
    
    # Low water warning threshold (percentage of max capacity)
    "low_water_threshold_percent": 20.0,
    
    # Dam name/identifier
    "dam_name": "Dam Water Level Monitor",
    
    # Location description
    "location": "",
    
    # Unit of measurement
    "unit": "m",
}

OCR_CONFIG = {
    # Region of Interest (ROI) - where the current reading is located
    # These are percentages of the LCD display area
    # Adjust these if the reading is in a different position
    "roi": {
        "x_start_pct": 0.28,   # Start X as percentage of LCD width
        "x_end_pct": 0.78,     # End X as percentage of LCD width  
        "y_start_pct": 0.78,   # Start Y as percentage of LCD height (adjusted to avoid row above)
        "y_end_pct": 0.98,     # End Y as percentage of LCD height
    },
    
    # Expected number format
    # For 0.000 to 250.000, we can have 1-3 digits before decimal, 3 after
    "decimal_position": 1,  # Position of decimal point from left (0-indexed)
                           # Set to -1 for auto-detection
                           # For "X.XXX" format, decimal is at position 1
                           # For "XXX.XXX" format, decimal is at position 3
    
    "expected_digits_before_decimal": None,  # None = auto, or 1, 2, 3
    "expected_digits_after_decimal": 3,      # Usually fixed at 3
    
    # Manual digit bounds (optional)
    # If you know the exact pixel positions of each digit within the ROI,
    # specify them here. Set to None for auto-detection.
    # Format: [(x_start, x_end), (x_start, x_end), ...]
    # These are pixel positions within the extracted ROI
    "manual_digit_bounds": None,  
    
    # Example for 4-digit display (X.XXX):
    # "manual_digit_bounds": [(10, 40), (45, 75), (80, 110), (115, 145)],
    
    # Segment detection thresholds
    "void_threshold": 0.25,  # Threshold for center void detection (0 vs 8)
    "edge_threshold": 0.25,  # Threshold for edge fill detection
    
    # Preprocessing settings
    "adaptive_threshold_block_size": 25,
    "adaptive_threshold_c": 10,
}


def get_config():
    """Return the current OCR configuration."""
    return OCR_CONFIG.copy()


def update_config(new_config: dict):
    """Update OCR configuration with new values."""
    global OCR_CONFIG
    OCR_CONFIG.update(new_config)


def get_dam_config():
    """Return the current dam configuration."""
    return DAM_CONFIG.copy()


def update_dam_config(new_config: dict):
    """Update dam configuration with new values."""
    global DAM_CONFIG
    DAM_CONFIG.update(new_config)


def calculate_water_level(distance_reading: float) -> dict:
    """
    Calculate actual water level from laser meter distance reading.
    
    The laser meter measures the distance from the device to the water surface.
    Water level = Device height - Distance reading
    
    Args:
        distance_reading: The distance measured by the laser meter (in meters)
        
    Returns:
        Dictionary with calculated values and status
    """
    device_height = DAM_CONFIG["device_height"]
    min_level = DAM_CONFIG["min_water_level"]
    max_level = DAM_CONFIG["max_water_level"]
    
    # Calculate actual water level
    water_level = device_height - distance_reading
    
    # Clamp to valid range
    water_level = max(min_level, min(water_level, max_level))
    
    # Calculate percentage of capacity
    capacity_range = max_level - min_level
    if capacity_range > 0:
        percentage = ((water_level - min_level) / capacity_range) * 100
    else:
        percentage = 0
    
    # Determine status based on thresholds
    warning_thresh = DAM_CONFIG["warning_threshold_percent"]
    critical_thresh = DAM_CONFIG["critical_threshold_percent"]
    low_thresh = DAM_CONFIG["low_water_threshold_percent"]
    
    if percentage >= critical_thresh:
        status = "critical"
        status_message = "CRITICAL: Water level very high!"
    elif percentage >= warning_thresh:
        status = "warning"
        status_message = "WARNING: Water level high"
    elif percentage <= low_thresh:
        status = "low"
        status_message = "LOW: Water level low"
    else:
        status = "normal"
        status_message = "Normal water level"
    
    return {
        "distance_reading": distance_reading,
        "water_level": round(water_level, 3),
        "percentage": round(percentage, 1),
        "status": status,
        "status_message": status_message,
        "device_height": device_height,
        "max_capacity": max_level,
        "unit": DAM_CONFIG["unit"]
    }


# ==================== Hydraulics Configuration ====================

HYDRAULICS_CONFIG = {
    # Reservoir parameters
    "reservoir_area": 1000.0,
    
    # Spillway parameters
    "spillway_crest_level": 8.0,
    "spillway_length": 10.0,
    "spillway_coefficient": 1.84,
    "num_spillway_gates": 3,
    "gate_width": 3.0,
    "gate_opening": 0.0,
    "gate_coefficient": 0.6,
    # Mechanical parameters for gate operation
    # Screw pitch: vertical lift per full hand‑wheel rotation (m/rotation)
    "gate_screw_pitch": 0.02,
    
    # Outlet parameters
    "outlet_area": 2.0,
    "outlet_coefficient": 0.62,
    "outlet_level": 2.0,
    
    # Manual values
    "manual_inflow": 0.0,
    "manual_outflow": 0.0,
    
    # Settings
    "use_calculated_discharge": True,
    "use_calculated_spillway": True,
    "gravity": 9.81
}


def get_hydraulics_config() -> dict:
    """Get current hydraulics configuration."""
    return HYDRAULICS_CONFIG.copy()


def update_hydraulics_config(new_config: dict):
    """Update hydraulics configuration."""
    HYDRAULICS_CONFIG.update(new_config)


def calculate_spillway_discharge(water_level: float) -> dict:
    """
    Calculate spillway discharge using weir formula.
    
    For free overflow: Q = C * L * H^(3/2)
    For gated flow: Q = C * A * sqrt(2 * g * H)
    
    Args:
        water_level: Current water level in meters
        
    Returns:
        Dictionary with spillway discharge details
    """
    crest_level = HYDRAULICS_CONFIG["spillway_crest_level"]
    spillway_length = HYDRAULICS_CONFIG["spillway_length"]
    coefficient = HYDRAULICS_CONFIG["spillway_coefficient"]
    num_gates = HYDRAULICS_CONFIG["num_spillway_gates"]
    gate_width = HYDRAULICS_CONFIG["gate_width"]
    gate_opening = HYDRAULICS_CONFIG["gate_opening"]
    gate_coeff = HYDRAULICS_CONFIG["gate_coefficient"]
    g = HYDRAULICS_CONFIG["gravity"]
    
    # Head over spillway crest
    head = max(0, water_level - crest_level)
    
    spillway_discharge = 0.0
    gate_discharge = 0.0
    discharge_type = "none"
    
    if head > 0:
        if gate_opening > 0:
            # Gated spillway discharge: Q = Cd * A * sqrt(2gh)
            # A = gate_width * gate_opening * num_gates
            effective_opening = min(gate_opening, head)  # Can't open more than head
            gate_area = gate_width * effective_opening * num_gates
            gate_discharge = gate_coeff * gate_area * (2 * g * head) ** 0.5
            discharge_type = "gated"
        
        # Free overflow spillway discharge: Q = C * L * H^(3/2)
        # This occurs over any uncontrolled portion or when water overtops gates
        free_overflow_head = max(0, head - gate_opening) if gate_opening > 0 else head
        if free_overflow_head > 0:
            spillway_discharge = coefficient * spillway_length * (free_overflow_head ** 1.5)
            if discharge_type == "gated":
                discharge_type = "combined"
            else:
                discharge_type = "free_overflow"
    
    total_discharge = spillway_discharge + gate_discharge
    
    return {
        "spillway_discharge": round(spillway_discharge, 3),
        "gate_discharge": round(gate_discharge, 3),
        "total_spillway_discharge": round(total_discharge, 3),
        "head_over_crest": round(head, 3),
        "discharge_type": discharge_type,
        "gate_opening": gate_opening,
        "unit": "m³/s"
    }


def calculate_outlet_discharge(water_level: float) -> dict:
    """
    Calculate outlet/sluice discharge using orifice formula.
    
    Q = Cd * A * sqrt(2 * g * H)
    
    Args:
        water_level: Current water level in meters
        
    Returns:
        Dictionary with outlet discharge details
    """
    outlet_area = HYDRAULICS_CONFIG["outlet_area"]
    outlet_coeff = HYDRAULICS_CONFIG["outlet_coefficient"]
    outlet_level = HYDRAULICS_CONFIG["outlet_level"]
    g = HYDRAULICS_CONFIG["gravity"]
    
    # Head above outlet center
    head = max(0, water_level - outlet_level)
    
    discharge = 0.0
    if head > 0 and outlet_area > 0:
        # Orifice flow: Q = Cd * A * sqrt(2gh)
        discharge = outlet_coeff * outlet_area * (2 * g * head) ** 0.5
    
    return {
        "outlet_discharge": round(discharge, 3),
        "head_above_outlet": round(head, 3),
        "outlet_area": outlet_area,
        "unit": "m³/s"
    }


def calculate_gate_rotations(required_discharge: float, water_level: float,
                             pitch: float = None) -> dict:
    """
    Calculate required number of full hand‑wheel rotations for a target discharge
    through the sluice/spillway gate using:
    
        Q = C_d * A * sqrt(2 * g * H)
        A = (N * p) * b
        N = Q / (C_d * p * b * sqrt(2 * g * H))
    
    Args:
        required_discharge: Desired discharge Q (m³/s)
        water_level: Current water level H_water (m)
        pitch: Screw pitch p (m/rotation). If None, uses HYDRAULICS_CONFIG["gate_screw_pitch"].
    
    Returns:
        Dictionary with rotations and intermediate values.
    """
    crest_level = HYDRAULICS_CONFIG["spillway_crest_level"]
    gate_width = HYDRAULICS_CONFIG["gate_width"]
    gate_coeff = HYDRAULICS_CONFIG["gate_coefficient"]
    g = HYDRAULICS_CONFIG["gravity"]
    
    if pitch is None:
        pitch = HYDRAULICS_CONFIG.get("gate_screw_pitch", 0.02)
    
    # Head of water above gate crest
    head = max(0.0, water_level - crest_level)
    
    valid = True
    message = "OK"
    rotations = 0.0
    
    if required_discharge < 0:
        valid = False
        message = "required_discharge must be non‑negative"
    elif head <= 0:
        valid = False
        message = "Water level is at or below gate crest; no discharge possible"
    elif gate_coeff <= 0 or gate_width <= 0 or pitch <= 0 or g <= 0:
        valid = False
        message = "Invalid hydraulic or mechanical parameters"
    else:
        sqrt_term = (2.0 * g * head) ** 0.5
        denominator = gate_coeff * pitch * gate_width * sqrt_term
        if denominator > 0:
            rotations = required_discharge / denominator
        else:
            valid = False
            message = "Denominator in rotation calculation is zero"
    
    return {
        "rotations": round(rotations, 3),
        "required_discharge": required_discharge,
        "water_level": water_level,
        "head_over_crest": round(head, 3),
        "gate_width": gate_width,
        "discharge_coefficient": gate_coeff,
        "pitch_used": pitch,
        "gravity": g,
        "units": {
            "discharge": "m³/s",
            "water_level": "m",
            "pitch": "m/rotation"
        },
        "valid": valid,
        "message": message
    }


def calculate_gate_open_time(required_volume: float,
                             rotations: float,
                             water_level: float,
                             pitch: float = None) -> dict:
    """
    Calculate the time the gate should remain open to pass a target volume V,
    given a number of full rotations N:
    
        Q = C_d * (N * p * b) * sqrt(2 * g * H)
        t = V / Q
    
    Args:
        required_volume: Target volume V in m³
        rotations: Number of full rotations N
        water_level: Current water level H_water in m
        pitch: Screw pitch p in m/rotation. If None, uses HYDRAULICS_CONFIG["gate_screw_pitch"].
    
    Returns:
        Dictionary with open time and intermediate values.
    """
    crest_level = HYDRAULICS_CONFIG["spillway_crest_level"]
    gate_width = HYDRAULICS_CONFIG["gate_width"]
    gate_coeff = HYDRAULICS_CONFIG["gate_coefficient"]
    g = HYDRAULICS_CONFIG["gravity"]
    
    if pitch is None:
        pitch = HYDRAULICS_CONFIG.get("gate_screw_pitch", 0.02)
    
    head = max(0.0, water_level - crest_level)
    
    valid = True
    message = "OK"
    discharge = 0.0
    open_time = 0.0
    
    if required_volume < 0:
        valid = False
        message = "required_volume must be non-negative"
    elif rotations <= 0:
        valid = False
        message = "rotations must be positive"
    elif head <= 0:
        valid = False
        message = "Water level is at or below gate crest; no discharge possible"
    elif gate_coeff <= 0 or gate_width <= 0 or pitch <= 0 or g <= 0:
        valid = False
        message = "Invalid hydraulic or mechanical parameters"
    else:
        sqrt_term = (2.0 * g * head) ** 0.5
        area = rotations * pitch * gate_width
        discharge = gate_coeff * area * sqrt_term
        if discharge > 0:
            open_time = required_volume / discharge
        else:
            valid = False
            message = "Computed discharge is zero; cannot determine time"
    
    return {
        "open_time": round(open_time, 2),
        "required_volume": required_volume,
        "discharge": round(discharge, 3),
        "rotations": rotations,
        "water_level": water_level,
        "head_over_crest": round(head, 3),
        "gate_width": gate_width,
        "discharge_coefficient": gate_coeff,
        "pitch_used": pitch,
        "gravity": g,
        "units": {
            "volume": "m³",
            "discharge": "m³/s",
            "water_level": "m",
            "time": "s",
            "pitch": "m/rotation"
        },
        "valid": valid,
        "message": message
    }


def calculate_total_discharge(water_level: float) -> dict:
    """
    Calculate total discharge (spillway + outlet).
    
    Args:
        water_level: Current water level in meters
        
    Returns:
        Dictionary with all discharge components
    """
    spillway_data = calculate_spillway_discharge(water_level)
    outlet_data = calculate_outlet_discharge(water_level)
    
    total_discharge = spillway_data["total_spillway_discharge"] + outlet_data["outlet_discharge"]
    
    return {
        "spillway": spillway_data,
        "outlet": outlet_data,
        "total_discharge": round(total_discharge, 3),
        "unit": "m³/s"
    }


def calculate_inflow(current_level: float, previous_level: float, 
                     time_interval: float, outflow: float = None) -> dict:
    """
    Calculate inflow using water balance equation.
    
    Inflow = (dV/dt) + Outflow
    dV = Area * dH
    
    Args:
        current_level: Current water level in meters
        previous_level: Previous water level in meters
        time_interval: Time between readings in seconds
        outflow: Total outflow (if None, calculated from current level)
        
    Returns:
        Dictionary with inflow calculation details
    """
    reservoir_area = HYDRAULICS_CONFIG["reservoir_area"]
    
    # Calculate volume change
    level_change = current_level - previous_level
    volume_change = reservoir_area * level_change  # m³
    
    # Rate of volume change
    if time_interval > 0:
        dv_dt = volume_change / time_interval  # m³/s
    else:
        dv_dt = 0
    
    # Calculate outflow if not provided
    if outflow is None:
        discharge_data = calculate_total_discharge(current_level)
        outflow = discharge_data["total_discharge"]
    
    # Water balance: Inflow = dV/dt + Outflow
    inflow = dv_dt + outflow
    
    # Inflow can't be negative (physically)
    inflow = max(0, inflow)
    
    return {
        "inflow": round(inflow, 3),
        "level_change": round(level_change, 4),
        "volume_change": round(volume_change, 2),
        "rate_of_change": round(dv_dt, 3),
        "outflow_used": round(outflow, 3),
        "time_interval": time_interval,
        "unit": "m³/s"
    }


def calculate_all_hydraulics(water_level: float, previous_level: float = None,
                              time_interval: float = 60.0) -> dict:
    """
    Calculate all hydraulic parameters.
    
    Args:
        water_level: Current water level in meters
        previous_level: Previous water level (for inflow calculation)
        time_interval: Time between readings in seconds
        
    Returns:
        Dictionary with all hydraulic calculations
    """
    # Calculate discharge components
    discharge_data = calculate_total_discharge(water_level)
    
    # Calculate inflow if we have previous level
    inflow_data = None
    if previous_level is not None:
        inflow_data = calculate_inflow(
            water_level, 
            previous_level, 
            time_interval,
            discharge_data["total_discharge"]
        )
    
    # Get manual values if calculations are disabled
    use_calc_discharge = HYDRAULICS_CONFIG["use_calculated_discharge"]
    use_calc_spillway = HYDRAULICS_CONFIG["use_calculated_spillway"]
    
    result = {
        "water_level": water_level,
        "spillway": discharge_data["spillway"],
        "outlet": discharge_data["outlet"],
        "total_discharge": discharge_data["total_discharge"],
        "total_outflow": discharge_data["total_discharge"],  # Alias
        "inflow": inflow_data,
        "manual_inflow": HYDRAULICS_CONFIG["manual_inflow"],
        "manual_outflow": HYDRAULICS_CONFIG["manual_outflow"],
        "use_calculated": {
            "discharge": use_calc_discharge,
            "spillway": use_calc_spillway
        }
    }
    
    # If manual values are preferred
    if not use_calc_discharge:
        result["total_outflow"] = HYDRAULICS_CONFIG["manual_outflow"]
    
    return result
