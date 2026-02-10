// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
    renderSidebar();
    
    // Check for trace in URL hash
    if (window.location.hash) {
        loadTrace(window.location.hash.slice(1));
    }
});

function renderSidebar() {
    const content = document.querySelector('.sidebar-content');
    const tests = MANIFEST.tests;
    
    if (Object.keys(tests).length === 0) {
        content.innerHTML = '<div class="empty-state"><p>No traces found</p></div>';
        return;
    }
    
    let html = '';
    for (const [testName, variants] of Object.entries(tests).sort()) {
        const displayName = formatTestName(testName);
        const groupId = 'group-' + testName.replace(/[^a-z0-9]/gi, '-');
        
        html += '<div class="test-group">';
        html += '<div class="test-name" onclick="toggleGroup(\'' + groupId + '\')">' + escapeHtml(displayName) + '</div>';
        html += '<div class="test-variants" id="' + groupId + '">';
        
        for (const variant of variants.sort((a, b) => a.params.localeCompare(b.params))) {
            const failureClass = variant.has_failure ? 'has-failure' : '';
            html += '<a class="variant-link ' + failureClass + '" data-trace="' + variant.filename + '" onclick="loadTrace(\'' + variant.filename + '\')">' + escapeHtml(variant.params || variant.filename) + '</a>';
        }
        
        html += '</div></div>';
    }
    
    content.innerHTML = html;
}

function toggleGroup(groupId) {
    const group = document.getElementById(groupId);
    const name = group.previousElementSibling;
    group.classList.toggle('show');
    name.classList.toggle('expanded');
}

