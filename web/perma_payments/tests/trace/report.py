"""
Report generation - self-contained HTML viewer with all data inlined.

This module generates a single report.html file that can be opened directly
in a browser without a server (works with file:// protocol).
"""

import base64
import json
import re
from pathlib import Path
from typing import Any


def generate_report(traces_dir: str | Path | None = None) -> Path:
    """
    Generate a self-contained report.html with all traces and images inlined.
    
    Args:
        traces_dir: Path to the traces directory (defaults to module's traces/ dir)
    
    Returns:
        Path to the generated report.html file
    """
    if traces_dir is None:
        traces_dir = Path(__file__).parent.parent / 'traces'
    else:
        traces_dir = Path(traces_dir)
    
    if not traces_dir.exists():
        traces_dir.mkdir(parents=True)
    
    # Collect all trace data
    traces_data = _collect_traces(traces_dir)
    
    # Generate HTML
    html = _generate_html(traces_data)
    
    # Write report
    report_path = traces_dir / 'report.html'
    with open(report_path, 'w') as f:
        f.write(html)
    
    return report_path


def _collect_traces(traces_dir: Path) -> dict:
    """Collect all trace data, converting images to base64."""
    images_dir = traces_dir / 'images'
    
    # Find all JSONL trace files
    jsonl_files = sorted(traces_dir.glob('*.jsonl'))
    
    # Pattern to parse test name and params from filename
    filename_pattern = re.compile(r'^(.+)_([^_]+-[^_]+.*)$')
    
    tests: dict[str, list[dict]] = {}
    traces: dict[str, list[dict]] = {}  # filename -> entries
    
    for jsonl_file in jsonl_files:
        stem = jsonl_file.stem
        
        match = filename_pattern.match(stem)
        if match:
            test_name = match.group(1)
            params = match.group(2)
        else:
            test_name = stem
            params = ''
        
        # Read and process entries
        entries = []
        lanes = []
        sections = []
        has_failure = False
        
        try:
            with open(jsonl_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    
                    # Convert image file references to base64
                    entry = _convert_images_to_base64(entry, images_dir)
                    entries.append(entry)
                    
                    entry_type = entry.get('type')
                    if entry_type == 'section':
                        sections.append(entry.get('title', 'Untitled'))
                    elif entry_type == 'internal':
                        lane = entry.get('lane')
                        if lane and lane not in lanes:
                            lanes.append(lane)
                        if 'TEST FAILED' in entry.get('title', ''):
                            has_failure = True
                    elif entry_type == 'network':
                        for lane in [entry.get('from_lane'), entry.get('to_lane')]:
                            if lane and lane not in lanes:
                                lanes.append(lane)
        except (json.JSONDecodeError, OSError):
            continue
        
        # Skip empty traces
        meaningful = [e for e in entries if e.get('type') not in ('setup', 'teardown')]
        if not meaningful:
            continue
        
        # Store trace data
        traces[jsonl_file.name] = entries
        
        # Build manifest entry
        if test_name not in tests:
            tests[test_name] = []
        
        tests[test_name].append({
            'filename': jsonl_file.name,
            'params': params,
            'entry_count': len(meaningful),
            'lanes': lanes,
            'sections': sections,
            'has_failure': has_failure,
        })
    
    return {
        'tests': tests,
        'traces': traces,
    }


def _convert_images_to_base64(data: Any, images_dir: Path) -> Any:
    """Recursively convert __image_file__ references to __image_base64__."""
    if isinstance(data, dict):
        if '__image_file__' in data:
            filename = data['__image_file__']
            image_path = images_dir / filename
            if image_path.exists():
                image_bytes = image_path.read_bytes()
                return {'__image_base64__': base64.b64encode(image_bytes).decode('ascii')}
            return data
        return {k: _convert_images_to_base64(v, images_dir) for k, v in data.items()}
    elif isinstance(data, list):
        return [_convert_images_to_base64(item, images_dir) for item in data]
    return data


def _generate_html(data: dict) -> str:
    """Generate the complete HTML with all data inlined."""
    
    template = _get_html()

    css = _get_css()
    js = _get_js()
    manifest_json = json.dumps({'tests': data['tests']})
    traces_json = json.dumps(data['traces'])
    
    return template.format(css=css, js=js, manifest_json=manifest_json, traces_json=traces_json)


def _get_viewer_dir() -> Path:
    """Return the path to the viewer directory."""
    return Path(__file__).parent / 'viewer'


def _get_css() -> str:
    """Return the CSS for the viewer (read from viewer/viewer.css)."""
    css_path = _get_viewer_dir() / 'viewer.css'
    return css_path.read_text()


def _get_js() -> str:
    """Return the JavaScript for the viewer (read from viewer/viewer.js)."""
    js_path = _get_viewer_dir() / 'viewer.js'
    return js_path.read_text()


def _get_html() -> str:
    """Return the HTML for the viewer (read from viewer/report.html)."""
    html_path = _get_viewer_dir() / 'report.html'
    return html_path.read_text()
