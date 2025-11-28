/**
 * Error Detail Page JavaScript
 * Handles stacktrace expansion, syntax highlighting, and time formatting
 */

document.addEventListener('DOMContentLoaded', () => {
    // Format all timestamps
    formatTimestamps();
    
    // Auto-expand first in-app frame
    const firstInAppFrame = document.querySelector('.stacktrace-frame.in-app');
    if (firstInAppFrame) {
        firstInAppFrame.setAttribute('data-expanded', 'true');
        setTimeout(() => highlightFrameCode(firstInAppFrame), 0);
    }
});

/**
 * Highlight code in a frame using Highlight.js with custom line numbers
 */
function highlightFrameCode(frame) {
    const codeBlock = frame.querySelector('pre.frame-code code');
    
    if (!codeBlock || codeBlock.classList.contains('hljs-highlighted')) {
        return;
    }
    
    codeBlock.classList.add('hljs-highlighted');
    
    // Get line info from frame attributes
    const startLine = parseInt(frame.getAttribute('data-start-line'), 10) || 1;
    const errorLineIndex = parseInt(frame.getAttribute('data-error-line'), 10) || 1;
    
    // Get the original code and split into lines
    const originalCode = codeBlock.textContent;
    const lines = originalCode.split('\n');
    
    // Remove trailing empty line if exists
    if (lines.length > 0 && lines[lines.length - 1] === '') {
        lines.pop();
    }
    
    // Highlight the code first
    if (typeof hljs !== 'undefined') {
        hljs.highlightElement(codeBlock);
    }
    
    // Now wrap each line with line numbers
    const highlightedCode = codeBlock.innerHTML;
    const highlightedLines = splitHighlightedCode(highlightedCode);
    
    // Build the new HTML with line numbers and error highlighting
    let html = '<table class="code-lines"><tbody>';
    
    for (let i = 0; i < highlightedLines.length; i++) {
        const lineNum = startLine + i;
        const isErrorLine = (i + 1) === errorLineIndex;
        const lineClass = isErrorLine ? 'code-line error-line' : 'code-line';
        
        html += `<tr class="${lineClass}">`;
        html += `<td class="line-number">${lineNum}</td>`;
        html += `<td class="line-content">${highlightedLines[i] || '&nbsp;'}</td>`;
        html += '</tr>';
    }
    
    html += '</tbody></table>';
    
    // Replace the code content
    codeBlock.innerHTML = html;
}

/**
 * Split highlighted HTML code into lines while preserving spans
 */
function splitHighlightedCode(html) {
    const lines = [];
    let currentLine = '';
    let openSpans = [];
    
    // Process character by character with tag awareness
    let i = 0;
    while (i < html.length) {
        if (html[i] === '<') {
            // Find the end of the tag
            const tagEnd = html.indexOf('>', i);
            if (tagEnd === -1) break;
            
            const tag = html.substring(i, tagEnd + 1);
            
            if (tag.startsWith('</span')) {
                // Closing span
                currentLine += tag;
                openSpans.pop();
            } else if (tag.startsWith('<span')) {
                // Opening span - save the full tag
                currentLine += tag;
                openSpans.push(tag);
            } else {
                // Other tag
                currentLine += tag;
            }
            
            i = tagEnd + 1;
        } else if (html[i] === '\n') {
            // Newline - close open spans, save line, reopen spans
            for (let j = openSpans.length - 1; j >= 0; j--) {
                currentLine += '</span>';
            }
            lines.push(currentLine);
            currentLine = '';
            for (let j = 0; j < openSpans.length; j++) {
                currentLine += openSpans[j];
            }
            i++;
        } else {
            currentLine += html[i];
            i++;
        }
    }
    
    // Don't forget the last line
    if (currentLine) {
        lines.push(currentLine);
    }
    
    return lines;
}

/**
 * Toggle a single stacktrace frame
 */
function toggleFrame(headerElement) {
    const frame = headerElement.closest('.stacktrace-frame');
    const isExpanded = frame.getAttribute('data-expanded') === 'true';
    frame.setAttribute('data-expanded', !isExpanded);
    
    // Highlight code when expanding
    if (!isExpanded) {
        setTimeout(() => highlightFrameCode(frame), 0);
    }
}

/**
 * Toggle all stacktrace frames
 */
function toggleAllFrames() {
    const frames = document.querySelectorAll('.stacktrace-frame');
    const allExpanded = Array.from(frames).every(f => f.getAttribute('data-expanded') === 'true');
    
    frames.forEach(frame => {
        frame.setAttribute('data-expanded', !allExpanded);
        if (!allExpanded) {
            setTimeout(() => highlightFrameCode(frame), 0);
        }
    });
    
    // Update button text
    const btn = document.querySelector('.btn-expand-all');
    if (btn) {
        if (allExpanded) {
            btn.innerHTML = '<i class="ph ph-arrows-out-simple"></i> Expand All';
        } else {
            btn.innerHTML = '<i class="ph ph-arrows-in-simple"></i> Collapse All';
        }
    }
}

/**
 * Update error status via API
 */
async function updateStatus(newStatus) {
    if (!errorData || !errorData.id) {
        console.error('Error data not available');
        return;
    }
    
    try {
        const response = await fetch(`/api/errors/${errorData.id}/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: newStatus })
        });
        
        if (response.ok) {
            // Update UI
            const buttons = document.querySelectorAll('.action-btn');
            buttons.forEach(btn => btn.classList.remove('active'));
            
            const activeBtn = document.querySelector(`.action-btn[onclick="updateStatus('${newStatus}')"]`);
            if (activeBtn) {
                activeBtn.classList.add('active');
            }
            
            // Update status badge
            const badge = document.querySelector('.error-status-badge');
            if (badge) {
                badge.className = `error-status-badge status-${newStatus}`;
                const statusText = newStatus.charAt(0).toUpperCase() + newStatus.slice(1);
                let icon = 'warning-circle';
                if (newStatus === 'resolved') icon = 'check-circle';
                if (newStatus === 'ignored') icon = 'eye-slash';
                badge.innerHTML = `<i class="ph ph-${icon}"></i> ${statusText}`;
            }
            
            errorData.status = newStatus;
        } else {
            console.error('Failed to update status');
            alert('Failed to update status. Please try again.');
        }
    } catch (error) {
        console.error('Error updating status:', error);
        alert('Failed to update status. Please try again.');
    }
}

/**
 * Format all timestamps on the page
 */
function formatTimestamps() {
    const elements = document.querySelectorAll('[data-timestamp]');
    
    elements.forEach(el => {
        const timestamp = parseInt(el.getAttribute('data-timestamp'), 10);
        if (isNaN(timestamp)) return;
        
        const date = new Date(timestamp * 1000);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        let formatted;
        
        if (diffMins < 1) {
            formatted = 'Just now';
        } else if (diffMins < 60) {
            formatted = `${diffMins}m ago`;
        } else if (diffHours < 24) {
            formatted = `${diffHours}h ago`;
        } else if (diffDays < 7) {
            formatted = `${diffDays}d ago`;
        } else {
            formatted = date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
            });
        }
        
        el.textContent = formatted;
        el.title = date.toLocaleString();
    });
}

/**
 * Copy text to clipboard
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Could show a toast notification here
        console.log('Copied to clipboard');
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}
