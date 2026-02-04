"""
Network tracing - browser network capture and network request/response logging.

This module provides:
- network_request(): Log outgoing HTTP requests
- network_response(): Log HTTP responses
- BrowserNetworkCapture: Context manager for automatic browser network tracing
- capture_browser_network(): Convenience function for the context manager
"""

import json
import re
from typing import Any

from . import state
from .core import log, screenshot, _truncate_url


# =============================================================================
# Network Request/Response Helpers
# =============================================================================

def network_request(
    from_lane: str,
    to_lane: str,
    *,
    method: str,
    url: str,
    body: Any = None,
    headers: dict | None = None,
    title: str | None = None,
    from_url: str | None = None,
) -> None:
    """
    Log an outgoing network request.

    Args:
        from_lane: Source lane
        to_lane: Destination lane
        method: HTTP method
        url: Request URL
        body: Request body (will be pretty-printed if dict/JSON)
        headers: Request headers
        title: Optional title (defaults to 'METHOD url')
        from_url: The current page URL where the request originated (for Browser requests)
    """
    if not state.is_enabled():
        return

    data = {
        'method': method,
        'url': url,
    }

    if from_url:
        data['from'] = from_url

    if body is not None:
        data['body'] = body

    if headers:
        data['headers'] = headers

    log(
        title=title or f'{method} {_truncate_url(url)}',
        from_lane=from_lane,
        to_lane=to_lane,
        data=data,
        include_stack=True,
    )


def network_response(
    from_lane: str,
    to_lane: str,
    *,
    status: int,
    body: Any = None,
    headers: dict | None = None,
    title: str | None = None,
    explanation: str | None = None,
) -> None:
    """
    Log a network response.

    Args:
        from_lane: Source lane (typically the API that responded)
        to_lane: Destination lane (typically the caller)
        status: HTTP status code
        body: Response body
        headers: Response headers
        title: Optional title (defaults to 'Response STATUS')
        explanation: Optional longer description
    """
    if not state.is_enabled():
        return

    data = {
        'status': status,
    }

    if body is not None:
        data['body'] = body

    if headers:
        data['headers'] = headers

    log(
        title=title or f'Response {status}',
        explanation=explanation,
        from_lane=from_lane,
        to_lane=to_lane,
        data=data,
        include_stack=True,
    )


# =============================================================================
# Playwright Network Capture
# =============================================================================

