/**
 * Browser-visible path (prepends BROKE_APPLICATION_PREFIX via __BROKE_SCRIPT_ROOT__ from templates).
 */
function brokeAppUrl(path) {
    const root =
        typeof window !== "undefined" && typeof window.__BROKE_SCRIPT_ROOT__ === "string"
            ? window.__BROKE_SCRIPT_ROOT__
            : "";
    let p = path || "/";
    if (p.charAt(0) !== "/") {
        p = "/" + p;
    }
    return root + p;
}

if (typeof window !== "undefined") {
    window.brokeAppUrl = brokeAppUrl;
}

/**
 * Centralized configuration for ticket statuses and priorities.
 * This file should be loaded before other JS files that depend on it.
 */

// Ticket Status Configuration
// Used by: lists.js, ticket.js
const StatusConfig = {
    'intake': {
        value: 'intake',
        label: 'Intake',
        icon: 'ph-tray',
        color: '#0ea5e9',
        colorClass: 'status-triage'
    },
    // Legacy alias for existing records that still use 'triage'.
    'triage': {
        value: 'triage',
        label: 'Intake',
        icon: 'ph-tray',
        color: '#0ea5e9',
        colorClass: 'status-triage'
    },
    'backlog': {
        value: 'backlog',
        label: 'Backlog',
        icon: 'ph-circle-dashed',
        color: '#6b7280',
        colorClass: 'status-backlog'
    },
    'todo': {
        value: 'todo',
        label: 'Todo',
        icon: 'ph-circle',
        color: '#8b5cf6',
        colorClass: 'status-todo'
    },
    'in-progress': {
        value: 'in-progress',
        label: 'In Progress',
        icon: 'ph-circle-half',
        color: '#3b82f6',
        colorClass: 'status-in-progress'
    },
    'in-review': {
        value: 'in-review',
        label: 'In Review',
        icon: 'ph-circle-notch',
        color: '#f59e0b',
        colorClass: 'status-in-review'
    },
    'done': {
        value: 'done',
        label: 'Done',
        icon: 'ph-check-circle',
        color: '#22c55e',
        colorClass: 'status-done'
    },
    'closed': {
        value: 'closed',
        label: 'Closed',
        icon: 'ph-x-circle',
        color: '#9ca3af',
        colorClass: 'status-closed'
    },
    'duplicate': {
        value: 'duplicate',
        label: 'Duplicate',
        icon: 'ph-copy',
        color: '#ef4444',
        colorClass: 'status-duplicate'
    }
};

// Order of statuses for sorting and grouping
const StatusOrder = ['intake', 'backlog', 'todo', 'in-progress', 'in-review', 'done', 'closed', 'duplicate'];

// Helper to get statuses as array (for dropdowns)
const StatusList = StatusOrder.map(key => StatusConfig[key]);

// Priority Configuration
// Used by: ticket.js
const PriorityConfig = {
    'urgent': {
        value: 'urgent',
        label: 'Urgent',
        icon: 'ph-warning',
        color: '#ef4444',
        colorClass: 'priority-urgent'
    },
    'high': {
        value: 'high',
        label: 'High',
        icon: 'ph-cell-signal-high',
        color: '#f97316',
        colorClass: 'priority-high'
    },
    'medium': {
        value: 'medium',
        label: 'Medium',
        icon: 'ph-cell-signal-medium',
        color: '#eab308',
        colorClass: 'priority-medium'
    },
    'low': {
        value: 'low',
        label: 'Low',
        icon: 'ph-cell-signal-low',
        color: '#22c55e',
        colorClass: 'priority-low'
    },
    'none': {
        value: 'none',
        label: 'No priority',
        icon: 'ph-cell-signal-none',
        color: '#6b7280',
        colorClass: 'priority-none'
    }
};

// Order of priorities for sorting
const PriorityOrder = ['urgent', 'high', 'medium', 'low', 'none'];

