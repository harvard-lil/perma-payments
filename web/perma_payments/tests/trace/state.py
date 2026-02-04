"""
Global state and value normalization for trace module.

This module manages the global state for tracing (enabled status, output paths,
lanes, etc.) and provides normalization functions that replace volatile data
(UUIDs, timestamps, tokens) with stable placeholders for deterministic output.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any


# =============================================================================
# Global State
# =============================================================================

_enabled: bool = False
_output_path: Path | None = None
_lanes: list[str] = []  # Ordered list of lane names as they're encountered

# Normalization state - maps raw values to placeholders for deterministic output
_seen_values: dict[str, str] = {}  # raw_value -> placeholder (e.g., "abc-123..." -> "<uuid_1>")
_value_counts: dict[str, int] = {}  # pattern_name -> count (e.g., "uuid" -> 3)
_screenshot_index: int = 0
_images_dir: Path | None = None

# Page reference for failure capture
_page: Any = None


# =============================================================================
# Normalization Patterns
# =============================================================================

# Global patterns - applied to all string values (order matters)
GLOBAL_PATTERNS = [
    # UUID v4
    ('uuid', re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', re.I)),
    # JWT (three base64url-encoded parts separated by dots)
    ('jwt', re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')),
    # Localhost with port (normalize port) - use fixed placeholder, not indexed
    ('localhost', re.compile(r'http://localhost:\d+')),
    # Long base64-ish strings (likely encrypted data, tokens, etc.) - 40+ chars of base64
    ('token', re.compile(r'[A-Za-z0-9+/=_-]{40,}')),
    # PERMA reference numbers (PERMA-XXXX-XXXX)
    ('ref', re.compile(r'PERMA-\d{4}-\d{4}')),
]

# Key-specific patterns - only applied when key matches
# Format: (key_regex, value_regex, placeholder_name)
KEY_PATTERNS = [
    # customer_pk - test-generated customer IDs
    (re.compile(r'^customer_pk$', re.I), re.compile(r'^\d+$'), 'customer_pk'),
    # Timestamps - Unix timestamps (large floats)
    (re.compile(r'timestamp', re.I), re.compile(r'^\d{10,}\.?\d*$'), 'timestamp'),
    # Datetime repr strings - datetime.datetime(2026, 2, 4, ...) with possible nested parens
    (re.compile(r'timestamp|time|date', re.I), re.compile(r"datetime\.datetime\((?:[^()]+|\([^)]*\))*\)"), 'datetime'),
    # ISO datetime strings - 2026-02-04T14:40:15Z or with milliseconds
    (re.compile(r'time|date|submit', re.I), re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?'), 'datetime'),
    # Local time - 6:40:15
    (re.compile(r'local_time', re.I), re.compile(r'^\d{1,2}:\d{2}:\d{2}$'), 'time'),
    # CyberSource numeric IDs - 17+ digit numbers
    (re.compile(r'^id$|_id$|^href$', re.I), re.compile(r'\d{17,}'), 'cs_id'),
    # CyberSource hex IDs - 32 uppercase hex chars
    (re.compile(r'^id$|_id$', re.I), re.compile(r'[A-F0-9]{32}'), 'cs_hex_id'),
    # Reconciliation ID - alphanumeric ~12 chars
    (re.compile(r'reconciliation_id', re.I), re.compile(r'^[A-Z0-9]{10,14}$'), 'recon_id'),
    # Name field containing Registrar-NNNN
    (re.compile(r'^name$', re.I), re.compile(r'(Registrar-)\d+'), 'registrar_name'),
    # Code fields that might have numeric codes
    (re.compile(r'^code$', re.I), re.compile(r'^\d{2,3}$'), 'code'),
    # Result fields
    (re.compile(r'^result$', re.I), re.compile(r'^\d+$'), 'result'),
]

# Keys where numeric values should be normalized
NUMERIC_KEY_PATTERNS = [
    # customer_pk - test-generated customer IDs
    (re.compile(r'^customer_pk$', re.I), 'customer_pk'),
    # Timestamps - keys containing "timestamp"
    (re.compile(r'timestamp', re.I), 'timestamp'),
    # Primary keys and IDs that are numeric
    (re.compile(r'^pk$|^id$|_pk$|_id$', re.I), 'pk'),
]


# =============================================================================
# State Access Functions
# =============================================================================

def is_enabled() -> bool:
    """Check if tracing is currently enabled."""
    return _enabled


def get_output_path() -> Path | None:
    """Get the current output path."""
    return _output_path


def get_lanes() -> list[str]:
    """Get the current list of lanes."""
    return _lanes.copy()


def get_images_dir() -> Path | None:
    """Get the images directory path."""
    return _images_dir


def get_page() -> Any:
    """Get the registered Playwright page."""
    return _page


def register_lane(name: str) -> None:
    """Register a lane if not already registered."""
    if name not in _lanes:
        _lanes.append(name)


def set_page(page: Any) -> None:
    """Set the page reference for failure capture."""
    global _page
    _page = page


# =============================================================================
# State Management
# =============================================================================

def initialize(output_path: Path) -> None:
    """
    Initialize tracing state.
    
    Args:
        output_path: Path to the JSONL output file
    """
    global _enabled, _output_path, _lanes, _seen_values, _value_counts
    global _screenshot_index, _images_dir
    
    _output_path = output_path
    _output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize normalization state
    _seen_values = {}
    _value_counts = {}
    _screenshot_index = 0
    
    # Create images directory (sibling to traces dir)
    _images_dir = _output_path.parent / 'images'
    _images_dir.mkdir(parents=True, exist_ok=True)
    
    _lanes = []
    _enabled = True


def reset() -> None:
    """Reset all tracing state."""
    global _enabled, _output_path, _lanes, _seen_values, _value_counts
    global _screenshot_index, _images_dir, _page
    
    _enabled = False
    _output_path = None
    _lanes = []
    _seen_values = {}
    _value_counts = {}
    _screenshot_index = 0
    _images_dir = None
    _page = None


# =============================================================================
# Normalization Functions
# =============================================================================

def normalize_numeric(value: int | float, key: str | None = None) -> int | float | str:
    """
    Normalize a numeric value based on its key.
    
    Returns the original value if no normalization applies,
    or a placeholder string if it matches a key pattern.
    """
    if key is None:
        return value
    
    for key_pattern, placeholder_name in NUMERIC_KEY_PATTERNS:
        if key_pattern.search(key):
            return f'<{placeholder_name}>'
    
    return value


def normalize_value(value: str, key: str | None = None) -> str:
    """
    Normalize a string value, replacing volatile data with indexed placeholders.
    
    Preserves identity: if the same raw value appears multiple times, it gets
    the same placeholder, allowing tracing of values through the system.
    
    Args:
        value: The string value to normalize
        key: Optional dict key, used for key-specific patterns
    """
    if not isinstance(value, str):
        return value
    
    # First check if we've seen this exact value before
    if value in _seen_values:
        return _seen_values[value]
    
    result = value
    
    # Apply key-specific patterns first (if key provided)
    if key:
        for key_pattern, value_pattern, placeholder_name in KEY_PATTERNS:
            if key_pattern.search(key):
                def replace_match(match, pname=placeholder_name):
                    raw = match.group(0)
                    if raw in _seen_values:
                        return _seen_values[raw]
                    
                    # Special case for registrar names - preserve prefix
                    if pname == 'registrar_name' and match.lastindex:
                        prefix = match.group(1)
                        _value_counts[pname] = _value_counts.get(pname, 0) + 1
                        placeholder = f'{prefix}<{pname}>'
                    else:
                        _value_counts[pname] = _value_counts.get(pname, 0) + 1
                        placeholder = f'<{pname}>'
                    
                    _seen_values[raw] = placeholder
                    return placeholder
                
                result = value_pattern.sub(replace_match, result)
    
    # Apply global patterns
    for pattern_name, pattern in GLOBAL_PATTERNS:
        def replace_match(match, pname=pattern_name):
            raw = match.group(0)
            if raw in _seen_values:
                return _seen_values[raw]
            
            # Special case: localhost just normalizes the port
            if pname == 'localhost':
                placeholder = 'http://localhost:PORT'
            else:
                # Assign a new index for this pattern type
                _value_counts[pname] = _value_counts.get(pname, 0) + 1
                idx = _value_counts[pname]
                placeholder = f'<{pname}_{idx}>'
            
            _seen_values[raw] = placeholder
            return placeholder
        
        result = pattern.sub(replace_match, result)
    
    return result


def normalize_data(data: Any, key: str | None = None) -> Any:
    """Recursively normalize data, replacing volatile values with placeholders."""
    if isinstance(data, str):
        return normalize_value(data, key)
    elif isinstance(data, dict):
        return {k: normalize_data(v, key=k) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_data(item, key) for item in data]
    else:
        return data


# =============================================================================
# File I/O
# =============================================================================

def write_entry(entry: dict) -> None:
    """Write a single entry to the JSONL file."""
    if _output_path is None:
        return
    
    with open(_output_path, 'a') as f:
        f.write(json.dumps(entry, default=str) + '\n')


def get_next_screenshot_index() -> int:
    """Get and increment the screenshot index."""
    global _screenshot_index
    _screenshot_index += 1
    return _screenshot_index


def save_screenshot(image_bytes: bytes) -> dict:
    """
    Save screenshot to file with content-hash-based naming.
    
    Returns a dict with __image_file__ key for JSON serialization.
    Only writes the file if content has changed (based on hash).
    """
    if not _images_dir:
        # Fallback if images dir not set up (shouldn't happen)
        import base64
        return {'__image_base64__': base64.b64encode(image_bytes).decode('ascii')}
    
    # Generate content hash for deduplication
    content_hash = hashlib.sha256(image_bytes).hexdigest()[:12]
    
    # Use sequential index for ordering, hash for content identity
    idx = get_next_screenshot_index()
    filename = f'screenshot_{idx:03d}_{content_hash}.png'
    filepath = _images_dir / filename
    
    # Only write if file doesn't exist (hash-based deduplication)
    if not filepath.exists():
        filepath.write_bytes(image_bytes)
    
    return {'__image_file__': filename}
