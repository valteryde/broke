/**
 * Error-specific configuration for the generic List component.
 * Triage-focused: attention groups, urgency bands, importance sort.
 */

const ERROR_SPIKE_MIN_OCCURRENCES = 5;
const ERROR_NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
const ERROR_RECENT_WINDOW_MS = 24 * 60 * 60 * 1000;

function errorEventCount(element) {
    return Number(element.eventCount) || 0;
}

function errorRecentCount(element) {
    return Number(element.recentCount) || 0;
}

function errorLastSeenMs(element) {
    if (element.lastSeen) {
        return Number(element.lastSeen) * 1000;
    }
    return Number(element.createdAt) || 0;
}

function errorFirstSeenMs(element) {
    if (element.firstSeen) {
        return Number(element.firstSeen) * 1000;
    }
    return errorLastSeenMs(element);
}

function errorIsNew(element) {
    const firstSeen = errorFirstSeenMs(element);
    if (!firstSeen) return false;
    return Date.now() - firstSeen <= ERROR_NEW_WINDOW_MS;
}

function errorIsSpike(element) {
    return errorRecentCount(element) >= ERROR_SPIKE_MIN_OCCURRENCES;
}

function errorIsRecent(element) {
    const lastSeen = errorLastSeenMs(element);
    if (!lastSeen) return false;
    return Date.now() - lastSeen <= ERROR_RECENT_WINDOW_MS;
}

/**
 * Urgency band for unresolved groups. Resolved/ignored are always cold.
 */
function errorUrgencyBand(element) {
    if (element.status !== 'unresolved') {
        return 'cold';
    }

    const count = errorEventCount(element);
    const isNew = errorIsNew(element);

    if (errorIsSpike(element) || count >= 50 || (isNew && count >= 10)) {
        return 'hot';
    }
    if (count >= 10 || (count >= 3 && errorIsRecent(element))) {
        return 'warm';
    }
    return 'cold';
}

function errorAttentionKey(element) {
    if (element.status === 'resolved' || element.status === 'ignored') {
        return 'parked';
    }
    const band = errorUrgencyBand(element);
    if (band === 'hot') return 'needs_attention';
    if (band === 'warm') return 'monitor';
    return 'quiet';
}

function errorImportanceScore(element) {
    const recent = errorRecentCount(element);
    const count = errorEventCount(element);
    const newBonus = errorIsNew(element) ? 50 : 0;
    return recent * 100 + count * 10 + newBonus;
}

