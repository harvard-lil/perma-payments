"""
Core tracing API - logging functions for trace entries.

This module provides the main API for logging trace entries:
- log(): Core logging function for internal and network events
- screenshot(): Capture browser state with screenshot
- db(): Log database model state
- section(): Mark sections for navigation
"""

import inspect
import re
from pathlib import Path
from typing import Any

from . import state


# =============================================================================
# Setup / Teardown
# =============================================================================

def setup(output_path: str | Path, clear_existing: bool = True) -> None:
    """
    Initialize tracing.

    Args:
        output_path: Path to the JSONL output file
        clear_existing: If True, clear any existing file at the path
    """
    path = Path(output_path)
    
    if clear_existing and path.exists():
        path.unlink()
    
    state.initialize(path)
    state.write_entry({'type': 'setup'})


def teardown() -> None:
    """Disable tracing, prune unused images, and reset state."""
    if state.is_enabled():
        state.write_entry({'type': 'teardown'})
        
        # Prune images that are no longer referenced by any trace file
        images_dir = state.get_images_dir()
        if images_dir and images_dir.exists():
            _prune_orphan_images(images_dir)
    
    state.reset()


def register_page(page: Any) -> None:
    """
    Register a Playwright page for failure capture.
    
    When a test fails, if a page is registered, capture_failure() will
    automatically take a screenshot showing the browser state at failure time.
    
    Args:
        page: Playwright Page object
    """
    state.set_page(page)


def capture_failure(error: Exception) -> None:
    """
    Capture browser state when a test fails.
    
    Takes a screenshot and logs the error details. Called automatically
    by the pytest hook when a test fails, if a page is registered.
    
    Args:
        error: The exception that caused the test failure
    """
    if not state.is_enabled():
        return
    
    page = state.get_page()
    if page is None:
        return
    
    # Build error info
    error_type = type(error).__name__
    error_message = str(error)
    
    # Truncate long error messages
    if len(error_message) > 500:
        error_message = error_message[:500] + '...'
    
    data = {
        'error_type': error_type,
        'error_message': error_message,
    }
    
    # Try to capture current URL
    try:
        data['url'] = page.url
    except Exception:
        pass
    
    # Try to capture page title
    try:
        data['title'] = page.title()
    except Exception:
        pass
    
    # Try to capture DOM content
    try:
        dom_content = page.content()
        # Truncate very large DOMs to avoid bloating the trace
        if len(dom_content) > 100000:
            dom_content = dom_content[:100000] + '\n<!-- ... truncated (>100KB) -->'
        data['dom'] = dom_content
    except Exception as e:
        data['dom_error'] = str(e)
    
    # Try to take a screenshot
    try:
        screenshot_bytes = page.screenshot(full_page=True)
        data['screenshot'] = screenshot_bytes
    except Exception as e:
        data['screenshot_error'] = str(e)
    
    log(
        title=f'TEST FAILED: {error_type}',
        lane='Browser',
        data=data,
        include_stack=False,  # The pytest output will have the full traceback
    )


# =============================================================================
# Core Logging API
# =============================================================================

def log(
    title: str,
    *,
    lane: str | None = None,
    from_lane: str | None = None,
    to_lane: str | None = None,
    data: dict | None = None,
    explanation: str | None = None,
    include_stack: bool = True,
) -> None:
    """
    Log a trace entry.

    For internal events (state within one actor):
        trace.log(title='...', lane='Browser', data={...})

    For network events (communication between actors):
        trace.log(title='...', from_lane='Server', to_lane='CyberSource', data={...})

    Args:
        title: Short description shown in the box header
        lane: For internal events - which lane this belongs to
        from_lane: For network events - source lane
        to_lane: For network events - destination lane
        data: Key-value pairs to display (values rendered monospace)
        explanation: Optional longer text, revealed on click
        include_stack: Whether to capture call stack (default True)
    """
    if not state.is_enabled():
        return

    # Validate: must have either lane OR (from_lane AND to_lane)
    is_internal = lane is not None
    is_network = from_lane is not None and to_lane is not None

    if not (is_internal or is_network):
        raise ValueError("Must specify either 'lane' (internal) or both 'from_lane' and 'to_lane' (network)")
    if is_internal and is_network:
        raise ValueError("Cannot specify both 'lane' and 'from_lane'/'to_lane'")

    # Register lanes in order encountered
    if is_internal:
        state.register_lane(lane)
    else:
        state.register_lane(from_lane)
        state.register_lane(to_lane)

    entry = {
        'type': 'internal' if is_internal else 'network',
        'title': title,
        'data': _serialize_data(data or {}),
    }

    if is_internal:
        entry['lane'] = lane
    else:
        entry['from_lane'] = from_lane
        entry['to_lane'] = to_lane

    if explanation:
        entry['explanation'] = explanation

    if include_stack:
        entry['stack_trace'] = _capture_stack_trace()

    state.write_entry(entry)


# =============================================================================
# Convenience Helpers
# =============================================================================

def screenshot(page: Any, title: str | None = None) -> None:
    """
    Log browser state with a screenshot.

    Args:
        page: Playwright Page object
        title: Optional title (defaults to 'Browser State')
    """
    if not state.is_enabled():
        return

    data = {
        'url': page.url,
    }

    try:
        data['title'] = page.title()
    except Exception:
        pass

    try:
        screenshot_bytes = page.screenshot(full_page=True)
        data['screenshot'] = screenshot_bytes  # Will be saved to images/ directory
    except Exception as e:
        data['screenshot_error'] = str(e)

    log(
        title=title or 'Browser State',
        lane='Browser',
        data=data,
        include_stack=True,
    )


