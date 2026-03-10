const TicketBoard = {
    statuses: [
        { key: 'intake', label: 'Intake' },
        { key: 'backlog', label: 'Backlog' },
        { key: 'todo', label: 'To Do' },
        { key: 'in-progress', label: 'In Progress' },
        { key: 'in-review', label: 'In Review' },
        { key: 'done', label: 'Done' }
    ],

    getStatuses() {
        const page = window.ticketPageContext || 'tickets';
        if (page === 'triage' || page === 'intake') {
            return this.statuses;
        }
        return this.statuses.filter((status) => status.key !== 'intake');
    },

    init(containerId, tickets, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) {
            return;
        }

        const onMove = options.onMove || (async () => {});
        const onCardClick = options.onCardClick || (() => {});

        const statuses = this.getStatuses();
        const priorityFilter = document.getElementById('ticket-board-filter-priority');
        const assigneeFilter = document.getElementById('ticket-board-filter-assignee');

        const normalizedTickets = (tickets || []).map((ticket) => ({
            ...ticket,
            status: ticket.status === 'triage'
                ? 'intake'
                : (statuses.some((s) => s.key === ticket.status) ? ticket.status : 'backlog')
        }));

        const applyFilters = (rows) => {
            const selectedPriority = priorityFilter ? String(priorityFilter.value || 'all') : 'all';
            const selectedAssignee = assigneeFilter ? String(assigneeFilter.value || 'all') : 'all';

            return rows.filter((ticket) => {
                if (selectedPriority !== 'all' && String(ticket.urgency || 'none') !== selectedPriority) {
                    return false;
                }

                if (selectedAssignee === 'all') {
                    return true;
                }

                const assignees = Array.isArray(ticket.assignees) ? ticket.assignees : [];
                if (selectedAssignee === 'unassigned') {
                    return assignees.length === 0;
                }

                return assignees.includes(selectedAssignee);
            });
        };

        const render = () => {
            const visibleTickets = applyFilters(normalizedTickets);
            const columnsHtml = statuses.map((status) => {
                const items = visibleTickets.filter((ticket) => ticket.status === status.key);
                const cards = items.map((ticket) => this.renderCard(ticket)).join('');
                return `
                    <section class="ticket-board-column" data-status="${status.key}">
                        <header class="ticket-board-column-header">
                            <h3>${status.label}</h3>
                            <span>${items.length}</span>
                        </header>
                        <div class="ticket-board-column-body" data-drop-zone="${status.key}">
                            ${cards}
                        </div>
                    </section>
                `;
            }).join('');

            container.innerHTML = `<div class="ticket-board-grid">${columnsHtml}</div>`;
            this.bindEvents(container, normalizedTickets, onMove, onCardClick, render);
        };

        if (priorityFilter) {
            priorityFilter.addEventListener('change', render);
        }
        if (assigneeFilter) {
            assigneeFilter.addEventListener('change', render);
        }

        render();
    },

    renderCard(ticket) {
        const safeTitle = ticket.title || '(Untitled)';
        const priorityLabel = ticket.urgency || 'none';
        const assignees = Array.isArray(ticket.assignees) ? ticket.assignees : [];
        const assigneeHtml = assignees.slice(0, 3).map((username) => {
            const initial = (username || '?').charAt(0).toUpperCase();
            return `<span title="${username}" style="display:inline-flex;align-items:center;justify-content:center;width:1.2rem;height:1.2rem;border-radius:50%;background:#1f2937;color:#fff;font-size:0.7rem;">${initial}</span>`;
        }).join('');

        const subticketCount = Number(ticket.subticketCount || 0);
        const subticketDoneCount = Number(ticket.subticketDoneCount || 0);
        const subticketMeta = subticketCount > 0
            ? `<div class="ticket-board-card-subtasks">Subtasks ${subticketDoneCount}/${subticketCount}</div>`
            : '';

        return `
            <article class="ticket-board-card" draggable="true" data-ticket-id="${ticket.id}">
                <div class="ticket-board-card-id">${ticket.id}</div>
                <div class="ticket-board-card-title">${safeTitle}</div>
                <div class="ticket-board-card-meta">${ticket.project}</div>
                <div class="ticket-board-card-meta">Priority: ${priorityLabel}</div>
                ${subticketMeta}
                <div class="ticket-board-card-assignees" style="display:flex;gap:0.25rem;margin-top:0.35rem;">${assigneeHtml}</div>
            </article>
        `;
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
