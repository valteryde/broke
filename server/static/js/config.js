/**
 * Centralized configuration for ticket statuses and priorities.
 * This file should be loaded before other JS files that depend on it.
 */

// Ticket Status Configuration
// Used by: lists.js, ticket.js
const StatusConfig = {
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
const StatusOrder = ['backlog', 'todo', 'in-progress', 'in-review', 'done', 'closed', 'duplicate'];

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
