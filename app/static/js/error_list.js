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
                // Dynamically generate release options from list data.
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

        const rowActions = `
            <span class="list-inline-actions" style="display:inline-flex;gap:0.35rem;align-items:center;">
                <button class="btn btn-secondary error-inline-action" data-error-id="${element.id}" data-status="resolved" title="Resolve" style="padding:0.15rem 0.4rem;font-size:0.75rem;">Resolve</button>
                <button class="btn btn-secondary error-inline-action" data-error-id="${element.id}" data-status="ignored" title="Ignore" style="padding:0.15rem 0.4rem;font-size:0.75rem;">Ignore</button>
                <button class="btn btn-secondary error-inline-action" data-error-id="${element.id}" data-status="unresolved" title="Reopen" style="padding:0.15rem 0.4rem;font-size:0.75rem;">Reopen</button>
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
            ${rowActions}
        `;

        inner.querySelectorAll('.error-inline-action').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
            });
        });
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
