(function initTriageDashboard() {
    const data = window.triageData || { tickets: [], projects: [], endpoints: {} };
    const state = {
        history: [],
        draft: null,
        readyToCommit: false,
        guidedStep: 0,
        guidedDraft: {
            title: '',
            impact: '',
            context: '',
            project: '',
        },
    };

    const chatThread = document.getElementById('triage-chat-thread');
    const chatInput = document.getElementById('triage-chat-input');
    const chatSend = document.getElementById('triage-chat-send');
    const resetButton = document.getElementById('triage-chat-reset');

    function toast(message, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type || 'success');
            return;
        }
        console.log(message);
    }

    function appendChatBubble(role, text) {
        if (!chatThread) {
            return;
        }
        const row = document.createElement('div');
        row.className = `triage-chat-row triage-chat-row-${role}`;

        const bubble = document.createElement('div');
        bubble.className = `triage-chat-bubble triage-chat-bubble-${role}`;
        bubble.textContent = text;

        row.appendChild(bubble);
        chatThread.appendChild(row);
        chatThread.scrollTop = chatThread.scrollHeight;
    }

    function showTypingIndicator() {
        if (!chatThread) {
            return;
        }

        const existing = chatThread.querySelector('#triage-chat-typing-row');
        if (existing) {
            return;
        }

        const row = document.createElement('div');
        row.id = 'triage-chat-typing-row';
        row.className = 'triage-chat-row triage-chat-row-assistant triage-chat-typing-row';
        row.innerHTML = `
            <div class="triage-chat-bubble triage-chat-bubble-assistant triage-chat-typing-bubble" aria-live="polite" aria-label="Assistant is typing">
                <span class="triage-dot"></span>
                <span class="triage-dot"></span>
                <span class="triage-dot"></span>
            </div>
        `;
        chatThread.appendChild(row);
        chatThread.scrollTop = chatThread.scrollHeight;
    }

    function hideTypingIndicator() {
        if (!chatThread) {
            return;
        }
        const row = chatThread.querySelector('#triage-chat-typing-row');
        if (row) {
            row.remove();
        }
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setSendBusy(isBusy) {
        if (!chatSend) {
            return;
        }
        chatSend.disabled = isBusy;
        chatSend.innerHTML = isBusy ? 'Sending...' : '<i class="ph ph-paper-plane-tilt"></i> Send';
    }

    function seedConversation() {
        chatThread.innerHTML = '';
        if (data.aiEnabled) {
            appendChatBubble('assistant', 'Tell me what is broken. I will ask follow-up questions and prepare the ticket draft.');
        } else {
            appendChatBubble('assistant', 'Quick Intake assistant ready. Tell me the problem summary in one sentence.');
            appendChatBubble('assistant', 'Tip: you can paste one full paragraph and I will guide the remaining details.');
        }
    }

    async function patchTicket(ticketId, field, value) {
        const response = await fetch(`/api/tickets/${ticketId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ field, value }),
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || 'Failed to update ticket');
        }
    }

    function updateInboxCount() {
        const countEl = document.getElementById('triage-inbox-count');
        const list = document.getElementById('triage-inbox-list');
        const empty = document.getElementById('triage-empty-state');
        if (!countEl || !list || !empty) {
            return;
        }

        const rows = list.querySelectorAll('.triage-inbox-row').length;
        countEl.textContent = String(rows);
        empty.classList.toggle('triage-hidden', rows > 0);
    }

    async function sendTicketFromRow(row, explicitProjectId) {
        const ticketId = row.dataset.triageTicketId;
        const projectId = String(explicitProjectId || '').trim();

        if (!ticketId || !projectId) {
            toast('Pick a project before routing', 'error');
            return;
        }

        try {
            await patchTicket(ticketId, 'project', projectId);
            await patchTicket(ticketId, 'status', 'backlog');
            row.remove();
            updateInboxCount();
            toast(`Sent ${ticketId} to ${projectId}`, 'success');
        } catch (error) {
            toast(error.message || 'Failed to send ticket', 'error');
        }
    }

    function createDraftCardRow() {
        if (!chatThread) {
            return null;
        }

        const row = document.createElement('div');
        row.className = 'triage-chat-row triage-chat-row-assistant triage-chat-draft-row';
        chatThread.appendChild(row);
        return row;
    }

    function archivePreviousDraftCards() {
        if (!chatThread) {
            return;
        }

        const cards = Array.from(chatThread.querySelectorAll('.triage-chat-draft-row .triage-chat-bubble-card'));
        cards.forEach((card) => {
            card.classList.add('triage-draft-card-archived');
            const status = card.querySelector('.triage-draft-card-status');
            if (status) {
                status.textContent = 'Superseded';
            }

            card.querySelectorAll('.triage-draft-commit-triage, .triage-draft-commit-project').forEach((button) => {
                button.disabled = true;
            });
        });
    }

    function renderPossibleDuplicatesMarkup(possibleDuplicates) {
        const matches = Array.isArray(possibleDuplicates) ? possibleDuplicates : [];
        if (!matches.length) {
            return '';
        }

        const items = matches
            .slice(0, 3)
            .map((match) => {
                const score = Math.round(Number(match.score || 0) * 100);
                return `<li><strong>${escapeHtml(match.id)}</strong> - ${escapeHtml(match.title)} (${score}% match)</li>`;
            })
            .join('');

        return `
            <div class="triage-ai-duplicates">
                <p><strong>Possible duplicates found:</strong></p>
                <ul>${items}</ul>
            </div>
        `;
    }

    function bindInboxRows() {
        document.querySelectorAll('.triage-inbox-row .triage-route-project-btn').forEach((button) => {
            button.addEventListener('click', () => {
                const row = button.closest('.triage-inbox-row');
                if (row) {
                    const projectId = button.getAttribute('data-project-id') || '';
                    sendTicketFromRow(row, projectId);
                }
            });
        });
    }

    function findProjectByHint(rawHint) {
        const hint = String(rawHint || '').trim().toLowerCase();
        if (!hint || hint === 'skip' || hint === 'none' || hint === 'intake' || hint === 'triage') {
            return '';
        }

        const byId = (data.projects || []).find((project) => String(project.id || '').toLowerCase() === hint);
        if (byId) {
            return byId.id;
        }

        const byName = (data.projects || []).find((project) => String(project.name || '').toLowerCase().includes(hint));
        return byName ? byName.id : '';
    }

    function inferPriorityFromText(text) {
        const lowered = (text || '').toLowerCase();
        if (/critical|outage|down|urgent|data loss/.test(lowered)) {
            return 'urgent';
        }
        if (/broken|fails|error|cannot|can't|failure/.test(lowered)) {
            return 'high';
        }
        return 'medium';
    }

    function buildLocalDraft() {
        const description = `Impact/Urgency:\n${state.guidedDraft.impact}\n\nContext/Details:\n${state.guidedDraft.context}`;
        return {
            title: state.guidedDraft.title,
            description,
            priority: inferPriorityFromText(`${state.guidedDraft.impact} ${state.guidedDraft.context}`),
            suggested_project: state.guidedDraft.project || null,
            confidence: 0.75,
            reason: 'Guided intake conversation completed.',
            route: state.guidedDraft.project ? 'direct' : 'intake',
            source: 'guided',
        };
    }

    function handleGuidedTurn(message) {
        const answer = String(message || '').trim();
        if (!answer) {
            appendChatBubble('assistant', 'Please add a short answer so we can continue.');
            return;
        }

        if (state.guidedStep === 0) {
            state.guidedDraft.title = answer;
            state.guidedStep = 1;
            appendChatBubble('assistant', 'Got it. What is the impact and urgency?');
            return;
        }

        if (state.guidedStep === 1) {
            state.guidedDraft.impact = answer;
            state.guidedStep = 2;
            appendChatBubble('assistant', 'Thanks. Can you share context details, examples, or steps to reproduce?');
            return;
        }

        if (state.guidedStep === 2) {
            state.guidedDraft.context = answer;
            state.guidedStep = 3;
            appendChatBubble('assistant', 'Last step: optional project hint (project ID/name) or type "skip".');
            return;
        }

        if (state.guidedStep === 3) {
            state.guidedDraft.project = findProjectByHint(answer);
            state.draft = buildLocalDraft();
            state.readyToCommit = true;
            renderDraft(state.draft, state.readyToCommit);

            if (state.guidedDraft.project) {
                appendChatBubble('assistant', `Great. Draft ready and suggested project is ${state.guidedDraft.project}. Confirm where to create it in the draft card.`);
            } else {
                appendChatBubble('assistant', 'Great. Draft ready. No project match provided, so creating in intake is recommended in the draft card.');
            }
        }
    }

    function renderDraft(draft, readyToCommit, possibleDuplicates, assistantMessage) {
        if (!chatThread) {
            return;
        }

        if (!draft) {
            chatThread.querySelectorAll('.triage-chat-draft-row').forEach((row) => row.remove());
            return;
        }

        archivePreviousDraftCards();

        const row = createDraftCardRow();
        if (!row) {
            return;
        }

        const hasProject = Boolean(draft.suggested_project);
        const statusLabel = readyToCommit ? 'Ready to create' : 'Needs more info';
        const statusClass = readyToCommit ? 'triage-draft-card-status-ready' : 'triage-draft-card-status-warning';
        const showFollowup = Boolean(assistantMessage) && (!readyToCommit || (Array.isArray(possibleDuplicates) && possibleDuplicates.length));
        const followup = showFollowup ? `<p class="triage-draft-card-followup">${escapeHtml(assistantMessage)}</p>` : '';
        const duplicateMarkup = renderPossibleDuplicatesMarkup(possibleDuplicates);

        row.innerHTML = `
            <div class="triage-chat-bubble triage-chat-bubble-assistant triage-chat-bubble-card">
                <div class="triage-draft-card-header">
                    <strong class="triage-draft-card-title"><i class="ph ph-note-pencil"></i> Draft Ticket</strong>
                    <span class="triage-draft-card-status ${statusClass}">${statusLabel}</span>
                </div>
                ${followup}
                <p class="triage-draft-main-title">${escapeHtml(draft.title || 'Untitled')}</p>
                <div class="triage-draft-meta">
                    <span class="triage-draft-meta-item"><i class="ph ph-folder-open"></i>${escapeHtml(draft.suggested_project || 'intake')}</span>
                    <span class="triage-draft-meta-item"><i class="ph ph-flag"></i>${escapeHtml(draft.priority || 'medium')}</span>
                </div>
                <div class="triage-ai-draft-description">${escapeHtml(draft.description || 'No description available yet.')}</div>
                ${duplicateMarkup}
                <div class="triage-intake-actions">
                    <button type="button" class="btn btn-secondary triage-draft-commit-triage" ${readyToCommit ? '' : 'disabled'}><i class="ph ph-tray"></i> Create in Intake</button>
                    <button type="button" class="btn btn-primary triage-draft-commit-project ${readyToCommit && hasProject ? '' : 'triage-hidden'}"><i class="ph ph-arrow-square-out"></i> Create in Suggested Project</button>
                </div>
            </div>
        `;

        const commitTriage = row.querySelector('.triage-draft-commit-triage');
        const commitProject = row.querySelector('.triage-draft-commit-project');
        if (commitTriage) {
            commitTriage.addEventListener('click', () => commitAIDraft('intake'));
        }
        if (commitProject) {
            commitProject.addEventListener('click', () => commitAIDraft('project'));
        }

        chatThread.scrollTop = chatThread.scrollHeight;
    }

    async function sendChatTurn() {
        const message = chatInput ? chatInput.value.trim() : '';
        if (!message) {
            toast('Please enter a message', 'error');
            return;
        }

        setSendBusy(true);

        appendChatBubble('user', message);
        state.history.push({ role: 'user', content: message });
        chatInput.value = '';

        if (!data.aiEnabled) {
            handleGuidedTurn(message);
            setSendBusy(false);
            return;
        }

        try {
            showTypingIndicator();
            const response = await fetch(data.endpoints.chat, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ history: state.history, message }),
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'AI chat failed');
            }

            const reply = payload.reply || {};
            const text = reply.message || 'Draft updated.';
            state.history.push({ role: 'assistant', content: text });

            state.draft = reply.draft || null;
            state.readyToCommit = Boolean(reply.ready_to_commit);
            renderDraft(state.draft, state.readyToCommit, reply.possible_duplicates || [], text);
        } catch (error) {
            appendChatBubble('assistant', error.message || 'I ran into a problem. Please try again.');
            toast(error.message || 'AI chat failed', 'error');
        } finally {
            hideTypingIndicator();
            setSendBusy(false);
        }
    }

    async function commitAIDraft(destination) {
        if (!state.draft || !state.readyToCommit) {
            toast('Complete the chat first so the draft is ready', 'error');
            return;
        }

        const payload = {
            destination,
            project: state.draft.suggested_project || null,
            suggestion: state.draft,
        };

        try {
            const response = await fetch(data.endpoints.commit, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const body = await response.json();
            if (!response.ok) {
                if (response.status === 409 && Array.isArray(body.possible_duplicates) && body.possible_duplicates.length) {
                    renderDraft(
                        state.draft,
                        false,
                        body.possible_duplicates,
                        'This looks like a duplicate of an existing ticket. Review the matches before creating another one.',
                    );
                }
                throw new Error(body.error || 'Failed to create ticket');
            }
            const createdTicket = body.ticket || {};
            const createdId = createdTicket.id || 'new ticket';
            const createdProject = createdTicket.project || 'intake';
            toast(`Created ${createdId} in ${createdProject}`, 'success');
            window.setTimeout(() => {
                window.location.reload();
            }, 900);
        } catch (error) {
            toast(error.message || 'Failed to create ticket', 'error');
        }
    }

    function bindIntakeControls() {
        if (chatSend && chatInput) {
            chatSend.addEventListener('click', sendChatTurn);
            chatInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    sendChatTurn();
                }
            });
        }

        if (resetButton) {
            resetButton.addEventListener('click', () => {
                state.history = [];
                state.draft = null;
                state.readyToCommit = false;
                state.guidedStep = 0;
                state.guidedDraft = {
                    title: '',
                    impact: '',
                    context: '',
                    project: '',
                };
                renderDraft(null, false, [], '');
                seedConversation();
                if (chatInput) {
                    chatInput.value = '';
                    chatInput.focus();
                }
            });
        }
    }

    bindIntakeControls();
    bindInboxRows();
    updateInboxCount();
    seedConversation();
})();