def db(instance: Any, title: str | None = None, action: str = 'Write') -> None:
    """
    Log database model state.

    Args:
        instance: Django model instance
        title: Optional title (defaults to 'ModelName pk=N')
        action: 'Write' or 'Fetch' - shown as prefix in Server lane
    """
    if not state.is_enabled():
        return

    model_name = instance._meta.model_name
    pk = instance.pk

    data = {
        'model': f'{instance._meta.app_label}.{model_name}',
        'pk': pk,
    }

    # Extract fields
    try:
        from django.forms.models import model_to_dict
        fields = model_to_dict(instance)
        data['fields'] = fields
    except Exception:
        # Fallback to __dict__
        try:
            data['fields'] = {
                k: v for k, v in instance.__dict__.items()
                if not k.startswith('_')
            }
        except Exception as e:
            data['fields_error'] = str(e)

    # Database events go in Server lane with action prefix
    base_title = title or f'{model_name} pk={pk}'
    log(
        title=f'{action}: {base_title}',
        lane='Server',
        data=data,
        include_stack=True,
    )


def section(title: str) -> None:
    """
    Mark a new section in the trace.
    
    Sections create visual dividers in the sequence diagram and generate
    a table of contents at the top of the HTML output when sections exist.
    
    Args:
        title: The section title (shown in TOC and as a divider)
    """
    if not state.is_enabled():
        return
    
    state.write_entry({
        'type': 'section',
        'title': title,
    })


# =============================================================================
# Private Helpers
# =============================================================================

def _prune_orphan_images(images_dir: Path) -> None:
    """Remove images in the images directory that aren't referenced by any trace file."""
    import json
    
    traces_dir = images_dir.parent
    
    # Collect all image filenames referenced in all JSONL files
    referenced_images = set()
    for jsonl_file in traces_dir.glob('*.jsonl'):
        try:
            with open(jsonl_file, 'r') as f:
                for line in f:
                    # Look for __image_file__ references
                    if '__image_file__' in line:
                        entry = json.loads(line)
                        _collect_image_refs(entry, referenced_images)
        except (json.JSONDecodeError, OSError):
            continue
    
    # Remove unreferenced images
    for image_file in images_dir.glob('*.png'):
        if image_file.name not in referenced_images:
            image_file.unlink()


def _collect_image_refs(data: Any, refs: set) -> None:
    """Recursively collect __image_file__ values from data."""
    if isinstance(data, dict):
        if '__image_file__' in data:
            refs.add(data['__image_file__'])
        else:
            for v in data.values():
                _collect_image_refs(v, refs)
    elif isinstance(data, list):
        for item in data:
            _collect_image_refs(item, refs)


def _capture_stack_trace() -> list[dict]:
    """
    Capture the current stack trace, excluding trace module frames.

    Returns a list of frame dicts with filename, lineno, function, and code.
    Paths are made relative by stripping common prefixes (project dir, site-packages).
    """
    stack = []
    for frame_info in inspect.stack()[2:]:  # Skip this function and caller
        # Skip frames from this module
        if '/trace/' in frame_info.filename or frame_info.filename.endswith('trace.py'):
            continue
        stack.append({
            'filename': _relativize_path(frame_info.filename),
            'lineno': frame_info.lineno,
            'function': frame_info.function,
            'code': frame_info.code_context[0].strip() if frame_info.code_context else None,
        })
    return stack


def _relativize_path(filepath: str) -> str:
    """
    Convert absolute path to relative by stripping common prefixes.
    
    Handles:
    - Project directory (e.g., /app/web/perma_payments/ -> perma_payments/)
    - Site-packages (e.g., /usr/local/lib/python3.11/site-packages/django/ -> django/)
    """
    # Strip site-packages prefix
    site_packages_match = re.search(r'/site-packages/(.+)$', filepath)
    if site_packages_match:
        return site_packages_match.group(1)
    
    # Strip project directory - look for perma_payments as the anchor
    project_match = re.search(r'/(perma_payments/.+)$', filepath)
    if project_match:
        return project_match.group(1)
    
    # Strip /app/ prefix (Docker convention)
    if filepath.startswith('/app/'):
        return filepath[5:]  # Remove '/app/'
    
    # Fallback: just the filename
    return filepath.split('/')[-1] if '/' in filepath else filepath


def _serialize_data(data: dict) -> dict:
    """Serialize data dict, handling special types like images."""
    result = {}
    for key, value in data.items():
        result[key] = _serialize_value(value, key=key)
    return result


def _serialize_value(value: Any, key: str | None = None) -> Any:
    """Serialize a value for JSON storage, normalizing volatile data."""
    if value is None or isinstance(value, bool):
        return value
    elif isinstance(value, (int, float)):
        # Normalize numeric values based on key patterns
        return state.normalize_numeric(value, key)
    elif isinstance(value, str):
        # Normalize strings to replace volatile data with placeholders
        return state.normalize_value(value, key=key)
    elif isinstance(value, bytes):
        # Check if it's an image (PNG magic bytes or JPEG)
        if value[:8] == b'\x89PNG\r\n\x1a\n' or value[:2] == b'\xff\xd8':
            return state.save_screenshot(value)
        try:
            # Normalize decoded string
            return state.normalize_value(value.decode('utf-8'), key=key)
        except UnicodeDecodeError:
            return f'<binary: {len(value)} bytes>'
    elif isinstance(value, dict):
        return {str(k): _serialize_value(v, key=k) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [_serialize_value(item, key=key) for item in value]
    else:
        try:
            return state.normalize_value(repr(value), key=key)
        except Exception:
            return f'<unserializable: {type(value).__name__}>'


def _truncate_url(url: str, max_len: int = 50) -> str:
    """Truncate a URL for display in titles."""
    if len(url) <= max_len:
        return url
    return url[:max_len - 3] + '...'
