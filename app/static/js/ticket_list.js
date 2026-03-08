/**
 * Ticket-specific configuration for the generic List component.
 * Defines filters, groups, item rendering, and quick actions.
 * Depends on: config.js (StatusConfig, PriorityConfig, etc.)
 */

const TICKET_LIST_STATE_KEY = 'pref_ticket_list_state_v1';

function isTriageContext() {
    return (window.ticketPageContext || 'tickets') === 'triage';
}

function getStatusKeysForPage() {
    if (isTriageContext()) {
        return ['triage'];
    }
    return StatusOrder.filter((key) => key !== 'triage');
}

function getStatusEntriesForPage() {
    return getStatusKeysForPage().map((key) => [key, StatusConfig[key]]).filter(([, value]) => Boolean(value));
}

function loadTicketListState() {
    try {
        const raw = localStorage.getItem(TICKET_LIST_STATE_KEY);
        if (!raw) {
            return { groupBy: 'status', filters: {} };
        }

        const parsed = JSON.parse(raw);
        const state = {
            groupBy: parsed.groupBy || 'status',
            filters: {}
        };

        const savedFilters = parsed.filters || {};
        Object.keys(savedFilters).forEach(filterType => {
            if (filterType === 'search') {
                return;
            }

            if (!Object.prototype.hasOwnProperty.call(TicketListConfig.filters, filterType)) {
                return;
            }

            const filterValue = savedFilters[filterType];
            if (filterValue === null || filterValue === undefined || filterValue === '') {
                return;
            }

            const filterConfig = TicketListConfig.filters[filterType];
            if (filterConfig.getValueFromOption && typeof filterValue === 'string') {
                const mappedValue = filterConfig.getValueFromOption(filterValue);
                mappedValue.optionValue = filterValue;
                mappedValue.optionLabel = filterValue;
                state.filters[filterType] = mappedValue;
                return;
            }

            state.filters[filterType] = filterValue;
        });

        return state;
    } catch (error) {
        console.warn('Failed to load ticket list state', error);
        return { groupBy: 'status', filters: {} };
    }
}

function saveTicketListState(state) {
    try {
        const serializedFilters = {};
        Object.keys(state.filters || {}).forEach(filterType => {
            if (filterType === 'search') {
                return;
            }

            const value = state.filters[filterType];
            if (value === null || value === undefined || value === '') {
                return;
            }

            if (Array.isArray(value) && value.length === 0) {
                return;
            }

            if (typeof value === 'object' && value.optionValue) {
                serializedFilters[filterType] = value.optionValue;
                return;
            }

            serializedFilters[filterType] = value;
        });

        localStorage.setItem(TICKET_LIST_STATE_KEY, JSON.stringify({
            groupBy: state.groupBy || 'status',
            filters: serializedFilters
        }));
    } catch (error) {
        console.warn('Failed to save ticket list state', error);
    }
}

