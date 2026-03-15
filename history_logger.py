"""
History Logger - Stores and manages reading history with persistence.
"""

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

HISTORY_FILE = "reading_history.json"
MAX_HISTORY_SIZE = 10000  # Maximum entries to keep

_history_lock = threading.Lock()
_history_cache = None


def get_history_path() -> str:
    """Get the full path to the history file."""
    return os.path.join(os.path.dirname(__file__), HISTORY_FILE)


def load_history() -> List[Dict[str, Any]]:
    """Load history from file."""
    global _history_cache
    
    with _history_lock:
        if _history_cache is not None:
            return _history_cache.copy()
        
        history_path = get_history_path()
        
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r') as f:
                    _history_cache = json.load(f)
                if not isinstance(_history_cache, list):
                    _history_cache = []
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading history: {e}")
                _history_cache = []
        else:
            _history_cache = []
        
        return _history_cache.copy()


def save_history() -> bool:
    """Save history to file."""
    global _history_cache
    
    with _history_lock:
        if _history_cache is None:
            _history_cache = []
        
        # Trim history if too large
        if len(_history_cache) > MAX_HISTORY_SIZE:
            _history_cache = _history_cache[-MAX_HISTORY_SIZE:]
        
        history_path = get_history_path()
        
        try:
            with open(history_path, 'w') as f:
                json.dump(_history_cache, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error saving history: {e}")
            return False


def add_reading(reading: Dict[str, Any]) -> None:
    """Add a reading to history."""
    global _history_cache
    
    with _history_lock:
        if _history_cache is None:
            _history_cache = []
        
        # Ensure timestamp exists
        if 'timestamp' not in reading:
            reading['timestamp'] = datetime.now().isoformat()
        
        _history_cache.append(reading)
        
        # Auto-save every 10 readings
        if len(_history_cache) % 10 == 0:
            save_history_unlocked()


def save_history_unlocked() -> bool:
    """Save history without acquiring lock (caller must hold lock)."""
    global _history_cache
    
    if _history_cache is None:
        return True
    
    # Trim if needed
    if len(_history_cache) > MAX_HISTORY_SIZE:
        _history_cache = _history_cache[-MAX_HISTORY_SIZE:]
    
    history_path = get_history_path()
    
    try:
        with open(history_path, 'w') as f:
            json.dump(_history_cache, f, default=str)
        return True
    except IOError as e:
        print(f"Error saving history: {e}")
        return False


def get_history_filtered(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Get filtered history entries.
    
    Args:
        start_date: ISO format date string (YYYY-MM-DD or full ISO datetime)
        end_date: ISO format date string (YYYY-MM-DD or full ISO datetime)
        limit: Maximum number of entries to return
        
    Returns:
        List of filtered history entries
    """
    history = load_history()
    
    # Parse date filters
    start_dt = None
    end_dt = None
    
    if start_date:
        try:
            if len(start_date) == 10:  # YYYY-MM-DD format
                start_dt = datetime.fromisoformat(start_date)
            else:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    if end_date:
        try:
            if len(end_date) == 10:  # YYYY-MM-DD format
                # End of day
                end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
            else:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    # Filter by date
    filtered = []
    for entry in history:
        timestamp_str = entry.get('timestamp', '')
        if not timestamp_str:
            continue
        
        try:
            entry_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            
            if start_dt and entry_dt < start_dt:
                continue
            if end_dt and entry_dt >= end_dt:
                continue
            
            filtered.append(entry)
        except ValueError:
            # Include entries with unparseable timestamps
            filtered.append(entry)
    
    # Apply limit
    if limit and len(filtered) > limit:
        filtered = filtered[-limit:]
    
    return filtered


def export_to_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    Export history to CSV format.
    
    Args:
        start_date: Start date filter
        end_date: End date filter
        
    Returns:
        CSV string
    """
    history = get_history_filtered(start_date, end_date)
    
    if not history:
        return "No data available for the selected date range"
    
    # Determine all unique keys across all entries
    all_keys = set()
    for entry in history:
        all_keys.update(entry.keys())
    
    # Order keys: timestamp first, then alphabetically
    ordered_keys = ['timestamp']
    ordered_keys.extend(sorted(k for k in all_keys if k != 'timestamp'))
    
    # Build CSV
    lines = []
    lines.append(','.join(ordered_keys))
    
    for entry in history:
        row = []
        for key in ordered_keys:
            value = entry.get(key, '')
            if isinstance(value, dict):
                value = json.dumps(value)
            elif value is None:
                value = ''
            else:
                value = str(value)
            # Escape quotes and wrap in quotes if contains comma
            if ',' in value or '"' in value or '\n' in value:
                value = '"' + value.replace('"', '""') + '"'
            row.append(value)
        lines.append(','.join(row))
    
    return '\n'.join(lines)


def export_to_json(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    Export history to JSON format.
    
    Args:
        start_date: Start date filter
        end_date: End date filter
        
    Returns:
        JSON string
    """
    history = get_history_filtered(start_date, end_date)
    return json.dumps(history, indent=2, default=str)


def get_history_stats() -> Dict[str, Any]:
    """Get statistics about the history."""
    history = load_history()
    
    if not history:
        return {
            'total_entries': 0,
            'oldest_entry': None,
            'newest_entry': None,
            'date_range': None
        }
    
    timestamps = []
    for entry in history:
        ts = entry.get('timestamp')
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
            except ValueError:
                pass
    
    if timestamps:
        oldest = min(timestamps)
        newest = max(timestamps)
        date_range = (newest - oldest).days
    else:
        oldest = None
        newest = None
        date_range = None
    
    return {
        'total_entries': len(history),
        'oldest_entry': oldest.isoformat() if oldest else None,
        'newest_entry': newest.isoformat() if newest else None,
        'date_range_days': date_range
    }


def clear_history() -> bool:
    """Clear all history."""
    global _history_cache
    
    with _history_lock:
        _history_cache = []
        return save_history_unlocked()
