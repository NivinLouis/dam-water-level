"""
Configuration Manager - Handles saving and loading settings to/from a JSON file.
"""

import json
import os
import threading
from typing import Any, Dict

CONFIG_FILE = "dam_config.json"

# Default configuration
DEFAULT_CONFIG = {
    "dam": {
        "device_height": 120.0,
        "min_water_level": 0.0,
        "max_water_level": 120.0,
        "warning_threshold_percent": 80.0,
        "critical_threshold_percent": 90.0,
        "low_water_threshold_percent": 20.0,
        "dam_name": "Dam Water Level Monitor",
        "location": "",
        "unit": "m"
    },
    "hydraulics": {
        # Reservoir parameters
        "reservoir_area": 1000.0,  # Surface area in m² (for inflow calculation from level change)
        
        # Spillway parameters (for spillway discharge calculation)
        "spillway_crest_level": 8.0,  # Spillway crest elevation in meters
        "spillway_length": 10.0,  # Spillway length in meters
        "spillway_coefficient": 1.84,  # Discharge coefficient (typical 1.6-2.2 for broad-crested)
        "num_spillway_gates": 3,  # Number of spillway gates/shutters
        "gate_width": 3.0,  # Width of each gate in meters
        "gate_opening": 0.0,  # Current gate opening in meters (0 = closed)
        "gate_coefficient": 0.6,  # Gate discharge coefficient
        
        # Outlet/Sluice discharge parameters
        "outlet_area": 2.0,  # Outlet cross-sectional area in m²
        "outlet_coefficient": 0.62,  # Discharge coefficient for outlet
        "outlet_level": 2.0,  # Outlet center elevation in meters
        
        # Manual input values (for when sensors aren't available)
        "manual_inflow": 0.0,  # Manual inflow value in m³/s
        "manual_outflow": 0.0,  # Manual outflow value in m³/s
        
        # Calculation settings
        "use_calculated_discharge": True,  # Use formula-based discharge calculation
        "use_calculated_spillway": True,  # Use formula-based spillway calculation
        "gravity": 9.81  # Gravitational acceleration m/s²
    },
    "ocr": {
        "roi": {
            "x_start_pct": 0.28,
            "x_end_pct": 0.78,
            "y_start_pct": 0.78,
            "y_end_pct": 0.98
        },
        "decimal_position": 1,
        "expected_digits_after_decimal": 3,
        "adaptive_threshold_block_size": 25,
        "adaptive_threshold_c": 10
    },
    "esp_cam": {
        "url": "",
        "auto_connect": False
    }
}

_config_lock = threading.Lock()
_config_cache = None


def get_config_path() -> str:
    """Get the full path to the config file."""
    return os.path.join(os.path.dirname(__file__), CONFIG_FILE)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _save_config_unlocked() -> bool:
    """Save config without acquiring lock (caller must hold lock)."""
    global _config_cache
    
    if _config_cache is None:
        _config_cache = DEFAULT_CONFIG.copy()
    
    config_path = get_config_path()
    
    try:
        with open(config_path, 'w') as f:
            json.dump(_config_cache, f, indent=2)
        return True
    except IOError as e:
        print(f"Error saving config: {e}")
        return False


def load_config() -> Dict[str, Any]:
    """Load configuration from file, or return defaults if file doesn't exist."""
    global _config_cache
    
    with _config_lock:
        if _config_cache is not None:
            return _config_cache.copy()
        
        config_path = get_config_path()
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                
                # Merge with defaults to ensure all keys exist
                _config_cache = _deep_merge(DEFAULT_CONFIG.copy(), loaded_config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading config: {e}, using defaults")
                _config_cache = DEFAULT_CONFIG.copy()
        else:
            _config_cache = DEFAULT_CONFIG.copy()
            # Save default config to file
            _save_config_unlocked()
        
        return _config_cache.copy()


def save_config(config: Dict[str, Any] = None) -> bool:
    """Save configuration to file."""
    global _config_cache
    
    with _config_lock:
        if config is not None:
            _config_cache = config
        
        return _save_config_unlocked()


def update_config_section(section: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update a specific section of the configuration."""
    global _config_cache
    
    with _config_lock:
        if _config_cache is None:
            # Load without lock since we already have it
            config_path = get_config_path()
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        _config_cache = json.load(f)
                except:
                    _config_cache = DEFAULT_CONFIG.copy()
            else:
                _config_cache = DEFAULT_CONFIG.copy()
        
        if section in _config_cache:
            _config_cache[section].update(data)
        else:
            _config_cache[section] = data
        
        # Save to file
        _save_config_unlocked()
        
        return _config_cache.copy()


def get_config_section(section: str) -> Dict[str, Any]:
    """Get a specific section of the configuration."""
    config = load_config()
    return config.get(section, {})


def reset_to_defaults() -> Dict[str, Any]:
    """Reset configuration to defaults."""
    global _config_cache
    
    with _config_lock:
        _config_cache = DEFAULT_CONFIG.copy()
        _save_config_unlocked()
        return _config_cache.copy()


def apply_config_to_modules():
    """Apply loaded configuration to OCR and Dam modules."""
    try:
        from ocr_config import update_config, update_dam_config
        
        config = load_config()
        
        # Apply OCR config
        if 'ocr' in config:
            update_config(config['ocr'])
        
        # Apply Dam config
        if 'dam' in config:
            update_dam_config(config['dam'])
    except ImportError as e:
        print(f"Warning: Could not apply config to modules: {e}")