const TicketListConfig = {
    // Filter definitions
    filters: {
        search: {
            placeholder: 'Search tickets...',
            filter: (element, value) => {
                if (!value) return true;
                const searchText = `${element.id} ${element.title} ${element.description}`.toLowerCase();
                return searchText.includes(value.toLowerCase());
            }
        },
        status: {
            label: 'Status',
            icon: 'ph-circle-half',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                return values.includes(element.status);
            },
            getOptions: () => getStatusEntriesForPage().map(([value, config]) => ({
                value,
                label: config.label,
                icon: config.icon
            }))
        },
        labels: {
            label: 'Labels',
            icon: 'ph-tag',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                const elementLabels = element.labels.map(l => l.text);
                return values.every(v => elementLabels.includes(v));
            },
            getOptions: (listInstance) => listInstance.extractLabels().map(l => ({
                value: l.text,
                label: l.text,
                icon: 'ph-fill ph-circle',
                colorClass: `filter-color-${l.color}`
            }))
        },
        assignees: {
            label: 'Assignees',
            icon: 'ph-users',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                return values.every(v => element.assignees.includes(v));
            },
            getOptions: (listInstance) => listInstance.extractAssignees().map(a => ({ value: a, label: a }))
        },
        urgency: {
            label: 'Urgency',
            icon: 'ph-warning',
            filter: (element, values) => {
                if (!values || values.length === 0) return true;
                return values.includes(element.urgency);
            },
            getOptions: () => [
                { value: 'urgent', label: 'Urgent', icon: 'ph-warning' },
                { value: 'high', label: 'High', icon: 'ph-cell-signal-high' },
                { value: 'medium', label: 'Medium', icon: 'ph-cell-signal-medium' },
                { value: 'low', label: 'Low', icon: 'ph-cell-signal-low' }
            ]
        },
        dateRange: {
            label: 'Date Range',
            icon: 'ph-calendar',
            filter: (element, value) => {
                if (!value || (!value.from && !value.to)) return true;
                const elementDate = element.createdAt ? new Date(element.createdAt) : null;
                if (!elementDate) return false;
                if (value.from && elementDate < value.from) return false;
                if (value.to && elementDate > value.to) return false;
                return true;
            },
            getOptions: () => [
                { value: 'last7', label: 'Last 7 days', icon: 'ph-clock-counter-clockwise' },
                { value: 'last14', label: 'Last 14 days', icon: 'ph-clock-counter-clockwise' },
                { value: 'last30', label: 'Last 30 days', icon: 'ph-clock-counter-clockwise' },
                { value: 'older7', label: 'Older than 7 days', icon: 'ph-clock-clockwise' },
                { value: 'older14', label: 'Older than 14 days', icon: 'ph-clock-clockwise' },
                { value: 'older30', label: 'Older than 30 days', icon: 'ph-clock-clockwise' }
            ],
            // Special handling for date range values
            getValueFromOption: (optionValue) => {
                const now = new Date();
                const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                switch (optionValue) {
                    case 'last7': return { from: new Date(today.getTime() - 7 * 86400000), to: null };
                    case 'last14': return { from: new Date(today.getTime() - 14 * 86400000), to: null };
                    case 'last30': return { from: new Date(today.getTime() - 30 * 86400000), to: null };
                    case 'older7': return { from: null, to: new Date(today.getTime() - 7 * 86400000) };
                    case 'older14': return { from: null, to: new Date(today.getTime() - 14 * 86400000) };
                    case 'older30': return { from: null, to: new Date(today.getTime() - 30 * 86400000) };
                    default: return { from: null, to: null };
                }
            }
        }
    },

    // Grouping definitions
    groups: {
        none: {
            label: 'None',
            icon: 'ph-list',
            getGroupKey: () => null,
            getGroupLabel: () => null
        },
        status: {
            label: 'Status',
            icon: 'ph-circle-half',
            getGroupKey: (element) => element.status || 'backlog',
            getGroupLabel: (key) => StatusConfig[key]?.label || key,
            order: getStatusKeysForPage()
        },
        urgency: {
            label: 'Urgency',
            icon: 'ph-warning',
            getGroupKey: (element) => element.urgency || 'none',
            getGroupLabel: (key) => PriorityConfig[key]?.label || key,
            order: PriorityOrder
        },
        assignees: {
            label: 'Assignee',
            icon: 'ph-users',
            getGroupKey: (element) => element.assignees && element.assignees.length > 0 ? element.assignees[0] : 'unassigned',
            getGroupLabel: (key) => key === 'unassigned' ? 'Unassigned' : key
        },
        labels: {
            label: 'Label',
            icon: 'ph-tag',
            getGroupKey: (element) => element.labels && element.labels.length > 0 ? element.labels[0].text : 'unlabeled',
            getGroupLabel: (key) => key === 'unlabeled' ? 'No labels' : key
        }
    },

    // Default grouping
    defaultGroupBy: 'status',

    // Item renderer
    renderer: (element) => {
        const inner = document.createElement('div');
        inner.className = 'list-element-inner';

        let dateString = '';
        if (element.createdAt) {
            var date = new Date(element.createdAt * 1000); // Expecting timestamp in seconds from tickets.jinja2
            // Check if it's already ms or Date object?
            // Existing lists.js did `new Date(element.createdAt * 1000)`
            // But verify if element.createdAt is string or number? tickets.jinja2 passes `{{ ticket.created_at }}` which is usually python timestamp (float/int).
            // Tickets.jinja2: `createdAt: '{{ ticket.created_at }}'` -> String?
            // Wait, tickets.jinja2 passes it as a string literal. `new Date('1234')` is invalid.
            // Ah, tickets.jinja2 `createdAt: '{{ ticket.created_at }}',`
            // If it's a unix timestamp string, `new Date(str * 1000)` works because of type coercion.
            dateString = date.toLocaleDateString();
        }

        // Extract text content safely from HTML description
        const parser = new DOMParser();
        const htmlDoc = parser.parseFromString(element.description || '', 'text/html');

        // Get status config if available
        const statusConfig = element.status ? StatusConfig[element.status] : null;
        const statusHtml = statusConfig
            ? `<span class="list-status" style="--status-color: ${statusConfig.color}" title="${statusConfig.label}">
                <i class="ph ${statusConfig.icon}"></i>
               </span>`
            : '';

        inner.innerHTML = `
            <i class="ph ${element.icon} list-element-icon"></i>
            <span class="list-element-id">${element.id}</span>
            ${statusHtml}
            <span class="list-element-text">
                <h3>${element.title}</h3>
                <p class="list-element-description">${(htmlDoc.body.textContent || "")}</p>
            </span>
            <span class="list-labels">
                ${(element.labels || []).map(label => `<span class="list-label"> <span class="list-label-circle" style="background-color: ${label.color}"></span> ${label.text}  </span>`).join('')}
            </span>
            <span class="list-assignees">
                ${(element.assignees || []).map(assignee => `<span class="list-assignee"> <i class="ph ph-user"></i>  ${assignee}</span>`).join('')}
            </span>
        `;

        if (isTriageContext() && typeof window.openSendTicketModal === 'function') {
            const sendButton = document.createElement('button');
            sendButton.type = 'button';
            sendButton.className = 'list-send-ticket-btn';
            sendButton.innerHTML = '<i class="ph ph-paper-plane-tilt"></i> Send';
            sendButton.addEventListener('click', (event) => {
                event.stopPropagation();
                window.openSendTicketModal(element.id);
            });
            inner.appendChild(sendButton);
        }

        return inner;
    },

    // Quick actions (shortcuts)
    quickActions: {
        's': {
            name: 'Change Status',
            handler: (listInstance, item) => {
                new ListModal({
                    title: 'Set Status',
                    items: getStatusEntriesForPage().map(([, s]) => ({
                        label: s.label,
                        value: s.value,
                        icon: s.icon,
                        colorClass: `status-${s.value}`,
                        selected: item.status === s.value
                    })),
                    onSelect: (selected) => listInstance.handleUpdate(item, 'status', selected.value)
                }).show();
            }
        },
        'p': {
            name: 'Change Priority',
            handler: (listInstance, item) => {
                new ListModal({
                    title: 'Set Priority',
                    items: Object.entries(PriorityConfig).map(([key, conf]) => ({
                        label: conf.label,
                        value: key,
                        icon: conf.icon,
                        selected: item.urgency === key
                    })),
                    onSelect: (selected) => listInstance.handleUpdate(item, 'priority', selected.value)
                }).show();
            }
        },
        'a': {
            name: 'Change Assignees',
            handler: (listInstance, item) => {
                if (typeof window.availableUsers !== 'undefined') {
                    new ListModal({
                        title: 'Assign Member',
                        items: window.availableUsers.map(u => ({
                            label: u.username,
                            value: u.username,
                            avatar: `<svg width="16" height="16" data-jdenticon-value="${u.username}"></svg>`,
                            selected: item.assignees.includes(u.username)
                        })),
                        onSelect: (selected) => listInstance.handleUpdate(item, 'assignees', selected.value, true),
                        closeOnSelect: false
                    }).show();
                } else {
                    console.warn('availableUsers not defined');
                }
            }
        },
        'l': {
            name: 'Change Labels',
            handler: (listInstance, item) => {
                if (typeof window.availableLabels !== 'undefined') {
                    new ListModal({
                        title: 'Add Label',
                        items: window.availableLabels.map(l => ({
                            label: l.name,
                            value: l,
                            avatar: '<i class="ph-fill ph-circle" style="color: ' + l.color + '"></i>',
                            selected: item.labels.some(lbl => lbl.text === l.name)
                        })),
                        onSelect: (selected) => listInstance.handleUpdate(item, 'labels', selected.value, true),
                        closeOnSelect: false
                    }).show();
                } else {
                    console.warn('availableLabels not defined');
                }
            }
        }
    }
};
