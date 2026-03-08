const TicketBoard = {
    statuses: [
        { key: 'backlog', label: 'Backlog' },
        { key: 'todo', label: 'To Do' },
        { key: 'in-progress', label: 'In Progress' },
        { key: 'in-review', label: 'In Review' },
        { key: 'done', label: 'Done' }
    ],

    init(containerId, tickets, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) {
            return;
        }

        const onMove = options.onMove || (async () => {});
        const onCardClick = options.onCardClick || (() => {});

        const normalizedTickets = (tickets || []).map((ticket) => ({
            ...ticket,
            status: this.statuses.some((s) => s.key === ticket.status) ? ticket.status : 'backlog'
        }));

        const render = () => {
            const columnsHtml = this.statuses.map((status) => {
                const items = normalizedTickets.filter((ticket) => ticket.status === status.key);
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

        render();
    },

    renderCard(ticket) {
        const safeTitle = ticket.title || '(Untitled)';
        return `
            <article class="ticket-board-card" draggable="true" data-ticket-id="${ticket.id}">
                <div class="ticket-board-card-id">${ticket.id}</div>
                <div class="ticket-board-card-title">${safeTitle}</div>
                <div class="ticket-board-card-meta">${ticket.project}</div>
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