// Helper to get priorities as array (for dropdowns)
const PriorityList = PriorityOrder.map(key => PriorityConfig[key]);

const ESTIMATE_MINUTES_PER_HOUR = 60;
const ESTIMATE_MINUTES_PER_DAY = 8 * ESTIMATE_MINUTES_PER_HOUR;
const ESTIMATE_MINUTES_PER_WEEK = 5 * ESTIMATE_MINUTES_PER_DAY;
const ESTIMATE_MAX_MINUTES = 4 * ESTIMATE_MINUTES_PER_WEEK;

const EstimatePresets = [
    { minutes: 15, label: '15m' },
    { minutes: 30, label: '30m' },
    { minutes: 60, label: '1h' },
    { minutes: 120, label: '2h' },
    { minutes: 240, label: '4h' },
    { minutes: 480, label: '1d' },
    { minutes: 960, label: '2d' },
    { minutes: 1440, label: '3d' },
    { minutes: 2400, label: '1w' }
];

function formatEstimateMinutes(minutes) {
    if (minutes == null || minutes === '') return '';
    let remaining = Math.round(Number(minutes));
    if (!Number.isFinite(remaining) || remaining <= 0) return '';

    const weeks = Math.floor(remaining / ESTIMATE_MINUTES_PER_WEEK);
    remaining -= weeks * ESTIMATE_MINUTES_PER_WEEK;
    const days = Math.floor(remaining / ESTIMATE_MINUTES_PER_DAY);
    remaining -= days * ESTIMATE_MINUTES_PER_DAY;
    const hours = Math.floor(remaining / ESTIMATE_MINUTES_PER_HOUR);
    remaining -= hours * ESTIMATE_MINUTES_PER_HOUR;

    const parts = [];
    if (weeks) parts.push(weeks + 'w');
    if (days) parts.push(days + 'd');
    if (hours) parts.push(hours + 'h');
    if (remaining) parts.push(remaining + 'm');
    return parts.join(' ');
}

function parseEstimateInput(raw) {
    if (raw == null) return null;
    const text = String(raw).trim().toLowerCase();
    if (!text || ['none', 'no', 'clear', '-', '0', 'null', 'no estimate'].includes(text)) {
        return null;
    }

    const compact = text.replace(/[,+]|and/g, ' ').replace(/\s+/g, ' ').trim();
    const tokenRe = /(\d+(?:\.\d+)?)\s*(w(?:eeks?)?|d(?:ays?)?|h(?:ours?|rs?)?|m(?:ins?|inutes?)?)?/gi;
    let total = 0;
    let consumed = 0;
    let match;
    while ((match = tokenRe.exec(compact)) !== null) {
        const gap = compact.slice(consumed, match.index).trim();
        if (gap) {
            tokenRe.lastIndex = 0;
            return null;
        }
        consumed = match.index + match[0].length;
        const amount = parseFloat(match[1]);
        const unit = (match[2] || '').toLowerCase();
        if (!unit) {
            total += amount * ESTIMATE_MINUTES_PER_HOUR;
        } else if (unit.startsWith('w')) {
            total += amount * ESTIMATE_MINUTES_PER_WEEK;
        } else if (unit.startsWith('d')) {
            total += amount * ESTIMATE_MINUTES_PER_DAY;
        } else if (unit.startsWith('h')) {
            total += amount * ESTIMATE_MINUTES_PER_HOUR;
        } else {
            total += amount;
        }
    }
    if (!consumed || compact.slice(consumed).trim()) return null;
    const minutes = Math.round(total);
    if (minutes <= 0 || minutes > ESTIMATE_MAX_MINUTES) return null;
    return minutes;
}

if (typeof window !== 'undefined') {
    window.EstimatePresets = EstimatePresets;
    window.formatEstimateMinutes = formatEstimateMinutes;
    window.parseEstimateInput = parseEstimateInput;
}
