"""
Seven-Segment Display OCR Processor for Laser Meter
Supports range: 0.000m to 250.000m
Configurable digit positions and segment detection.
"""

import cv2
import numpy as np
from typing import Optional, Tuple, List
from collections import deque
import threading
from ocr_config import get_config


class ReadingFilter:
    """
    Filters outlier readings to improve accuracy and precision.
    Uses a sliding window of recent readings to detect and reject anomalies.
    """
    
    def __init__(self, window_size: int = 10, max_deviation_percent: float = 20.0):
        """
        Initialize the reading filter.
        
        Args:
            window_size: Number of recent readings to consider
            max_deviation_percent: Maximum allowed deviation from median (as percentage)
        """
        self.window_size = window_size
        self.max_deviation_percent = max_deviation_percent
        self.readings = deque(maxlen=window_size)
        self.lock = threading.Lock()
        self.last_valid_reading = None
        self.rejected_count = 0
        self.total_count = 0
    
    def add_reading(self, value: float) -> Tuple[Optional[float], bool]:
        """
        Add a new reading and check if it's valid.
        
        Args:
            value: The new reading value
            
        Returns:
            Tuple of (filtered_value, is_valid)
            - filtered_value: The value if valid, or last valid reading if outlier
            - is_valid: True if the reading was accepted, False if rejected as outlier
        """
        with self.lock:
            self.total_count += 1
            
            # If we don't have enough history, accept the reading
            if len(self.readings) < 3:
                self.readings.append(value)
                self.last_valid_reading = value
                return value, True
            
            # Calculate median of recent readings
            sorted_readings = sorted(self.readings)
            median = sorted_readings[len(sorted_readings) // 2]
            
            # Calculate allowed deviation
            if median == 0:
                max_deviation = 0.1  # Small absolute threshold when median is 0
            else:
                max_deviation = abs(median) * (self.max_deviation_percent / 100.0)
            
            # Check if new reading is within acceptable range
            deviation = abs(value - median)
            
            if deviation <= max_deviation:
                # Reading is valid
                self.readings.append(value)
                self.last_valid_reading = value
                return value, True
            else:
                # Reading is an outlier
                self.rejected_count += 1
                # Return last valid reading instead
                return self.last_valid_reading, False
    
    def get_stable_reading(self) -> Optional[float]:
        """Get the current stable reading (median of recent valid readings)."""
        with self.lock:
            return self._get_stable_reading_unlocked()
    
    def _get_stable_reading_unlocked(self) -> Optional[float]:
        """Get stable reading without acquiring lock (caller must hold lock)."""
        if len(self.readings) == 0:
            return None
        sorted_readings = sorted(self.readings)
        return sorted_readings[len(sorted_readings) // 2]
    
    def get_stats(self) -> dict:
        """Get filter statistics."""
        with self.lock:
            return {
                'total_readings': self.total_count,
                'rejected_readings': self.rejected_count,
                'rejection_rate': self.rejected_count / max(1, self.total_count),
                'buffer_size': len(self.readings),
                'last_valid': self.last_valid_reading,
                'stable_reading': self._get_stable_reading_unlocked()
            }
    
    def reset(self):
        """Clear the reading history."""
        with self.lock:
            self.readings.clear()
            self.last_valid_reading = None
            self.rejected_count = 0
            self.total_count = 0


# Global reading filter instance
_reading_filter = None
_filter_lock = threading.Lock()


def get_reading_filter(window_size: int = 10, max_deviation_percent: float = 20.0) -> ReadingFilter:
    """Get or create the global reading filter."""
    global _reading_filter
    with _filter_lock:
        if _reading_filter is None:
            _reading_filter = ReadingFilter(window_size, max_deviation_percent)
        return _reading_filter


def reset_reading_filter():
    """Reset the global reading filter."""
    global _reading_filter
    with _filter_lock:
        if _reading_filter is not None:
            _reading_filter.reset()


class SevenSegmentOCR:
    """OCR for seven-segment displays with configurable parameters."""
    
    # Class-level boundary cache for stability across frames
    _cached_bounds = None
    _bounds_confidence = 0
    _bounds_lock = None
    
    def __init__(self, debug: bool = False, config: dict = None):
        self.debug = debug
        self.config = config or get_config()
        self.debug_images = {}
        
        # Initialize class-level lock if needed
        if SevenSegmentOCR._bounds_lock is None:
            import threading
            SevenSegmentOCR._bounds_lock = threading.Lock()
    
    @classmethod
    def reset_cached_bounds(cls):
        """Reset cached boundaries - call when switching images/streams."""
        if cls._bounds_lock:
            with cls._bounds_lock:
                cls._cached_bounds = None
                cls._bounds_confidence = 0
        else:
            cls._cached_bounds = None
            cls._bounds_confidence = 0

    def find_lcd_bounds(self, image: np.ndarray) -> Tuple[int, int, int, int]:
        """Find LCD display area."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            return cv2.boundingRect(max(contours, key=cv2.contourArea))
        return (0, 0, image.shape[1], image.shape[0])

    def extract_reading_region(self, image: np.ndarray) -> Tuple[np.ndarray, int, int]:
        """Extract the region containing the reading based on config."""
        lx, ly, lw, lh = self.find_lcd_bounds(image)
        
        roi = self.config["roi"]
        x_start = lx + int(lw * roi["x_start_pct"])
        x_end = lx + int(lw * roi["x_end_pct"])
        y_start = ly + int(lh * roi["y_start_pct"])
        y_end = ly + int(lh * roi["y_end_pct"])
        
        return image[y_start:y_end, x_start:x_end], x_start, y_start

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image to isolate digit pixels."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        block_size = self.config.get("adaptive_threshold_block_size", 25)
        c_value = self.config.get("adaptive_threshold_c", 10)
        
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, block_size, c_value)
        
        kernel = np.ones((2, 2), np.uint8)
        return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    def segment_digits_auto(self, binary: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Auto-detect digit positions using vertical projection with boundary stabilization."""
        h, w = binary.shape
        
        # Use projection-based detection (more reliable for slanted seven-segment displays)
        digit_ranges = self._detect_digits_projection(binary)
        
        # If projection fails, try contour-based as fallback
        if not digit_ranges or len(digit_ranges) < 2:
            digit_ranges = self._detect_digits_contour(binary)
        
        if self.debug:
            print(f"Detected digit x-ranges: {digit_ranges}")
        
        # Apply boundary stabilization
        digit_ranges = self._stabilize_bounds(digit_ranges, w)
        
        if self.debug:
            print(f"Stabilized digit x-ranges: {digit_ranges}")
        
        # Convert to bounding boxes
        boxes = []
        for x_start, x_end in digit_ranges:
            column_data = binary[:, x_start:x_end]
            h_proj = np.sum(column_data, axis=1)
            y_start, y_end = 0, h
            for y in range(h):
                if h_proj[y] > 0:
                    y_start = y
                    break
            for y in range(h - 1, -1, -1):
                if h_proj[y] > 0:
                    y_end = y + 1
                    break
            boxes.append((x_start, y_start, x_end - x_start, y_end - y_start))
        
        return boxes
    
    def _detect_digits_contour(self, binary: np.ndarray) -> List[Tuple[int, int]]:
        """Detect digits using contour analysis (more stable than projection)."""
        h, w = binary.shape
        
        # Find contours
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return []
        
        # Get bounding boxes for significant contours
        boxes = []
        min_height = h * 0.3  # Digit should be at least 30% of ROI height
        min_width = 3  # Individual segments can be narrow
        
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            if ch >= min_height and cw >= min_width:
                boxes.append((x, x + cw))
        
        if not boxes:
            return []
        
        # Sort by x position
        boxes.sort(key=lambda b: b[0])
        
        # Smart merging: merge boxes that are close together but don't create
        # digits that are too wide compared to the average
        merged = self._smart_merge_boxes(boxes, w)
        
        return merged
    
    def _smart_merge_boxes(self, boxes: List[Tuple[int, int]], width: int) -> List[Tuple[int, int]]:
        """
        Merge contour boxes into digit regions.
        Strategy: merge nearby segments but ensure resulting digits are reasonable width.
        """
        if not boxes:
            return []
        
        # First pass: minimal merge (only overlapping or touching boxes)
        merged = []
        for box in boxes:
            x_start, x_end = box
            if merged:
                last_x_start, last_x_end = merged[-1]
                # Merge if overlapping or gap < 5 pixels
                if x_start <= last_x_end + 5:
                    merged[-1] = (last_x_start, max(last_x_end, x_end))
                    continue
            merged.append((x_start, x_end))
        
        # If we have more than expected digits, find natural groupings
        expected_digits = 4
        if len(merged) > expected_digits:
            merged = self._group_into_digits(merged, expected_digits, width)
        
        return merged
    
    def _group_into_digits(self, ranges: List[Tuple[int, int]], expected: int, width: int) -> List[Tuple[int, int]]:
        """Group segment ranges into digit regions based on gaps."""
        if len(ranges) <= expected:
            return ranges
        
        # Calculate all gaps
        gaps = []
        for i in range(1, len(ranges)):
            gap = ranges[i][0] - ranges[i-1][1]
            gaps.append((gap, i))
        
        # Sort by gap size (largest first) - these are likely digit boundaries
        gaps.sort(reverse=True, key=lambda x: x[0])
        
        # Find the expected-1 largest gaps as digit separators
        # But ensure they're significantly larger than the smallest gaps we merge
        separator_indices = set()
        
        # Only use gaps that are substantial (> 10 pixels or > 3% of width)
        min_separator_gap = max(10, width * 0.03)
        
        for gap_size, idx in gaps:
            if len(separator_indices) >= expected - 1:
                break
            if gap_size >= min_separator_gap:
                separator_indices.add(idx)
        
        # If we didn't find enough separators, just take the largest gaps
        if len(separator_indices) < expected - 1:
            for gap_size, idx in gaps[:expected - 1]:
                separator_indices.add(idx)
        
        # Build merged ranges based on separators
        result = []
        current_start, current_end = ranges[0]
        
        for i in range(1, len(ranges)):
            if i in separator_indices:
                result.append((current_start, current_end))
                current_start, current_end = ranges[i]
            else:
                current_end = max(current_end, ranges[i][1])
        
        result.append((current_start, current_end))
        return result
    
    def _detect_digits_projection(self, binary: np.ndarray) -> List[Tuple[int, int]]:
        """Detect digits using vertical projection with equal-width regions."""
        h, w = binary.shape
        v_proj = np.sum(binary, axis=0)
        max_val = np.max(v_proj)
        if max_val > 0:
            v_proj = v_proj / max_val
        else:
            return []
        
        # Use low threshold to find any content
        threshold = 0.05
        
        # Find all regions with content
        in_region = False
        regions = []
        start = 0
        
        for i, val in enumerate(v_proj):
            if val > threshold and not in_region:
                start = i
                in_region = True
            elif val <= threshold and in_region:
                regions.append((start, i))
                in_region = False
        
        if in_region:
            regions.append((start, w))
        
        if self.debug:
            print(f"Raw projection regions: {regions}")
        
        # Filter out noise and "m" unit (very narrow or at the end)
        min_width = 8
        filtered = []
        for start, end in regions:
            width = end - start
            if width >= min_width:
                # Skip if it's at the very end and narrow (likely "m" unit)
                if end > w * 0.95 and width < w * 0.1:
                    continue
                filtered.append((start, end))
        
        if not filtered:
            return []
        
        # Now normalize to equal-width digit regions
        # Find the widest digit (likely a full digit like 0, 8, 6, 9)
        # and use that as the standard width for all digits
        digit_ranges = self._normalize_digit_widths(filtered, w)
        
        if self.debug:
            print(f"Normalized digit ranges: {digit_ranges}")
        
        return digit_ranges
    
    def _normalize_digit_widths(self, regions: List[Tuple[int, int]], total_width: int) -> List[Tuple[int, int]]:
        """Normalize all digit regions to have equal width based on spacing."""
        if len(regions) < 2:
            return regions
        
        # Calculate the boundaries between digits (midpoints of gaps)
        boundaries = [0]  # Start
        for i in range(len(regions) - 1):
            # Midpoint between end of current region and start of next
            gap_start = regions[i][1]
            gap_end = regions[i + 1][0]
            boundary = (gap_start + gap_end) // 2
            boundaries.append(boundary)
        boundaries.append(total_width)  # End
        
        # Calculate widths based on boundaries
        widths = [boundaries[i+1] - boundaries[i] for i in range(len(regions))]
        max_width = max(widths)
        
        if self.debug:
            print(f"Boundaries: {boundaries}, Widths: {widths}, Max width: {max_width}")
        
        # Create equal-width non-overlapping regions
        # Use the boundary midpoints to define each digit's region
        normalized = []
        for i in range(len(regions)):
            start = boundaries[i]
            end = boundaries[i + 1]
            normalized.append((start, end))
        
        return normalized
    
    def _stabilize_bounds(self, new_bounds: List[Tuple[int, int]], width: int) -> List[Tuple[int, int]]:
        """Stabilize digit boundaries across frames to prevent jitter."""
        if not new_bounds:
            # Use cached bounds if available
            with SevenSegmentOCR._bounds_lock:
                if SevenSegmentOCR._cached_bounds:
                    return SevenSegmentOCR._cached_bounds
            return []
        
        with SevenSegmentOCR._bounds_lock:
            cached = SevenSegmentOCR._cached_bounds
            
            # If no cache or different digit count, use new bounds but don't cache immediately
            if cached is None or len(cached) != len(new_bounds):
                # Only update cache if we have reasonable digit count (typically 4-6 digits)
                if 3 <= len(new_bounds) <= 7:
                    SevenSegmentOCR._cached_bounds = new_bounds
                    SevenSegmentOCR._bounds_confidence = 1
                return new_bounds
            
            # Compare new bounds to cached - use cached if similar, blend if slightly different
            max_drift = width * 0.05  # 5% drift tolerance
            
            is_similar = True
            for (new_start, new_end), (old_start, old_end) in zip(new_bounds, cached):
                if abs(new_start - old_start) > max_drift or abs(new_end - old_end) > max_drift:
                    is_similar = False
                    break
            
            if is_similar:
                # Bounds are similar - use exponential moving average for smoothing
                alpha = 0.3  # Smoothing factor (lower = more stable)
                smoothed = []
                for (new_start, new_end), (old_start, old_end) in zip(new_bounds, cached):
                    smooth_start = int(old_start * (1 - alpha) + new_start * alpha)
                    smooth_end = int(old_end * (1 - alpha) + new_end * alpha)
                    smoothed.append((smooth_start, smooth_end))
                
                SevenSegmentOCR._cached_bounds = smoothed
                SevenSegmentOCR._bounds_confidence = min(10, SevenSegmentOCR._bounds_confidence + 1)
                return smoothed
            else:
                # Significant change detected
                if SevenSegmentOCR._bounds_confidence > 3:
                    # High confidence in old bounds - might be noise, reduce confidence
                    SevenSegmentOCR._bounds_confidence -= 1
                    return cached
                else:
                    # Low confidence - accept new bounds
                    SevenSegmentOCR._cached_bounds = new_bounds
                    SevenSegmentOCR._bounds_confidence = 1
                    return new_bounds

    def segment_digits_manual(self, binary: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Use manually specified digit bounds from config."""
        h, w = binary.shape
        bounds = self.config.get("manual_digit_bounds", [])
        
        boxes = []
        for x_start, x_end in bounds:
            # Clamp to image bounds
            x_start = max(0, min(x_start, w - 1))
            x_end = max(x_start + 1, min(x_end, w))
            
            # Find y bounds within this x range
            column_data = binary[:, x_start:x_end]
            h_proj = np.sum(column_data, axis=1)
            y_start, y_end = 0, h
            for y in range(h):
                if h_proj[y] > 0:
                    y_start = y
                    break
            for y in range(h - 1, -1, -1):
                if h_proj[y] > 0:
                    y_end = y + 1
                    break
            
            boxes.append((x_start, y_start, x_end - x_start, y_end - y_start))
        
        return boxes

    def segment_digits(self, binary: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Segment digits using either manual bounds or auto-detection."""
        if self.config.get("manual_digit_bounds"):
            return self.segment_digits_manual(binary)
        return self.segment_digits_auto(binary)

    def recognize_digit(self, digit_img: np.ndarray, region_width: int = None) -> str:
        """Recognize digit using center fill and region analysis."""
        original_h, original_w = digit_img.shape
        
        if original_h < 10 or original_w < 3:
            return '?'
        
        # Check for '1' BEFORE cropping - based on how much of the region has content
        # A '1' will only have content in a small portion of its allocated region
        cols_with_any_content = np.any(digit_img > 0, axis=0)
        content_width = np.sum(cols_with_any_content)
        
        # If region_width is provided (from normalized regions), use it for comparison
        compare_width = region_width if region_width else original_w
        content_ratio = content_width / compare_width if compare_width > 0 else 1
        
        if self.debug:
            print(f"    Content width: {content_width}/{compare_width} ({content_ratio:.2f})")
        
        # If content occupies less than 40% of the region width, it's likely a '1'
        if content_ratio < 0.40 and content_width < 25:
            if self.debug:
                print(f"    -> '1' (narrow content ratio)")
            return '1'
        
        # Additional '1' detection: check left/right content distribution
        # A '1' has most content on the right side (the vertical bar)
        left_half = digit_img[:, :original_w//2]
        right_half = digit_img[:, original_w//2:]
        left_content = np.sum(left_half > 0)
        right_content = np.sum(right_half > 0)
        total_content = left_content + right_content
        
        # For '1' detection via distribution:
        # 1. Right side has 3x+ more content than left
        # 2. Content width is relatively narrow (< 50 pixels)
        # 3. Total content is low (a '1' has less pixels than '9', '8', etc.)
        # 4. Content ratio should suggest a narrow digit
        if right_content > left_content * 3 and content_width < 50:
            # Check total pixel density - '1' should have low total content
            # compared to the region size
            region_area = original_h * original_w
            content_density = total_content / region_area if region_area > 0 else 1
            
            # Also check if content is truly narrow relative to region
            if content_ratio < 0.65 and content_density < 0.18:
                if self.debug:
                    print(f"    -> '1' (right-heavy: L={left_content}, R={right_content}, density={content_density:.3f})")
                return '1'
        
        # Tight crop to actual content for further analysis
        rows_with_content = np.any(digit_img > 0, axis=1)
        cols_with_content = np.any(digit_img > 0, axis=0)
        
        if not np.any(rows_with_content) or not np.any(cols_with_content):
            return '?'
        
        y_min = np.argmax(rows_with_content)
        y_max = original_h - np.argmax(rows_with_content[::-1])
        x_min = np.argmax(cols_with_content)
        x_max = original_w - np.argmax(cols_with_content[::-1])
        
        digit_img = digit_img[y_min:y_max, x_min:x_max]
        h, w = digit_img.shape
        
        if h < 10:
            return '?'
        
        # Calculate aspect ratio
        aspect_ratio = w / h if h > 0 else 0
        
        # Additional '1' detection after crop
        if aspect_ratio < 0.25 and w <= 18:
            if self.debug:
                print(f"    [Cropped {w}x{h}] Narrow aspect ({aspect_ratio:.2f}) -> '1'")
            return '1'
        
        # For wider digits, calculate regions
        # For slanted/italic seven-segment displays, the left segments are shifted right
        # and the right segments are shifted left. Use wider regions to capture them.
        
        # Upper half regions (excluding middle horizontal segment)
        # Use 45% width for each side to account for slant
        upper_left = digit_img[int(h*0.12):int(h*0.42), :int(w*0.45)]
        upper_right = digit_img[int(h*0.12):int(h*0.42), int(w*0.55):]
        
        # Lower half regions (excluding middle horizontal segment)
        lower_left = digit_img[int(h*0.58):int(h*0.88), :int(w*0.45)]
        lower_right = digit_img[int(h*0.58):int(h*0.88), int(w*0.55):]
        
        # Calculate fill ratios
        ul_fill = np.sum(upper_left > 0) / max(1, upper_left.size)
        ur_fill = np.sum(upper_right > 0) / max(1, upper_right.size)
        ll_fill = np.sum(lower_left > 0) / max(1, lower_left.size)
        lr_fill = np.sum(lower_right > 0) / max(1, lower_right.size)
        
        # Horizontal segments
        top_seg = digit_img[:int(h*0.15), int(w*0.20):int(w*0.80)]
        bot_seg = digit_img[int(h*0.85):, int(w*0.20):int(w*0.80)]
        
        # For middle segment: check if there's a HORIZONTAL bar connecting left to right
        # Not just any pixels (which could be vertical segments passing through)
        mid_region = digit_img[int(h*0.42):int(h*0.58), :]
        h_proj_mid = np.sum(mid_region, axis=0)
        
        # The middle segment should have CONTINUOUS pixels across the center
        # Check the TRUE center area (40-60% of width) - this is where the horizontal bar would be
        center_start = int(w * 0.35)
        center_end = int(w * 0.65)
        true_center = h_proj_mid[center_start:center_end]
        
        # For a middle segment to exist, the CENTER columns must have pixels
        # (not just the edges which are vertical segments)
        if len(true_center) > 0:
            center_pixels = np.sum(true_center > 0)
            center_width = len(true_center)
            # Middle segment exists if center area is mostly filled
            mid_connected = center_pixels > center_width * 0.6
        else:
            mid_connected = False
        
        top_fill = np.sum(top_seg > 0) / max(1, top_seg.size)
        bot_fill = np.sum(bot_seg > 0) / max(1, bot_seg.size)
        mid_fill = 0.5 if mid_connected else 0.0  # Binary: connected or not
        
        total_fill = np.sum(digit_img > 0) / (h * w)
        
        if self.debug:
            print(f"    [Cropped {w}x{h}] UL:{ul_fill:.2f} UR:{ur_fill:.2f} LL:{ll_fill:.2f} LR:{lr_fill:.2f} "
                  f"Top:{top_fill:.2f} Mid:{mid_fill:.2f} Bot:{bot_fill:.2f}")
        
        # Thresholds - lower for slanted displays where segments may be partially captured
        seg_thresh = 0.12  # Threshold for horizontal segments
        vert_thresh = 0.22  # Threshold for vertical segments (lowered for slanted digits)
        
        has_ul = ul_fill > vert_thresh
        has_ur = ur_fill > vert_thresh
        has_ll = ll_fill > vert_thresh
        has_lr = lr_fill > vert_thresh
        has_top = top_fill > seg_thresh
        has_mid = mid_fill > seg_thresh
        has_bot = bot_fill > seg_thresh
        
        # Calculate relative strengths for better discrimination
        upper_diff = ur_fill - ul_fill  # Positive means more right
        lower_diff = lr_fill - ll_fill  # Positive means more right
        
        # Decision tree based on seven-segment patterns
        # Priority: check distinctive patterns first
        
        # Key insight: mid_fill is the most distinctive feature
        # - 0, 1, 7: NO middle segment
        # - 2, 3, 4, 5, 6, 8, 9: HAS middle segment
        
        if self.debug:
            print(f"      Segments: UL={has_ul} UR={has_ur} LL={has_ll} LR={has_lr} "
                  f"Top={has_top} Mid={has_mid} Bot={has_bot}")
        
        # Check for 0 first: all corners, top, bottom, NO middle
        if not has_mid and has_top and has_bot:
            # Could be 0 or 7
            if has_ll or has_ul:  # Has left side = 0
                return '0'
            # If no left side, it's 7
            return '7'
        
        # Check for no middle segment cases
        if not has_mid:
            if has_top and not has_bot and has_ur:
                return '7'
            # Default no-middle with some content
            if has_top or has_bot:
                return '0'
        
        # From here, we have middle segment (has_mid = True)
        
        # 9: Has middle, top, bottom, upper corners, lower-right, but NOT lower-left
        # The key distinguisher: ll_fill is low AND ul_fill is present (unlike '3')
        if ll_fill < 0.15 and has_ur and has_lr and has_ul:
            return '9'
        
        # 3: Right side only (UR, LR) with top, mid, bottom - NO left side at all
        if ll_fill < 0.15 and ul_fill < 0.15 and has_ur and has_lr:
            return '3'
        
        # 6: Has middle, has lower corners, has upper-left, but weak/no upper-right
        # The key distinguisher: lower half is complete (both LL and LR), but UR is weak
        if ur_fill < ul_fill * 0.8 and has_ll and has_lr:
            # Additional check: 6 should have strong lower-left
            if ll_fill > 0.4:
                return '6'
        
        # Also catch 6 by absolute threshold
        if ur_fill < 0.25 and has_ll and has_lr and (has_ul or ul_fill > 0.15):
            return '6'
        
        # 8: All segments - check if all four corners are present
        if has_ul and has_ur and has_ll and has_lr:
            return '8'
        
        # 2: Upper-right and lower-left, but not upper-left or lower-right
        # Z-shape pattern
        if ur_fill > ll_fill * 0.5 and ll_fill > ur_fill * 0.5:
            if ul_fill < 0.20 and lr_fill < 0.20:
                return '2'
        
        # 3: Right side only (UR, LR) with top, mid, bottom
        if has_ur and has_lr and not has_ul and not has_ll:
            return '3'
        
        # 5: Upper-left, lower-right, no upper-right
        if has_ul and has_lr and not has_ur and not has_ll:
            return '5'
        
        # 4: Upper corners, lower-right, middle, no lower-left
        # Key pattern: middle segment + upper portion + right side going down
        # Allow weaker LR threshold since '4' has a distinctive shape
        has_lr_weak = lr_fill > 0.15  # Lower threshold for '4' detection
        if has_mid and has_ul and has_ur and has_lr_weak and not has_ll:
            # '4' typically has weak or no top/bottom segments
            # But on slanted displays, some bleed may occur
            if not has_top or not has_bot or (top_fill < 0.35 and bot_fill < 0.35):
                return '4'
        
        # Also check for '4' pattern where ll is very weak
        if has_mid and has_ul and has_ur and ll_fill < 0.10:
            # If LR has any presence and we have the upper part, it could be '4'
            if lr_fill > 0.10 and (not has_top or top_fill < 0.35):
                return '4'
        
        # Fallback based on relative fills
        left_total = ul_fill + ll_fill
        right_total = ur_fill + lr_fill
        
        # 9 vs 6 based on which corner is missing
        if ll_fill < lr_fill * 0.4:
            return '9'
        if ur_fill < ul_fill * 0.4:
            return '6'
        
        # 2 vs 5 based on diagonal pattern
        if ur_fill > ul_fill and ll_fill > lr_fill:
            return '2'
        if ul_fill > ur_fill and lr_fill > ll_fill:
            return '5'
        
        # Default fallbacks
        if has_mid:
            if left_total > right_total:
                return '6'
            else:
                return '9'
        else:
            return '0'

    def insert_decimal(self, digits: List[str]) -> str:
        """Insert decimal point at the correct position."""
        decimal_pos = self.config.get("decimal_position", -1)
        digits_after = self.config.get("expected_digits_after_decimal", 3)
        
        if decimal_pos >= 0 and decimal_pos < len(digits):
            # Fixed decimal position
            before = ''.join(digits[:decimal_pos])
            after = ''.join(digits[decimal_pos:])
            return f"{before}.{after}" if before else f"0.{after}"
        else:
            # Auto: assume last N digits are after decimal
            if len(digits) > digits_after:
                before = ''.join(digits[:-digits_after])
                after = ''.join(digits[-digits_after:])
                return f"{before}.{after}"
            elif len(digits) == digits_after:
                return f"0.{''.join(digits)}"
            else:
                return ''.join(digits)

    def process_image(self, image: np.ndarray) -> Tuple[Optional[float], np.ndarray]:
        """Main OCR processing."""
        annotated = image.copy()
        
        digit_region, x_off, y_off = self.extract_reading_region(image)
        if digit_region.size == 0:
            return None, annotated
        
        # Draw ROI (blue box) on the live frame
        cv2.rectangle(
            annotated,
            (x_off, y_off),
            (x_off + digit_region.shape[1], y_off + digit_region.shape[0]),
            (255, 0, 0), 2  # Blue in BGR
        )
        
        binary = self.preprocess(digit_region)
        if self.debug:
            self.debug_images['binary'] = binary
        
        boxes = self.segment_digits(binary)
        if self.debug:
            print(f"Found {len(boxes)} digits")
        
        if not boxes:
            return None, annotated
        
        # Draw a red box around the full digit area (distance_reading region)
        min_x = min(x for (x, _, w, _) in boxes)
        min_y = min(y for (_, y, _, h) in boxes)
        max_x = max(x + w for (x, _, w, _) in boxes)
        max_y = max(y + h for (_, y, _, h) in boxes)
        # Draw prominent boundary around OCR reading (digit area)
        cv2.rectangle(
            annotated,
            (x_off + min_x, y_off + min_y),
            (x_off + max_x, y_off + max_y),
            (0, 0, 255), 3  # Red in BGR, thicker border
        )
        # Label the reading boundary for clarity
        cv2.putText(
            annotated,
            "OCR READING",
            (x_off + min_x, max(y_off + min_y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2
        )
        
        # Recognize each digit (without drawing per-digit boxes to avoid blinking)
        result_chars = []
        for i, (x, y, w, h) in enumerate(boxes):
            digit_img = binary[y:y+h, x:x+w]
            # Pass the full region width for '1' detection
            char = self.recognize_digit(digit_img, region_width=w)
            result_chars.append(char)
            
            if self.debug:
                print(f"    Digit {i+1} recognized as: '{char}'")
        
        # Build result with decimal
        result = self.insert_decimal(result_chars)
        result = result.replace('?', '')
        
        cv2.putText(annotated, f"Reading: {result} m",
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        try:
            if result:
                value = float(result)
                # Validate range
                if 0 <= value <= 250:
                    return value, annotated
        except ValueError:
            pass
        
        return None, annotated


def read_water_level(image_path: str, debug: bool = False) -> Optional[float]:
    """Read water level from image file."""
    image = cv2.imread(image_path)
    if image is None:
        return None
    return SevenSegmentOCR(debug=debug).process_image(image)[0]


def read_water_level_from_frame(frame: np.ndarray, debug: bool = False) -> Tuple[Optional[float], np.ndarray]:
    """Read water level from video frame."""
    return SevenSegmentOCR(debug=debug).process_image(frame)


def read_water_level_filtered(frame: np.ndarray, debug: bool = False) -> Tuple[Optional[float], np.ndarray, bool]:
    """
    Read water level from video frame with outlier filtering.
    
    Returns:
        Tuple of (value, annotated_image, is_valid)
        - value: The filtered reading (or last valid if current is outlier)
        - annotated_image: The annotated frame
        - is_valid: True if reading was accepted, False if rejected as outlier
    """
    raw_value, annotated = SevenSegmentOCR(debug=debug).process_image(frame)
    
    if raw_value is None:
        return None, annotated, False
    
    # Apply outlier filtering
    reading_filter = get_reading_filter()
    filtered_value, is_valid = reading_filter.add_reading(raw_value)
    
    # Add filter status to annotated image
    if not is_valid:
        cv2.putText(annotated, f"[FILTERED: {raw_value}]",
                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    return filtered_value, annotated, is_valid


def reset_ocr_bounds():
    """Reset cached OCR digit boundaries."""
    SevenSegmentOCR.reset_cached_bounds()


if __name__ == "__main__":
    import sys
    
    test_image = "static_test_image.png"
    if len(sys.argv) > 1:
        test_image = sys.argv[1]
    
    print(f"Testing OCR on: {test_image}")
    print("=" * 50)
    
    image = cv2.imread(test_image)
    if image is None:
        print(f"Error: Could not load image {test_image}")
        sys.exit(1)
    
    ocr = SevenSegmentOCR(debug=True)
    value, annotated = ocr.process_image(image)
    
    cv2.imwrite("debug_annotated.png", annotated)
    print("\nSaved debug_annotated.png")
    
    if 'binary' in ocr.debug_images:
        cv2.imwrite("debug_binary.png", ocr.debug_images['binary'])
    
    print(f"\n{'=' * 50}")
    print(f"Detected: {value} m")
    # Expected values: static_test_image.png = 9.089, static_test_image2.png = 1.262
    print(f"{'=' * 50}")