class BrowserNetworkCapture:
    """
    Capture and trace browser network traffic to known payment lanes.
    
    Usage:
        titles = {
            '/subscribe/': ['Subscribe Request', 'Payment Form'],
            '/callback/': ['Callback'],
            '/flex/v2/tokens': ['Create Token'],
        }
        with trace.capture_browser_network(page, server_url=live_server.url, titles=titles):
            page.goto(url)
            # ... do things ...
        # All network traffic is automatically traced with custom titles
    
    Features:
        - Captures traffic to known lanes only (allowlist approach)
        - Captures Browser → CyberSource/Stripe traffic invisible to server-side code
        - Custom titles for requests by path
        - Auto-screenshot for HTML page responses
        - Skips JS bundles, images, fonts, etc.
    
    Lane classification (allowlist - only these are captured):
        - server_url matches → 'Server'
        - checkout.stripe.com, billing.stripe.com, api.stripe.com → 'Stripe'
        - testsecureacceptance.cybersource.com → 'Cybersource Legacy'
        - testflex.cybersource.com → 'Cybersource Rest'
        - perma.test → 'Perma.cc'
    """
    
    # URL patterns for lane classification (allowlist - only these are captured)
    LANE_PATTERNS = [
        (r'^https?://testsecureacceptance\.cybersource\.com', 'Cybersource Legacy'),
        (r'^https?://testflex\.cybersource\.com', 'Cybersource Rest'),
        (r'^https?://checkout\.stripe\.com', 'Stripe'),
        (r'^https?://billing\.stripe\.com', 'Stripe'),
        (r'^https?://api\.stripe\.com', 'Stripe'),
        (r'^https?://perma\.test', 'Perma.cc'),  # Production/staging server
    ]
    
    # Patterns to skip even if they match a lane pattern
    SKIP_PATTERNS = [
        r'/microform/bundle/',  # CyberSource Flex Microform JS bundles
        r'\.js(\?|$)',  # JavaScript files
        r'\.(png|jpg|jpeg|gif|svg|ico|css|woff|woff2|ttf|eot)(\?|$)',  # Static assets
    ]
    
    def __init__(
        self,
        page: Any,
        server_url: str | None = None,
        titles: dict[str, list[str]] | None = None,
        include_resources: bool = False,
        auto_screenshot: bool = True,
    ):
        """
        Args:
            page: Playwright page object
            server_url: URL of the test server (for 'Server' lane classification)
            titles: Dict mapping URL paths to list of titles (consumed in order)
                    e.g., {'/subscribe/': ['Subscribe Request', 'Payment Form']}
            include_resources: If False, skip images/css/fonts/js bundles (default: False)
            auto_screenshot: Take screenshot after HTML page loads (default: True)
        """
        self.page = page
        self.server_url = server_url.rstrip('/') if server_url else None
        self.titles = {k: list(v) for k, v in (titles or {}).items()}  # Copy lists
        self.include_resources = include_resources
        self.auto_screenshot = auto_screenshot
        self._request_handler = None
        self._response_handler = None
        self._pending_requests: dict[str, dict] = {}  # url -> request data
    
    def _classify_lane(self, url: str) -> str:
        """Determine which lane a URL belongs to."""
        # Check if it's our server
        if self.server_url and url.startswith(self.server_url):
            return 'Server'
        
        # Check known patterns
        for pattern, lane in self.LANE_PATTERNS:
            if re.search(pattern, url):
                return lane
        
        # Fall back to domain name
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or 'Unknown'
        except Exception:
            return 'Unknown'
    
    def _get_title(self, url: str, method: str, default: str) -> str:
        """Get custom title for a URL path, or use default."""
        from urllib.parse import urlparse
        try:
            path = urlparse(url).path
        except Exception:
            return default
        
        # Check each registered path
        for registered_path, title_list in self.titles.items():
            if registered_path in path and title_list:
                # Consume the first title
                return title_list.pop(0)
        
        return default
    
    def _should_capture(self, request: Any) -> bool:
        """Determine if a request should be captured."""
        url = request.url
        
        # Skip static resources by type (unless include_resources=True)
        if not self.include_resources:
            resource_type = request.resource_type
            if resource_type in ('image', 'stylesheet', 'font', 'media', 'script'):
                return False
        
        # Skip by URL pattern (always applied)
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, url, re.I):
                return False
        
        # Allowlist: must match server_url or a known lane pattern
        if self.server_url and url.startswith(self.server_url):
            return True
        
        for pattern, _ in self.LANE_PATTERNS:
            if re.search(pattern, url):
                return True
        
        # Doesn't match any known lane - skip
        return False
    
    def _parse_form_data(self, post_data: str | None) -> dict | str | None:
        """Parse POST data, handling both JSON and form-urlencoded."""
        if not post_data:
            return None
        
        # Try JSON first
        try:
            return json.loads(post_data)
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Try form-urlencoded
        try:
            from urllib.parse import parse_qs
            parsed = parse_qs(post_data)
            # parse_qs returns lists, simplify single values
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        except Exception:
            pass
        
        # Return as-is (truncated if long)
        if len(post_data) > 1000:
            return post_data[:1000] + '...'
        return post_data
    
    def _on_request(self, request: Any) -> None:
        """Handle a network request event."""
        if not state.is_enabled():
            return
        
        if not self._should_capture(request):
            return
        
        url = request.url
        method = request.method
        to_lane = self._classify_lane(url)
        
        # Try to get request body
        try:
            post_data = request.post_data
        except Exception:
            post_data = None
        
        # Store for pairing with response
        self._pending_requests[url] = {
            'method': method,
            'to_lane': to_lane,
            'body': post_data,
        }
        
        # Build data for trace
        data = {'method': method, 'url': url}
        if post_data:
            data['body'] = self._parse_form_data(post_data)
        
        # Get custom title or default
        default_title = f'{method} {_truncate_url(url)}'
        title = self._get_title(url, method, default_title)
        
        log(
            title=title,
            from_lane='Browser',
            to_lane=to_lane,
            data=data,
            include_stack=False,
        )
    
    def _on_response(self, response: Any) -> None:
        """Handle a network response event."""
        if not state.is_enabled():
            return
        
        request = response.request
        if not self._should_capture(request):
            return
        
        url = response.url
        status = response.status
        from_lane = self._classify_lane(url)
        
        # Get content type
        content_type = response.headers.get('content-type', '')
        is_html = 'html' in content_type
        
        # Try to get response body
        body_data = None
        try:
            if 'json' in content_type:
                body_text = response.text()
                if body_text:
                    try:
                        body_data = json.loads(body_text)
                    except json.JSONDecodeError:
                        body_data = body_text[:500] + '...' if len(body_text) > 500 else body_text
            elif 'text' in content_type and not is_html:
                body_text = response.text()
                if body_text and len(body_text) < 500:
                    body_data = body_text
        except Exception:
            pass
        
        # Build response data
        data = {'status': status}
        if body_data:
            data['body'] = body_data
        
        # Clean up pending request (if any)
        self._pending_requests.pop(url, None)
        
        # Get custom title or default
        default_title = f'Response {status}'
        title = self._get_title(url, 'RESPONSE', default_title)
        
        log(
            title=title,
            from_lane=from_lane,
            to_lane='Browser',
            data=data,
            include_stack=False,
        )
        
        # Auto-screenshot for HTML responses
        if self.auto_screenshot and is_html and status == 200:
            try:
                # Wait for page to settle
                self.page.wait_for_load_state('domcontentloaded', timeout=5000)
                page_title = self.page.title() or 'Page'
                screenshot(self.page, title=f'{page_title}')
            except Exception:
                pass  # Screenshot failed, continue
    
    def __enter__(self) -> 'BrowserNetworkCapture':
        """Start capturing network events."""
        self._request_handler = lambda r: self._on_request(r)
        self._response_handler = lambda r: self._on_response(r)
        
        self.page.on('request', self._request_handler)
        self.page.on('response', self._response_handler)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop capturing network events."""
        # Actually remove the event listeners from the page
        if self._request_handler:
            try:
                self.page.remove_listener('request', self._request_handler)
            except Exception:
                pass
        if self._response_handler:
            try:
                self.page.remove_listener('response', self._response_handler)
            except Exception:
                pass
        self._request_handler = None
        self._response_handler = None
        return None


def capture_browser_network(
    page: Any,
    server_url: str | None = None,
    titles: dict[str, list[str]] | None = None,
    include_resources: bool = False,
    auto_screenshot: bool = True,
) -> BrowserNetworkCapture:
    """
    Context manager to capture all browser network traffic.
    
    Usage:
        titles = {
            '/subscribe/': ['Subscribe Request', 'Payment Form'],
            '/flex/v2/tokens': ['Tokenize Card'],
            '/callback/': ['Callback'],
        }
        with trace.capture_browser_network(page, server_url=live_server.url, titles=titles):
            page.goto(url)
            page.click('#submit')
            # All requests/responses automatically traced with custom titles
    
    Args:
        page: Playwright page object
        server_url: URL of the test server (classified as 'Server' lane)
        titles: Dict mapping URL paths to list of titles (consumed in order)
        include_resources: Include images/css/fonts/js (default: False)
        auto_screenshot: Take screenshot after HTML page loads (default: True)
    
    Returns:
        Context manager that captures network traffic
    """
    return BrowserNetworkCapture(page, server_url, titles, include_resources, auto_screenshot)
