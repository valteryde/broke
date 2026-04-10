const TicketBoard = {
    statuses: [
        { key: 'intake', label: 'Intake' },
        { key: 'backlog', label: 'Backlog' },
        { key: 'todo', label: 'To Do' },
        { key: 'in-progress', label: 'In Progress' },
        { key: 'in-review', label: 'In Review' },
        { key: 'done', label: 'Done' }
    ],

    MAX_VISIBLE_TICKETS: 30,
    collapsedStatuses: JSON.parse(localStorage.getItem('board_collapsed_statuses') || '[]'),
    expandedColumns: new Set(), // Session-based 'Show all' state
    renderTimer: null,
    rerenderCb: null,

    getStatuses() {
        const page = window.ticketPageContext || 'tickets';
        if (page === 'triage' || page === 'intake') {
            return this.statuses;
        }
        return this.statuses.filter((status) => status.key !== 'intake');
    },

    saveCollapsed() {
        localStorage.setItem('board_collapsed_statuses', JSON.stringify(this.collapsedStatuses));
    },

    toggleCollapse(statusKey) {
        const index = this.collapsedStatuses.indexOf(statusKey);
        if (index > -1) {
            this.collapsedStatuses.splice(index, 1);
        } else {
            this.collapsedStatuses.push(statusKey);
        }
        this.saveCollapsed();
        if (this.rerenderCb) this.rerenderCb();
    },

    showAll(statusKey) {
        this.expandedColumns.add(statusKey);
        if (this.rerenderCb) this.rerenderCb();
    },

    init(containerId, tickets, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) {
            return;
        }

        const onMove = options.onMove || (async () => {});
        const onCardClick = options.onCardClick || (() => {});

        const statuses = this.getStatuses();

        const normalizedTickets = (tickets || [])
            .map((ticket) => ({
                ...ticket,
                status: ticket.status === 'triage' ? 'intake' : ticket.status
            }))
            .filter((ticket) => statuses.some((s) => s.key === ticket.status));

        let filterController = null;

        const applyFilters = (rows) => {
            if (filterController) {
                return filterController.filteredElements || rows;
            }
            return rows;
        };

        const render = () => {
            // Debounce the render call
            if (this.renderTimer) clearTimeout(this.renderTimer);
            this.renderTimer = setTimeout(() => this.doRender(container, normalizedTickets, statuses, applyFilters, onMove, onCardClick, render), 16);
        };

        this.rerenderCb = render;

        filterController = this.createFilterController(normalizedTickets, render);

        if (!filterController) {
            render();
        }
    },

    doRender(container, normalizedTickets, statuses, applyFilters, onMove, onCardClick, rerender) {
        const visibleTickets = applyFilters(normalizedTickets);
        const columnsHtml = statuses.map((status) => {
            const isCollapsed = this.collapsedStatuses.includes(status.key);
            const items = visibleTickets.filter((ticket) => ticket.status === status.key);

            let bodyHtml = '';
            let footerHtml = '';
            const statusClass = isCollapsed ? 'is-collapsed' : '';
            const collapseIcon = isCollapsed ? 'ph ph-caret-double-right' : 'ph ph-caret-double-left';

            if (!isCollapsed) {
                const limit = this.expandedColumns.has(status.key) ? this.MAX_VISIBLE_TICKETS : this.MAX_VISIBLE_TICKETS;
                // Wait, if expanded, we want items.length
                const actualLimit = this.expandedColumns.has(status.key) ? items.length : this.MAX_VISIBLE_TICKETS;
                const visibleItems = items.slice(0, actualLimit);
                const cards = visibleItems.map((ticket) => this.renderCard(ticket)).join('');
                bodyHtml = `<div class="ticket-board-column-body" data-drop-zone="${status.key}">${cards}</div>`;

                if (items.length > this.MAX_VISIBLE_TICKETS && !this.expandedColumns.has(status.key)) {
                    footerHtml = `
                        <div class="ticket-board-column-footer">
                            <button class="btn-show-all" onclick="TicketBoard.showAll('${status.key}')">
                                Show all ${items.length} tickets
                            </button>
                        </div>
                    `;
                }
            }

            return `
                <section class="ticket-board-column ${statusClass}" data-status="${status.key}">
                    <header class="ticket-board-column-header">
                        <button class="column-collapse-btn" onclick="TicketBoard.toggleCollapse('${status.key}')" title="${isCollapsed ? 'Expand' : 'Collapse'}">
                            <i class="${collapseIcon}"></i>
                        </button>
                        <h3>${status.label}</h3>
                        <span>${items.length}</span>
                    </header>
                    ${bodyHtml}
                    ${footerHtml}
                </section>
            `;
        }).join('');

        container.innerHTML = `<div class="ticket-board-grid">${columnsHtml}</div>`;
        this.renderAvatars(container);
        this.bindEvents(container, normalizedTickets, onMove, onCardClick, rerender);
    },

    createFilterController(tickets, onChange) {
        const filterHost = document.getElementById('ticket-board-filters');
        if (!filterHost || typeof List === 'undefined' || typeof TicketListConfig === 'undefined') {
            return null;
        }

        const listMountId = 'ticket-board-filter-controller';
        filterHost.innerHTML = `<div id="${listMountId}"></div>`;

        const filterController = new List(listMountId, {
            filters: {
                search: TicketListConfig.filters.search,
                status: TicketListConfig.filters.status,
                labels: TicketListConfig.filters.labels,
                assignees: TicketListConfig.filters.assignees,
                urgency: TicketListConfig.filters.urgency,
                workCycle: TicketListConfig.filters.workCycle,
            },
            groups: {},
            syncUrlState: false,
            renderer: () => {
                const node = document.createElement('div');
                node.style.display = 'none';
                return node;
            },
            onClearFilters: (list) => {
                list.clearAllFilters();
                const searchInput = filterHost.querySelector('.list-search-input');
                if (searchInput) {
                    searchInput.value = '';
                }
                if (window.showToast) {
                    window.showToast('Filters cleared', 'success');
                }
            },
            onClearFiltersLabel: 'Clear Filters',
            onStateChange: () => {
                onChange();
            },
        });

        filterController.container.style.display = 'none';
        filterController.addAll(tickets);
        return filterController;
    },

    renderCard(ticket) {
        const safeTitle = (ticket.title || '(Untitled)').replace(/"/g, '&quot;');
        const priorityKey = String(ticket.urgency || 'none');
        const priorityLabel = priorityKey === 'none' ? 'No priority' : priorityKey;
        const priorityClass = `ticket-priority-${priorityKey.replace(/[^a-z-]/g, '')}`;
        const assignees = Array.isArray(ticket.assignees) ? ticket.assignees : [];
        const assigneeHtml = assignees.slice(0, 3).map((username) => {
            const safeUsername = this.escapeHtml(String(username || 'unknown'));
            return `
                <span class="ticket-board-assignee-chip" title="${safeUsername}" aria-label="${safeUsername}">
                    <svg width="18" height="18" data-jdenticon-value="${safeUsername}"></svg>
                    <img src="/avatar/${encodeURIComponent(String(username || 'unknown'))}" alt="${safeUsername}" onload="this.classList.add('is-loaded'); if (this.previousElementSibling) this.previousElementSibling.style.display='none';" onerror="this.remove();">
                </span>
            `;
        }).join('');

        const subticketCount = Number(ticket.subticketCount || 0);
        const subticketDoneCount = Number(ticket.subticketDoneCount || 0);
        const subticketMeta = subticketCount > 0
            ? `<div class="ticket-board-card-subtasks">Subtasks ${subticketDoneCount}/${subticketCount}</div>`
            : '';

        return `
            <article class="ticket-board-card ${priorityClass}" draggable="true" data-ticket-id="${ticket.id}">
                <div class="ticket-board-card-id">${ticket.id}</div>
                <div class="ticket-board-card-title">${safeTitle}</div>
                <div class="ticket-board-card-meta">${ticket.project}</div>
                <div class="ticket-board-card-meta"><span class="ticket-board-priority ${priorityClass}">${priorityLabel}</span></div>
                ${subticketMeta}
                <div class="ticket-board-card-assignees">${assigneeHtml}</div>
            </article>
        `;
    },

    renderAvatars(container) {
        if (!container || !window.jdenticon) {
            return;
        }

        try {
            container.querySelectorAll('svg[data-jdenticon-value]').forEach((svg) => {
                window.jdenticon.update(svg);
            });
        } catch (e) {
            // Ignore transient render failures from async icon library load.
        }
    },

    escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    bindEvents(container, tickets, onMove, onCardClick, rerender) {
        container.querySelectorAll('.ticket-board-card').forEach((card) => {
            card.addEventListener('dragstart', (event) => {
                card.classList.add('dragging');
                event.dataTransfer.setData('text/plain', card.dataset.ticketId);
                event.dataTransfer.effectAllowed = 'move';
            });

            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
            });

            card.addEventListener('click', () => {
                const ticket = tickets.find((row) => row.id === card.dataset.ticketId);
                if (ticket) {
                    onCardClick(ticket);
                }
            });
        });

        container.querySelectorAll('[data-drop-zone]').forEach((zone) => {
            zone.addEventListener('dragover', (event) => {
                event.preventDefault();
                zone.classList.add('drag-over');
            });

            zone.addEventListener('dragleave', () => {
                zone.classList.remove('drag-over');
            });

            zone.addEventListener('drop', async (event) => {
                event.preventDefault();
                zone.classList.remove('drag-over');

                const ticketId = event.dataTransfer.getData('text/plain');
                const nextStatus = zone.dataset.dropZone;
                const ticket = tickets.find((row) => row.id === ticketId);
                if (!ticket || !nextStatus || ticket.status === nextStatus) {
                    return;
                }

                const previousStatus = ticket.status;
                ticket.status = nextStatus;
                rerender();

                try {
                    await onMove(ticket.id, nextStatus);
                    if (window.showToast) {
                        window.showToast('Ticket moved', 'success');
                    }
                } catch (error) {
                    ticket.status = previousStatus;
                    rerender();
                    if (window.showToast) {
                        window.showToast('Failed to move ticket', 'error');
                    }
                }
            });
        });
    }
};

window.TicketBoard = TicketBoard;