function errorFormatRelativeTime(ms) {
    if (!ms) return '';
    const date = new Date(ms);
    const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)}d ago`;
    return date.toLocaleDateString();
}

function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const ErrorListConfig = {
    filters: {
        search: {
            placeholder: 'Search errors...',
            filter: (element, value) => {
                if (!value) return true;
                const searchText = `${element.id} ${element.title} ${element.description} ${element.culprit || ''} ${element.partName || ''}`.toLowerCase();
                return searchText.includes(value.toLowerCase());
            }
        },
        part: {
            label: 'Part',
            icon: 'ph-puzzle-piece',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                if (element.partId == null) return values.includes('none');
                return values.includes(String(element.partId));
            },
            getOptions: (listInstance) => {
                const items = Array.isArray(listInstance?.elements) ? listInstance.elements : [];
                const byId = new Map();
                items.forEach((item) => {
                    if (item.partId == null) return;
                    const key = String(item.partId);
                    if (!byId.has(key)) {
                        byId.set(key, item.partName || `Part ${key}`);
                    }
                });
                const options = Array.from(byId.entries())
                    .sort((a, b) => a[1].localeCompare(b[1]))
                    .map(([value, label]) => ({
                        value,
                        label,
                        icon: 'ph-puzzle-piece'
                    }));
                return options;
            }
        },
        status: {
            label: 'Status',
            icon: 'ph-warning',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                return values.includes(element.status);
            },
            getOptions: () => [
                { value: 'unresolved', label: 'Unresolved', icon: 'ph-warning-circle' },
                { value: 'resolved', label: 'Resolved', icon: 'ph-check-circle' },
                { value: 'ignored', label: 'Ignored', icon: 'ph-eye-slash' }
            ]
        },
        environment: {
            label: 'Environment',
            icon: 'ph-cloud',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                if (!element.environment) return values.includes('none');
                return values.includes(element.environment);
            },
            getOptions: () => [
                { value: 'production', label: 'Production', icon: 'ph-lightning' },
                { value: 'staging', label: 'Staging', icon: 'ph-wrench' },
                { value: 'development', label: 'Development', icon: 'ph-code' },
                { value: 'none', label: 'None', icon: 'ph-question' }
            ]
        },
        release: {
            label: 'Release',
            icon: 'ph-tag',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                if (!element.release) return values.includes('none');
                return values.includes(element.release);
            },
            getOptions: (listInstance) => {
                const items = Array.isArray(listInstance?.elements) ? listInstance.elements : [];
                const releases = new Set();
                items.forEach(item => {
                    if (item.release) {
                        releases.add(item.release);
                    }
                });
                const options = Array.from(releases).sort().map(release => ({
                    value: release,
                    label: release,
                    icon: 'ph-tag'
                }));
                options.push({ value: 'none', label: 'None', icon: 'ph-question' });
                return options;
            }
        }
    },

    groups: {
        attention: {
            label: 'Attention',
            icon: 'ph-fire',
            getGroupKey: (element) => errorAttentionKey(element),
            getGroupLabel: (key) => {
                const labels = {
                    needs_attention: 'Needs attention',
                    monitor: 'Monitor',
                    quiet: 'Quiet',
                    parked: 'Parked'
                };
                return labels[key] || key;
            },
            getGroupClass: (key) => `error-attention-group error-attention-${key}`,
            order: ['needs_attention', 'monitor', 'quiet', 'parked']
        },
        none: {
            label: 'None',
            icon: 'ph-list',
            getGroupKey: () => null,
            getGroupLabel: () => null
        },
        status: {
            label: 'Status',
            icon: 'ph-warning',
            getGroupKey: (element) => element.status || 'unresolved',
            getGroupLabel: (key) => key.charAt(0).toUpperCase() + key.slice(1),
            order: ['unresolved', 'resolved', 'ignored']
        }
    },

    defaultGroupBy: 'attention',
    defaultFilters: {
        status: ['unresolved']
    },

    sortFn: (a, b) => {
        const scoreDiff = errorImportanceScore(b) - errorImportanceScore(a);
        if (scoreDiff !== 0) return scoreDiff;
        return errorLastSeenMs(b) - errorLastSeenMs(a);
    },

    renderer: (element) => {
        const inner = document.createElement('div');
        const band = errorUrgencyBand(element);
        const count = errorEventCount(element);
        const isSpike = errorIsSpike(element);
        const isNew = errorIsNew(element);
        const lastSeenLabel = errorFormatRelativeTime(errorLastSeenMs(element));
        const culprit = (element.culprit || '').trim();
        const partName = (element.partName || '').trim();

        let statusIcon = 'ph-warning-circle';
        let statusColor = '#ef4444';
        if (element.status === 'resolved') {
            statusIcon = 'ph-check-circle';
            statusColor = '#22c55e';
        } else if (element.status === 'ignored') {
            statusIcon = 'ph-eye-slash';
            statusColor = '#9ca3af';
        }

        const badges = [];
        if (isSpike && element.status === 'unresolved') {
            badges.push('<span class="error-triage-badge error-triage-badge-spike">Spike</span>');
        }
        if (isNew && element.status === 'unresolved') {
            badges.push('<span class="error-triage-badge error-triage-badge-new">New</span>');
        }

        inner.className = 'list-element-inner error-list-row';
        inner.dataset.urgency = band;
        inner.dataset.status = element.status || 'unresolved';

        inner.innerHTML = `
            <span class="list-element-id">E-${escapeHtml(element.id)}</span>
            <span class="list-status" style="--status-color: ${statusColor}" title="${escapeHtml(element.status)}">
                <i class="ph ${statusIcon}"></i>
            </span>
            <span class="list-element-text error-list-text">
                <h3>${escapeHtml(element.title || 'Error')}</h3>
                ${partName ? `<p class="error-list-part">${escapeHtml(partName)}</p>` : ''}
                <p class="list-element-description">${escapeHtml(element.description || '')}</p>
                ${culprit ? `<p class="error-list-culprit">${escapeHtml(culprit)}</p>` : ''}
            </span>
            <span class="error-list-signals">
                ${badges.join('')}
                <span class="error-event-count" data-urgency="${band}" title="Event count">${count}</span>
                <span class="error-event-count-label">events</span>
            </span>
            <span class="error-list-meta">
                ${lastSeenLabel ? `<span class="error-last-seen"><i class="ph ph-clock"></i> ${escapeHtml(lastSeenLabel)}</span>` : ''}
            </span>
        `;

        return inner;
    },

    quickActions: {
        's': {
            name: 'Change Status',
            handler: (listInstance, item) => {
                new ListModal({
                    title: 'Set Status',
                    items: [
                        { value: 'unresolved', label: 'Unresolved', icon: 'ph-warning-circle', colorClass: 'status-duplicate' },
                        { value: 'resolved', label: 'Resolved', icon: 'ph-check-circle', colorClass: 'status-done' },
                        { value: 'ignored', label: 'Ignored', icon: 'ph-eye-slash', colorClass: 'status-closed' }
                    ].map(s => ({ ...s, selected: item.status === s.value })),
                    onSelect: (selected) => listInstance.handleUpdate(item, 'status', selected.value)
                }).show();
            }
        }
    }
};
