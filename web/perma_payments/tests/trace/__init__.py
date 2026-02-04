"""
Integration test tracing utility - Sequence Diagram Generator.

This module creates visual sequence diagrams from test execution, showing the flow
of data between Browser, Server, external APIs, and Database.

=============================================================================
TRACING PHILOSOPHY: EVIDENCE, NOT CLAIMS
=============================================================================

Every trace entry should provide EVIDENCE that something happened, not just
assert that it did. This is a test audit trail.

GOOD (evidence):
    trace.screenshot(page, title='Payment form with card filled')
    trace.log(from_lane='Server', to_lane='CyberSource', title='Create Token',
              data={'status': 201, 'response': {...}})
    trace.db(subscription_agreement, title='After payment')

BAD (claims without evidence):
    trace.log(lane='Browser', title='User filled in card number')  # How do we know?
    trace.log(lane='Server', title='Validated the token')  # Where's the proof?

=============================================================================
TRACING IN PRODUCTION CODE: KEEP IT CHEAP
=============================================================================

Trace calls exist in production code (e.g., providers) but are disabled outside
of tests. They should be effectively NO-OP when disabled:

GOOD (cheap when disabled):
    trace.network_response(from_lane='CyberSource', to_lane='Server',
                           status=status, body=response_dict)
    trace.db(subscription_agreement)

BAD (does work even when tracing is disabled):
    trace.log(lane='Server', data={
        'computed': expensive_function(),
        'formatted': json.dumps(build_summary(data)),
    })

=============================================================================
API QUICK REFERENCE
=============================================================================

    # Setup/teardown (call from pytest fixture)
    trace.setup('/path/to/output.jsonl')
    trace.teardown()
    trace.report()  # updates manifest and installs viewer

    # Core logging
    trace.log(title='...', lane='Browser', data={...})
    trace.log(title='...', from_lane='Server', to_lane='CyberSource', data={...})

    # Helpers
    trace.screenshot(page, title='After filling form')
    trace.db(model_instance, title='SubscriptionAgreement created')
    trace.section('Payment Processing')

    # Network
    trace.network_request(from_lane, to_lane, method='POST', url='...')
    trace.network_response(from_lane, to_lane, status=200, body={...})
    
    # Browser network capture
    with trace.capture_browser_network(page, server_url='...'):
        page.goto(url)
"""

# Core API
from .core import (
    setup,
    teardown,
    register_page,
    capture_failure,
    log,
    screenshot,
    db,
    section,
)

# Network capture
from .network import (
    network_request,
    network_response,
    capture_browser_network,
    BrowserNetworkCapture,
)

# Report generation
from .report import generate_report

# State access (for advanced use cases)
from .state import (
    is_enabled,
    get_output_path,
    get_lanes,
)

__all__ = [
    # Core
    'setup',
    'teardown',
    'register_page',
    'capture_failure',
    'log',
    'screenshot',
    'db',
    'section',
    # Network
    'network_request',
    'network_response',
    'capture_browser_network',
    'BrowserNetworkCapture',
    # Report
    'report',
    'generate_report',
    'generate_manifest',
    'install_viewer',
    'generate_html',
    # State
    'is_enabled',
    'get_output_path',
    'get_lanes',
]


# =============================================================================
# CLI Support
# =============================================================================

def main():
    """Command-line interface for trace module."""
    from pathlib import Path
    
    traces_dir = Path(__file__).parent.parent / 'traces'
    path = generate_report(traces_dir)
    print(f"Generated report: {path}")


if __name__ == '__main__':
    main()