function formatTestName(name) {
    if (name.startsWith('test_')) name = name.slice(5);
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function loadTrace(filename) {
    // Update URL hash
    window.location.hash = filename;
    
    // Update sidebar selection
    document.querySelectorAll('.variant-link').forEach(el => {
        el.classList.toggle('active', el.dataset.trace === filename);
    });
    
    // Expand parent group
    const link = document.querySelector('.variant-link[data-trace="' + filename + '"]');
    if (link) {
        const variants = link.parentElement;
        const name = variants.previousElementSibling;
        variants.classList.add('show');
        name.classList.add('expanded');
    }
    
    // Update title
    document.querySelector('.trace-title').textContent = filename.replace('.jsonl', '').replace(/_/g, ' ');
    
    // Load trace from inlined data
    const entries = TRACES[filename];
    if (entries) {
        renderTrace(entries);
    } else {
        document.querySelector('.main-content').innerHTML = '<div class="empty-state"><p>Trace not found</p></div>';
    }
}

function renderTrace(entries) {
    const mainContent = document.querySelector('.main-content');
    
    // Collect lanes
    const lanes = [];
    for (const entry of entries) {
        if (entry.type === 'internal') {
            const lane = entry.lane;
            if (lane && lane !== 'Database' && !lanes.includes(lane)) lanes.push(lane);
        } else if (entry.type === 'network') {
            for (const lane of [entry.from_lane, entry.to_lane]) {
                if (lane && lane !== 'Database' && !lanes.includes(lane)) lanes.push(lane);
            }
        }
    }
    
    const numLanes = lanes.length || 1;
    const laneIndices = Object.fromEntries(lanes.map((lane, i) => [lane, i]));
    
    // Collect sections for TOC
    const sections = entries
        .filter(e => e.type === 'section')
        .map((e, i) => ({ title: e.title || 'Untitled', id: 'section-' + i }));
    
    let html = '';
    
    // Table of contents
    if (sections.length > 0) {
        html += '<nav class="toc"><div class="toc-title">Contents</div><ul class="toc-list">';
        for (const sec of sections) {
            html += '<li><a href="#' + sec.id + '">' + escapeHtml(sec.title) + '</a></li>';
        }
        html += '</ul></nav>';
    }
    
    // Lane headers
    html += '<div class="lane-headers" style="grid-template-columns: repeat(' + numLanes + ', var(--lane-width));">';
    for (const lane of lanes) {
        html += '<div class="lane-header">' + escapeHtml(lane) + '</div>';
    }
    html += '</div>';
    
    // Sequence diagram
    html += '<div class="sequence">';
    
    let entryId = 0;
    let sectionIdx = 0;
    
    for (const entry of entries) {
        if (entry.type === 'section') {
            const sectionId = 'section-' + sectionIdx++;
            html += '<div class="section-header" id="' + sectionId + '">' + escapeHtml(entry.title || 'Untitled') + '</div>';
            continue;
        }
        
        if (entry.type === 'setup' || entry.type === 'teardown') continue;
        
        if (entry.type === 'internal') {
            entryId++;
            let lane = entry.lane;
            if (lane === 'Database') lane = 'Server';
            const laneIdx = laneIndices[lane] || 0;
            
            html += '<div class="entry-row" style="grid-template-columns: repeat(' + numLanes + ', var(--lane-width));">';
            for (let i = 0; i < laneIdx; i++) html += '<div class="lane-placeholder"></div>';
            html += '<div class="box">' + renderBoxContent(entry, entryId) + '</div>';
            for (let i = laneIdx + 1; i < numLanes; i++) html += '<div class="lane-placeholder"></div>';
            html += '</div>';
        } else if (entry.type === 'network') {
            entryId++;
            let fromLane = entry.from_lane;
            let toLane = entry.to_lane;
            if (fromLane === 'Database') fromLane = 'Server';
            if (toLane === 'Database') toLane = 'Server';
            
            const fromIdx = laneIndices[fromLane] || 0;
            const toIdx = laneIndices[toLane] || 0;
            const leftIdx = Math.min(fromIdx, toIdx);
            const rightIdx = Math.max(fromIdx, toIdx);
            const span = rightIdx - leftIdx + 1;
            const isRight = toIdx > fromIdx;
            
            html += '<div class="entry-row" style="grid-template-columns: repeat(' + numLanes + ', var(--lane-width));">';
            for (let i = 0; i < leftIdx; i++) html += '<div class="lane-placeholder"></div>';
            html += '<div class="box" style="grid-column: span ' + span + ';">';
            html += '<div class="arrow-container"><div class="arrow-line ' + (isRight ? 'right' : 'left') + '"></div></div>';
            html += renderBoxContent(entry, entryId);
            html += '</div>';
            for (let i = rightIdx + 1; i < numLanes; i++) html += '<div class="lane-placeholder"></div>';
            html += '</div>';
        }
    }
    
    html += '</div>';
    mainContent.innerHTML = html;
}

function renderBoxContent(entry, entryId) {
    let html = '';
    const title = entry.title || 'Untitled';
    const isFailure = title.includes('TEST FAILED');
    
    html += '<div class="box-title ' + (isFailure ? 'failure' : '') + '">' + escapeHtml(title) + '</div>';
    
    // Explanation
    if (entry.explanation) {
        const firstLine = entry.explanation.split('\n')[0].slice(0, 80);
        const truncated = entry.explanation.length > firstLine.length ? firstLine + '...' : firstLine;
        html += '<div class="explanation-line" id="expl-line-' + entryId + '" onclick="toggleExplanation(' + entryId + ')">' + escapeHtml(truncated) + '</div>';
        html += '<div class="explanation-full" id="expl-full-' + entryId + '">' + escapeHtml(entry.explanation) + '</div>';
    }
    
    // Data table
    const data = entry.data || {};
    let screenshotSrc = null;
    const otherData = {};
    
    for (const [key, value] of Object.entries(data)) {
        if (value && typeof value === 'object' && value.__image_base64__) {
            screenshotSrc = 'data:image/png;base64,' + value.__image_base64__;
        } else {
            otherData[key] = value;
        }
    }
    
    if (Object.keys(otherData).length > 0) {
        html += '<table class="data-table">';
        for (const [key, value] of Object.entries(otherData)) {
            html += '<tr><td class="data-key">' + escapeHtml(key) + '</td><td class="data-value">' + renderValue(value) + '</td></tr>';
        }
        html += '</table>';
    }
    
    // Screenshot
    if (screenshotSrc) {
        html += '<div class="screenshot-container"><img class="screenshot-thumb" src="' + screenshotSrc + '" onclick="showLightbox(this.src)" alt="Screenshot" /></div>';
    }
    
    // Stack trace
    if (entry.stack_trace && entry.stack_trace.length > 0) {
        html += '<button class="stack-btn" onclick="showStackTrace(' + entryId + ')">stack trace</button>';
        html += '<div id="stack-data-' + entryId + '" style="display:none;">';
        for (const frame of entry.stack_trace) {
            const filename = frame.filename || '?';
            const lineno = frame.lineno || '?';
            const func = frame.function || '?';
            const code = frame.code || '';
            const shortFilename = filename.includes('/') ? filename.split('/').pop() : filename;
            const copyText = shortFilename + ':' + lineno;
            
            html += '<div class="stack-frame">';
            html += '<span class="stack-location">' + escapeHtml(shortFilename) + ':' + lineno + '</span>';
            html += ' in <span class="stack-function">' + escapeHtml(func) + '</span>';
            html += '<button class="copy-btn" onclick="copyToClipboard(\'' + escapeHtml(copyText) + '\', this)">copy</button>';
            if (code) html += '<div class="stack-code">' + escapeHtml(code) + '</div>';
            html += '</div>';
        }
        html += '</div>';
    }
    
    return html;
}

function renderValue(value) {
    if (value === null) return '<em>null</em>';
    if (value === undefined) return '<em>undefined</em>';
    
    // Status codes
    if (typeof value === 'number' && value >= 100 && value <= 599) {
        return '<span class="status-' + Math.floor(value / 100) + 'xx">' + value + '</span>';
    }
    
    // Objects/arrays
    if (typeof value === 'object') {
        try {
            const formatted = JSON.stringify(value, null, 2);
            return '<pre>' + escapeHtml(formatted) + '</pre>';
        } catch {
            return '<pre>' + escapeHtml(String(value)) + '</pre>';
        }
    }
    
    // Strings
    if (typeof value === 'string') {
        if (value.startsWith('{') || value.startsWith('[')) {
            try {
                const parsed = JSON.parse(value);
                const formatted = JSON.stringify(parsed, null, 2);
                return '<pre>' + escapeHtml(formatted) + '</pre>';
            } catch {}
        }
        if (value.includes('\n')) {
            return '<pre>' + escapeHtml(value) + '</pre>';
        }
        return escapeHtml(value);
    }
    
    return escapeHtml(String(value));
}

function escapeHtml(str) {
    if (typeof str !== 'string') str = String(str);
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function toggleExplanation(id) {
    const line = document.getElementById('expl-line-' + id);
    const full = document.getElementById('expl-full-' + id);
    if (line) line.classList.toggle('expanded');
    if (full) full.classList.toggle('show');
}

function showLightbox(src) {
    document.getElementById('lightbox-img').src = src;
    document.getElementById('lightbox').classList.add('show');
}

function closeLightbox() {
    document.getElementById('lightbox').classList.remove('show');
}

function showStackTrace(id) {
    const content = document.getElementById('stack-data-' + id);
    if (content) {
        document.getElementById('stack-modal-content').innerHTML = content.innerHTML;
        document.getElementById('stack-modal').classList.add('show');
    }
}

function closeStackModal() {
    document.getElementById('stack-modal').classList.remove('show');
}

function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const original = btn.textContent;
        btn.textContent = 'copied!';
        setTimeout(() => { btn.textContent = original; }, 1000);
    });
}

// Handle hash changes
window.addEventListener('hashchange', () => {
    if (window.location.hash) {
        loadTrace(window.location.hash.slice(1));
    }
});