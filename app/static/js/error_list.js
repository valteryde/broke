/**
 * Error-specific configuration for the generic List component.
 * Defines filters, groups, item rendering, and quick actions.
 */

const ErrorListConfig = {
    // Filter definitions
    filters: {
        search: {
            placeholder: 'Search errors...',
            filter: (element, value) => {
                if (!value) return true;
                const searchText = `${element.id} ${element.title} ${element.description}`.toLowerCase();
                return searchText.includes(value.toLowerCase());
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
            icon: 'ph-warning',
            getGroupKey: (element) => element.status || 'unresolved',
            getGroupLabel: (key) => key.charAt(0).toUpperCase() + key.slice(1),
            order: ['unresolved', 'resolved', 'ignored']
        }
    },

    // Default grouping
    defaultGroupBy: 'none',

    // Item renderer
    renderer: (element) => {
        const inner = document.createElement('div');
        inner.className = 'list-element-inner';

        // Format Date
        let dateString = '';
        if (element.createdAt) {
            // Expecting timestamp in milliseconds (part.jinja2 sends {{ error.last_seen }} * 1000)
            // or seconds if we want consistency?
            // part.jinja2: createdAt: {{ error.last_seen }} * 1000
            const date = new Date(element.createdAt);
            dateString = date.toLocaleDateString();
        }

        // Status visuals
        let statusIcon = 'ph-warning-circle';
        let statusColor = '#ef4444'; // red
        if (element.status === 'resolved') {
            statusIcon = 'ph-check-circle';
            statusColor = '#22c55e'; // green
        } else if (element.status === 'ignored') {
            statusIcon = 'ph-eye-slash';
            statusColor = '#9ca3af'; // gray
        }

        const statusHtml = `
            <span class="list-status" style="--status-color: ${statusColor}" title="${element.status}">
                <i class="ph ${statusIcon}"></i>
            </span>
        `;

        // Render logic similar to tickets but tailored for errors
        inner.innerHTML = `
            <i class="ph ${element.icon || 'ph-bug'} list-element-icon"></i>
            <span class="list-element-id">E-${element.id}</span>
            ${statusHtml}
            <span class="list-element-text">
                <h3>${element.title}</h3>
                <p class="list-element-description">${element.description || ''}</p>
            </span>
             
             <span class="list-labels">
                 <span class="list-label" title="Events count">
                    <span class="list-label-circle" style="background-color: #6b7280"></span> ${element.meta} 
                 </span>
                ${(element.labels || []).map(label => `<span class="list-label"> <span class="list-label-circle" style="background-color: ${label.color}"></span> ${label.text}  </span>`).join('')}
            </span>

            <span class="list-assignees">
                <span class="list-assignee"> <i class="ph ph-clock"></i>  ${dateString}</span>
            </span>
        `;
        return inner;
    },

    // Quick actions (shortcuts)
    quickActions: {
        's': {
            name: 'Change Status',
            handler: (listInstance, item) => {
                new ListModal({
                    title: 'Set Status',
                    items: [
                        { value: 'unresolved', label: 'Unresolved', icon: 'ph-warning-circle', colorClass: 'status-duplicate' }, // reusing existing CSS classes if possible, or generic
                        { value: 'resolved', label: 'Resolved', icon: 'ph-check-circle', colorClass: 'status-done' },
                        { value: 'ignored', label: 'Ignored', icon: 'ph-eye-slash', colorClass: 'status-closed' }
                    ].map(s => ({ ...s, selected: item.status === s.value })),
                    onSelect: (selected) => listInstance.handleUpdate(item, 'status', selected.value)
                }).show();
            }
        }
    }
};
