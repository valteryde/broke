/*
 * Ticket Editor Class
 * Linear-style ticket editor with invisible Quill editor and comments
 *
 * Usage:
 * const editor = new TicketEditor('container-id', {
 *     ticket: {
 *         id: 'DEN-123',
 *         title: 'Ticket title',
 *         description: '<p>Rich text description</p>',
 *         status: 'in-progress',
 *         priority: 'high',
 *         labels: [{text: 'bug', color: 'red'}],
 *         assignees: [{id: '1', name: 'Alice', avatar: null}],
 *         dueDate: '2024-12-31'
 *     },
 *     currentUser: {
 *         id: '1',
 *         name: 'Alice',
 *         avatar: null
 *     },
 *     activity: [
 *         { type: 'comment', id: '1', author: {...}, content: '<p>Comment</p>', createdAt: '...' },
 *         { type: 'update', id: '2', author: {...}, field: 'status', oldValue: 'todo', newValue: 'in-progress', createdAt: '...' }
 *     ],
 *     onSave: (field, value) => { ... },
 *     onComment: (content) => { ... },
 *     onDeleteComment: (commentId) => { ... }
 * });
 */

// StatusConfig, StatusList, PriorityConfig, PriorityList are now loaded from config.js

class TicketEditor {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = options;
        this.ticket = options.ticket || {};
        this.currentUser = options.currentUser;
        this.activity = options.activity || [];
        this.activityFilter = 'all'; // 'all', 'comments', 'updates'

        // Callbacks
        this.onSave = options.onSave || (() => { });
        this.onComment = options.onComment || (() => { });
        this.onDeleteComment = options.onDeleteComment || (() => { });
        this.onEditComment = options.onEditComment || (() => { });

        // Quill instances
        this.descriptionEditor = null;
        this.commentEditor = null;

        // Save debounce timer
        this.saveTimer = null;

        // Dropdown instances
        this.dropdowns = {};

        this.init();
    }

    init() {
        this.render();
        this.initQuillEditors();
        this.initPropertyDropdowns();
        this.initEventListeners();
        this.initAiDelegateHandoff();
        this.initShortcuts();
    }

    renderAvatarIconJdenticon() {
        try {
            jdenticon();
        } catch (e) {
            setTimeout(() => {
                jdenticon();
            }, 500);
        }
    }

    renderErrorLink() {
        if (!this.ticket.error || !this.ticket.error.id) return '';
        return `
            <div class="ticket-property">
                <div class="ticket-property-label">Status</div>
                <button class="ticket-property-btn" onclick="window.location.href='/errors/${this.ticket.error.project}/${this.ticket.error.part}/${this.ticket.error.id}'">
                    <i class="ph ph-link"></i>
                    <span class="property-value">See Error</span>
                    <i class="ph ph-caret-down"></i>
                </button>
            </div>
        `;
    }


    render() {
        this.container.innerHTML = `
            <div class="ticket-page">
                <div class="ticket-main">
                    ${this.renderHeader()}
                    ${this.renderDescription()}
                    ${this.renderActivity()}
                </div>
                <div class="ticket-sidebar">
                    ${this.renderProperties()}
                    <br>
                    ${this.renderErrorLink()}
                </div>
            </div>
        `;
        this.renderAvatarIconJdenticon();
    }

    renderHeader() {
        return `
            <div class="ticket-header">
                <input
                    type="text"
                    class="ticket-title"
                    value="${this.escapeHtml(this.ticket.title || '')}"
                    placeholder="Enter ticket title..."
                    data-field="title"
                />
            </div>
        `;
    }

    renderDescription() {
        return `
            <div class="ticket-description">

                <div class="ticket-editor-container">
                    <div class="ticket-save-indicator">
                        <i class="ph ph-circle-notch"></i>
                        <span>Saving...</span>
                    </div>
                    <div id="ticket-description-editor" class="ticket-editor"></div>
                </div>
            </div>
        `;
    }

    renderProperties() {
        const status = StatusList.find(s => s.value === this.ticket.status) || StatusList[0];
        const priority = PriorityList.find(p => p.value === this.ticket.priority) || PriorityList[4];

        return `
            <div class="ticket-properties">
                <!-- Status -->
                <div class="ticket-property">
                    <div class="ticket-property-label">Status</div>
                    <button class="ticket-property-btn" data-property="status">
                        <i class="ph ${status.icon} ${status.colorClass}"></i>
                        <span class="property-value ${status.colorClass}">${status.label}</span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>

                <!-- Priority -->
                <div class="ticket-property">
                    <div class="ticket-property-label">Priority</div>
                    <button class="ticket-property-btn" data-property="priority">
                        <i class="ph ${priority.icon} ${priority.colorClass}"></i>
                        <span class="property-value ${priority.colorClass}">${priority.label}</span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>

                <!-- Assignees -->
                <div class="ticket-property">
                    <div class="ticket-property-label">Assignees</div>
                    <button class="ticket-property-btn" data-property="assignees">
                        <i class="ph ph-users"></i>
                        <span class="property-value">
                            ${this.renderAssigneesValue()}
                        </span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>

                <!-- Labels -->
                <div class="ticket-property">
                    <div class="ticket-property-label">Labels</div>
                    <button class="ticket-property-btn" data-property="labels">
                        <i class="ph ph-tag"></i>
                        <span class="property-value">
                            ${this.renderLabelsValue()}
                        </span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>

                ${(this.options.availableWorkCycles && this.options.availableWorkCycles.length) ? `
                <div class="ticket-property">
                    <div class="ticket-property-label">Sprint</div>
                    <button class="ticket-property-btn" data-property="workCycle">
                        <i class="ph ph-calendar-dots"></i>
                        <span class="property-value">${this.renderWorkCycleValue()}</span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>` : ''}

                <!-- External AI (orchestrator handoff — no full ticket in snippet) -->
                <div class="ticket-property ticket-property-ai-delegate">
                    <div class="ticket-property-label">External AI</div>
                    <button type="button" class="ticket-property-btn ticket-ai-delegate-toggle ${this.ticket.aiDelegate ? 'ticket-ai-delegate-on' : ''}" aria-pressed="${this.ticket.aiDelegate ? 'true' : 'false'}">
                        <i class="ph ph-robot"></i>
                        <span class="property-value">${this.ticket.aiDelegate ? 'Let AI do it — on' : 'Let AI do it — off'}</span>
                    </button>
                    <div class="ticket-ai-delegate-panel" style="display: ${this.ticket.aiDelegate ? 'block' : 'none'};">
                        <p class="ticket-ai-delegate-hint"><strong>Copy the whole box</strong> into your AI once. Broke mints a <strong>real token</strong> each time you load/refresh — it includes full ticket context and ready-to-run <code>curl</code> lines (no line-ending backslashes). Revoke old tokens under Settings → Agent tokens if you regenerate often.</p>
                        <textarea readonly class="form-input ticket-ai-delegate-text" rows="16" spellcheck="false" placeholder="Turn on above to load text…"></textarea>
                        <div class="ticket-ai-delegate-actions">
                            <button type="button" class="btn btn-secondary btn-sm" id="ai-delegate-copy">Copy</button>
                            <button type="button" class="btn btn-secondary btn-sm" id="ai-delegate-refresh">Reload</button>
                        </div>
                    </div>
                </div>

                <!-- Due Date -->
                <div class="ticket-property">
                    <div class="ticket-property-label">Due Date</div>
                    <button class="ticket-property-btn" data-property="dueDate">
                        <i class="ph ph-calendar"></i>
                        <span class="property-value ${this.getDueDateClass()}">
                            ${this.formatDueDate()}
                        </span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                </div>
            </div>
        `;
    }

    renderAssigneesValue() {
        if (!this.ticket.assignees || this.ticket.assignees.length === 0) {
            return '<span style="color: #999;">No assignees</span>';
        }
        return this.ticket.assignees.map(a => `
            <span class="ticket-assignee-tag">
                <svg width="16" height="16" data-jdenticon-value="${this.escapeHtml(a.username)}"></svg>
                ${this.escapeHtml(a.username)}
            </span> <br>
        `).join('');
    }

    renderLabelsValue() {
        if (!this.ticket.labels || this.ticket.labels.length === 0) {
            return '<span style="color: #999;">No labels</span>';
        }
        return this.ticket.labels.map(l => `
            <span class="ticket-label-tag">
                <span class="ticket-label-dot" style="background-color: ${l.color}"></span>
                ${this.escapeHtml(l.name)}
            </span><br>
        `).join('');
    }

    renderWorkCycleValue() {
        const id = this.ticket.workCycleId;
        if (id == null || id === '') {
            return '<span style="color: #999;">None</span>';
        }
        const cycles = this.options.availableWorkCycles || [];
        const c = cycles.find((x) => String(x.id) === String(id));
        if (c) {
            return `${this.escapeHtml(c.name)} (#${id})`;
        }
        return `#${this.escapeHtml(String(id))}`;
    }

    mountWorkCycleDropdown() {
        const wcBtn = this.container.querySelector('[data-property="workCycle"]');
        if (!wcBtn || !this.options.availableWorkCycles || !this.options.availableWorkCycles.length) {
            return;
        }
        const items = [
            {
                label: 'None',
                icon: 'ph-x',
                selected: this.ticket.workCycleId == null || this.ticket.workCycleId === '',
                onClick: () => this.setWorkCycle(null)
            },
            ...this.options.availableWorkCycles.map((c) => ({
                label: `${c.name} (#${c.id})`,
                icon: 'ph-calendar-dots',
                selected: String(this.ticket.workCycleId) === String(c.id),
                onClick: () => this.setWorkCycle(c.id)
            }))
        ];
        this.dropdowns.workCycle = new Dropdown(wcBtn, {
            items,
            closeOnClick: true
        });
    }

    setWorkCycle(cycleId) {
        this.ticket.workCycleId = cycleId;
        this.onSave('work_cycle_id', cycleId);
        this.refreshProperty('workCycle');
    }

    renderActivity() {
        return `
            <div class="ticket-activity">
                <div class="ticket-activity-header">
                    <div class="ticket-activity-title">
                        <i class="ph ph-chat-text"></i>
                        Activity
                    </div>
                    <div class="ticket-activity-tabs">
                        <button class="ticket-activity-tab ${this.activityFilter === 'all' ? 'active' : ''}" data-filter="all">All</button>
                        <button class="ticket-activity-tab ${this.activityFilter === 'comments' ? 'active' : ''}" data-filter="comments">Comments</button>
                        <button class="ticket-activity-tab ${this.activityFilter === 'updates' ? 'active' : ''}" data-filter="updates">Updates</button>
                    </div>
                </div>

                <div class="ticket-activity-list">
                    ${this.renderActivityItems()}
                </div>

                ${this.renderNewComment()}
            </div>
        `;
    }

    renderActivityItems() {
        const filtered = this.activity.filter(item => {
            if (this.activityFilter === 'all') return true;
            if (this.activityFilter === 'comments') return item.type === 'comment';
            if (this.activityFilter === 'updates') return item.type === 'update';
            return true;
        });

        // sort by createdAt ascending
        filtered.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));


        const groups = [];
        let currentGroup = null;

        filtered.forEach(item => {
            if (item.type === 'update') {
                if (currentGroup) {
                    currentGroup.items.push(item);
                } else {
                    currentGroup = {
                        type: 'update-group',
                        items: [item],
                        createdAt: item.createdAt // Use first item's time for sorting/display
                    };
                    groups.push(currentGroup);
                }
            } else {
                currentGroup = null;
                groups.push(item);
            }
        });

        if (groups.length === 0) {
            return '<div style="color: #999; font-size: 0.9rem; padding: 20px 0;">No activity yet.</div>';
        }

        const res = groups.map(item => {
            if (item.type === 'comment') {
                return this.renderComment(item);
            } else if (item.type === 'update-group') {
                return this.renderUpdateGroup(item);
            }
            return '';
        }).join('');

        return res;
    }

    renderComment(comment) {
        const isOwn = comment.author.username === this.currentUser.username;

        return `
            <div class="ticket-activity-item" data-comment-id="${comment.id}">
                <div class="ticket-activity-avatar">
                    <svg width="40" height="40" data-jdenticon-value="${this.escapeHtml(comment.author.username)}"></svg>
                </div>
                <div class="ticket-activity-content">
                    <div class="ticket-activity-meta">
                        <span class="ticket-activity-author">${this.escapeHtml(comment.author.name)}</span>
                        <span class="ticket-activity-time">${this.formatRelativeTime(comment.createdAt)}</span>
                    </div>
                    <div class="ticket-comment-body">
                        <div class="ticket-comment-text">${comment.content}</div>
                        <!--
                        ${isOwn ? `
                            <div class="ticket-comment-actions">
                                <button class="ticket-comment-action edit" data-action="edit">
                                    <i class="ph ph-pencil"></i> Edit
                                </button>
                                <button class="ticket-comment-action delete" data-action="delete">
                                    <i class="ph ph-trash"></i> Delete
                                </button>
                            </div>
                        ` : ''}
                        -->
                    </div>
                </div>
            </div>
        `;
    }

    renderUpdateGroup(group) {
        if (group.items.length === 1) {
            return this.renderUpdate(group.items[0]);
        }

        const count = group.items.length;
        const authors = [...new Set(group.items.map(i => i.author?.username || 'System'))];
        // For the group ID, we can use the timestamp of the first item
        const groupId = `group-${group.createdAt}`;

        return `
            <div class="ticket-activity-item update-group">
                <div class="ticket-activity-avatar">
                   <div class="update-group-icon">
                        <i class="ph ph-stack"></i>
                   </div>
                </div>
                <div class="ticket-activity-content">
                    <div class="ticket-activity-meta">
                        <span class="ticket-activity-author">${count} updates</span>
                        <span class="ticket-activity-time">${this.formatRelativeTime(group.createdAt)}</span>
                        <button class="update-group-toggle" onclick="document.getElementById('${groupId}').classList.toggle('expanded');">
                            Show details <i class="ph ph-caret-down"></i>
                        </button>
                    </div>
                    <div class="ticket-update-group-items" id="${groupId}">
                        ${group.items.map(item => `
                            <div class="ticket-update-item-row">
                                <i class="ph ${item.icon || 'ph-pencil'}"></i>
                                <span>${this.escapeHtml(item.message)}</span>
                                <span class="update-time">${this.formatRelativeTime(item.createdAt)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    renderUpdate(update) {
        return `
            <div class="ticket-activity-item">
                <div class="ticket-activity-avatar">
                    <div class="update-icon">
                        <i class="ph ${update.icon}"></i>
                    </div>
                </div>
                <div class="ticket-activity-content">
                    <div class="ticket-activity-meta">
                         <span class="ticket-activity-author">Update</span>
                        <span class="ticket-activity-time">${this.formatRelativeTime(update.createdAt)}</span>
                    </div>
                    <div class="ticket-update">
                        ${this.escapeHtml(update.message)}
                    </div>
                </div>
            </div>
        `;
    }

    renderNewComment() {
        return `
            <div class="ticket-new-comment">
                <div class="ticket-new-comment-avatar">
                    <svg width="40" height="40" data-jdenticon-value="${this.currentUser.username}"></svg>
                </div>
                <div class="ticket-new-comment-editor">
                    <div class="ticket-new-comment-container">
                        <div id="ticket-comment-editor" class="ticket-comment-quill"></div>
                        <div class="ticket-new-comment-actions">
                            <span class="ticket-new-comment-hint">
                                <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to submit
                            </span>
                            <button class="ticket-new-comment-submit" id="submit-comment">
                                <i class="ph ph-paper-plane-tilt"></i>
                                Comment
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    initQuillEditors() {
        // Description editor (invisible, no toolbar)
        this.descriptionEditor = new Quill('#ticket-description-editor', {
            theme: 'snow',
            placeholder: 'Add a description...',
            modules: {
                toolbar: false,
                keyboard: {
                    bindings: {
                        // Keep default shortcuts working
                    }
                }
            }
        });

        // Set initial content
        if (this.ticket.description) {
            this.descriptionEditor.root.innerHTML = this.ticket.description;
        }

        // Autosave on change
        this.descriptionEditor.on('text-change', () => {
            this.showSaveIndicator('saving');
            this.debounceSave('description', this.descriptionEditor.root.innerHTML);
        });

        // Comment editor (invisible, no toolbar)
        this.commentEditor = new Quill('#ticket-comment-editor', {
            theme: 'snow',
            placeholder: 'Write a comment...',
            modules: {
                toolbar: false
            }
        });

        // Ctrl+Enter to submit comment
        this.commentEditor.keyboard.addBinding({
            key: 'Enter',
            ctrlKey: true
        }, () => {
            this.submitComment();
        });

        // Also support Cmd+Enter on Mac
        this.commentEditor.keyboard.addBinding({
            key: 'Enter',
            metaKey: true
        }, () => {
            this.submitComment();
        });
    }

    initPropertyDropdowns() {
        // Status dropdown
        const statusBtn = this.container.querySelector('[data-property="status"]');
        if (statusBtn) {
            this.dropdowns.status = new Dropdown(statusBtn, {
                items: StatusList.map(s => ({
                    label: s.label,
                    icon: s.icon,
                    colorClass: s.colorClass,
                    selected: this.ticket.status === s.value,
                    onClick: () => this.updateProperty('status', s.value)
                })),
                closeOnClick: true
            });
        }

        // Priority dropdown
        const priorityBtn = this.container.querySelector('[data-property="priority"]');
        if (priorityBtn) {
            this.dropdowns.priority = new Dropdown(priorityBtn, {
                items: PriorityList.map(p => ({
                    label: p.label,
                    icon: p.icon,
                    colorClass: p.colorClass,
                    selected: this.ticket.priority === p.value,
                    onClick: () => this.updateProperty('priority', p.value)
                })),
                closeOnClick: true
            });
        }

        // Assignees dropdown (would need available users from options)
        const assigneesBtn = this.container.querySelector('[data-property="assignees"]');
        if (assigneesBtn && this.options.availableUsers) {
            this.dropdowns.assignees = new Dropdown(assigneesBtn, {
                items: this.options.availableUsers.map(u => ({
                    label: u.username,
                    avatar: '<svg width="16" height="16" data-jdenticon-value="' + this.escapeHtml(u.username) + '"></svg>',
                    selected: this.ticket.assignees?.some(a => a.id === u.id),
                    onClick: () => this.toggleAssignee(u)
                })),
                closeOnClick: false // Multi-select
            });
        }

        // Labels dropdown (would need available labels from options)
        const labelsBtn = this.container.querySelector('[data-property="labels"]');
        if (labelsBtn && this.options.availableLabels) {
            this.dropdowns.labels = new Dropdown(labelsBtn, {
                items: this.options.availableLabels.map(l => ({
                    label: l.name,
                    icon: 'ph-fill ph-circle',
                    iconColor: l.color,
                    selected: this.ticket.labels?.some(label => label.name === l.name),
                    onClick: () => this.toggleLabel(l)
                })),
                closeOnClick: false // Multi-select
            });
        }

        this.mountWorkCycleDropdown();

        // Due date dropdown
        const dueDateBtn = this.container.querySelector('[data-property="dueDate"]');
        if (dueDateBtn) {
            this.dropdowns.dueDate = new Dropdown(dueDateBtn, {
                items: [
                    { label: 'No due date', icon: 'ph-x', onClick: () => this.updateProperty('dueDate', null) },
                    { divider: true },
                    { label: 'Today', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(0) },
                    { label: 'Tomorrow', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(1) },
                    { label: 'In 3 days', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(3) },
                    { label: 'In 1 week', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(7) },
                    { label: 'In 2 weeks', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(14) },
                    { label: 'In 1 month', icon: 'ph-calendar-blank', onClick: () => this.setDueDate(30) }
                ],
                closeOnClick: true
            });
        }
    }

    initEventListeners() {
        // Title input
        const titleInput = this.container.querySelector('.ticket-title');
        if (titleInput) {
            titleInput.addEventListener('input', () => {
                this.debounceSave('title', titleInput.value);
            });

            titleInput.addEventListener('blur', () => {
                this.ticket.title = titleInput.value;
                this.onSave('title', titleInput.value);
            });
        }

        // Activity filter tabs
        this.container.querySelectorAll('.ticket-activity-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.activityFilter = tab.dataset.filter;
                this.refreshActivityList();
            });
        });

        // Submit comment button
        const submitBtn = this.container.querySelector('#submit-comment');
        if (submitBtn) {
            submitBtn.addEventListener('click', () => this.submitComment());
        }

        // Comment actions (edit/delete)
        this.container.addEventListener('click', (e) => {
            const actionBtn = e.target.closest('.ticket-comment-action');
            if (actionBtn) {
                const commentEl = actionBtn.closest('[data-comment-id]');
                const commentId = commentEl?.dataset.commentId;
                const action = actionBtn.dataset.action;

                if (action === 'delete' && commentId) {
                    this.deleteComment(commentId);
                } else if (action === 'edit' && commentId) {
                    this.editComment(commentId);
                }
            }
        });

        // Copy ticket ID
        const ticketIdEl = this.container.querySelector('.ticket-id');
        if (ticketIdEl) {
            ticketIdEl.addEventListener('click', () => {
                navigator.clipboard.writeText(this.ticket.id);
                // Could show a toast notification here
            });
        }
    }

    initAiDelegateHandoff() {
        this.container.addEventListener('click', async (e) => {
            const toggle = e.target.closest('.ticket-ai-delegate-toggle');
            if (toggle) {
                e.preventDefault();
                await this.toggleAiDelegate();
                return;
            }
            if (e.target.id === 'ai-delegate-copy') {
                e.preventDefault();
                const ta = this.container.querySelector('.ticket-ai-delegate-text');
                if (ta && ta.value) {
                    try {
                        await navigator.clipboard.writeText(ta.value);
                        if (window.showToast) window.showToast('Copied handoff', 'success');
                    } catch (err) {
                        ta.select();
                        document.execCommand('copy');
                    }
                }
                return;
            }
            if (e.target.id === 'ai-delegate-refresh') {
                e.preventDefault();
                if (this.ticket.aiDelegate) this.loadAiDelegateMarkdown();
            }
        });
        if (this.ticket.aiDelegate) {
            this.loadAiDelegateMarkdown();
        }
    }

    async toggleAiDelegate() {
        const next = !this.ticket.aiDelegate;
        try {
            const response = await fetch(`/api/tickets/${this.ticket.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ field: 'ai_delegate', value: next })
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                alert(data.error || 'Could not update');
                return;
            }
            if (data.ticket) {
                if (typeof data.ticket.ai_delegate === 'boolean') {
                    this.ticket.aiDelegate = data.ticket.ai_delegate;
                }
                if (data.ticket.status) {
                    this.ticket.status = data.ticket.status;
                }
            }
            this.refreshProperty('status');
            this.refreshAiDelegateUI();
        } catch (err) {
            console.error(err);
            alert('Network error');
        }
    }

    refreshAiDelegateUI() {
        const btn = this.container.querySelector('.ticket-ai-delegate-toggle');
        const panel = this.container.querySelector('.ticket-ai-delegate-panel');
        const val = btn && btn.querySelector('.property-value');
        if (btn) {
            btn.classList.toggle('ticket-ai-delegate-on', !!this.ticket.aiDelegate);
            btn.setAttribute('aria-pressed', this.ticket.aiDelegate ? 'true' : 'false');
        }
        if (val) {
            val.textContent = this.ticket.aiDelegate ? 'Let AI do it — on' : 'Let AI do it — off';
        }
        if (panel) {
            panel.style.display = this.ticket.aiDelegate ? 'block' : 'none';
        }
        if (this.ticket.aiDelegate) {
            this.loadAiDelegateMarkdown();
        } else {
            const ta = this.container.querySelector('.ticket-ai-delegate-text');
            if (ta) ta.value = '';
        }
    }

    async loadAiDelegateMarkdown() {
        const ta = this.container.querySelector('.ticket-ai-delegate-text');
        if (!ta) return;
        ta.value = 'Generating paste (minting API token)…';
        try {
            const r = await fetch(`/api/tickets/${this.ticket.id}/ai-delegate-pack`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    Accept: 'text/markdown',
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': window.BROKE_CSRF_TOKEN || ''
                },
                body: '{}'
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                ta.value = err.error || `Error (${r.status})`;
                return;
            }
            ta.value = await r.text();
        } catch (err) {
            ta.value = 'Could not generate pack';
        }
    }

    initShortcuts() {
        if (!window.shortcuts) return;

        // Only trigger shortcuts if not editing content, not in other inputs, and no modal is open.
        const target = () => {
            if (document.querySelector('.modal-overlay')) {
                return false;
            }
            const ae = document.activeElement;
            if (ae) {
                const tag = ae.tagName;
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || ae.isContentEditable) {
                    return false;
                }
            }
            const isDescriptionFocused = this.descriptionEditor && this.descriptionEditor.hasFocus();
            const isCommentFocused = this.commentEditor && this.commentEditor.hasFocus();
            if (isDescriptionFocused || isCommentFocused) {
                return false;
            }
            return true;
        };

        window.shortcuts.register('s', () => {
            const modal = new ListModal({
                title: 'Set Status',
                items: StatusList.map(s => ({
                    label: s.label,
                    value: s.value,
                    icon: s.icon,
                    colorClass: s.colorClass,
                    selected: this.ticket.status === s.value,
                })),
                onSelect: (item) => this.updateProperty('status', item.value)
            })
            modal.show();
            console.log(modal);

        }, 'Change Status', false, target);

        window.shortcuts.register('p', () => {
            new ListModal({
                title: 'Set Priority',
                items: PriorityList.map(p => ({
                    label: p.label,
                    value: p.value,
                    icon: p.icon,
                    colorClass: p.colorClass,
                    selected: this.ticket.priority === p.value
                })),
                onSelect: (item) => this.updateProperty('priority', item.value)
            }).show();
        }, 'Change Priority', false, target);

        window.shortcuts.register('a', () => {
            if (!this.options.availableUsers) return;
            new ListModal({
                title: 'Assign Member',
                items: this.options.availableUsers.map(u => ({
                    label: u.username,
                    value: u,
                    avatar: `<svg width="16" height="16" data-jdenticon-value="${this.escapeHtml(u.username)}"></svg>`,
                    selected: this.ticket.assignees?.some(a => a.id === u.id)
                })),
                onSelect: (item) => this.toggleAssignee(item.value),
                closeOnSelect: false
            }).show();
        }, 'Change Assignees', false, target);

        window.shortcuts.register('l', () => {
            if (!this.options.availableLabels) return;
            new ListModal({
                title: 'Add Label',
                items: this.options.availableLabels.map(l => ({
                    label: l.name,
                    value: l,
                    color: l.color,
                    selected: this.ticket.labels?.some(label => label.name === l.name)
                })),
                onSelect: (item) => this.toggleLabel(item.value),
                closeOnSelect: false
            }).show();
        }, 'Change Labels', false, target);

        window.shortcuts.register('d', () => {
            new ListModal({
                title: 'Set Due Date',
                items: [
                    { label: 'No due date', value: null, icon: 'ph-x' },
                    { label: 'Today', value: 0, icon: 'ph-calendar-blank' },
                    { label: 'Tomorrow', value: 1, icon: 'ph-calendar-blank' },
                    { label: 'In 3 days', value: 3, icon: 'ph-calendar-blank' },
                    { label: 'In 1 week', value: 7, icon: 'ph-calendar-blank' },
                    { label: 'In 2 weeks', value: 14, icon: 'ph-calendar-blank' },
                    { label: 'In 1 month', value: 30, icon: 'ph-calendar-blank' }
                ],
                onSelect: (item) => {
                    if (item.value === null) this.updateProperty('dueDate', null);
                    else this.setDueDate(item.value);
                }
            }).show();
        }, 'Change Due Date', false, target);
    }

    // Property updates
    updateProperty(field, value) {
        const oldValue = this.ticket[field];
        this.ticket[field] = value;
        this.onSave(field, value, oldValue);
        this.refreshProperty(field);
    }

    refreshProperty(field) {
        const btn = this.container.querySelector(`[data-property="${field}"]`);
        if (!btn) return;

        if (field === 'status') {
            const status = StatusList.find(s => s.value === this.ticket.status) || StatusList[0];
            btn.innerHTML = `
                <i class="ph ${status.icon} ${status.colorClass}"></i>
                <span class="property-value ${status.colorClass}">${status.label}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'priority') {
            const priority = PriorityList.find(p => p.value === this.ticket.priority) || PriorityList[4];
            btn.innerHTML = `
                <i class="ph ${priority.icon} ${priority.colorClass}"></i>
                <span class="property-value ${priority.colorClass}">${priority.label}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'assignees') {
            btn.innerHTML = `
                <i class="ph ph-users"></i>
                <span class="property-value">${this.renderAssigneesValue()}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'labels') {
            btn.innerHTML = `
                <i class="ph ph-tag"></i>
                <span class="property-value">${this.renderLabelsValue()}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'dueDate') {
            btn.innerHTML = `
                <i class="ph ph-calendar"></i>
                <span class="property-value ${this.getDueDateClass()}">${this.formatDueDate()}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'workCycle') {
            btn.innerHTML = `
                <i class="ph ph-calendar-dots"></i>
                <span class="property-value">${this.renderWorkCycleValue()}</span>
                <i class="ph ph-caret-down"></i>
            `;
            this.mountWorkCycleDropdown();
        }
    }

    toggleAssignee(user) {
        if (!this.ticket.assignees) this.ticket.assignees = [];

        const index = this.ticket.assignees.findIndex(a => a.id === user.id);
        if (index > -1) {
            this.ticket.assignees.splice(index, 1);
        } else {
            this.ticket.assignees.push(user);
        }

        this.onSave('assignees', this.ticket.assignees);
        this.refreshProperty('assignees');
        this.renderAvatarIconJdenticon();
    }

    toggleLabel(label) {
        if (!this.ticket.labels) this.ticket.labels = [];

        const index = this.ticket.labels.findIndex(l => l.name === label.name);
        if (index > -1) {
            this.ticket.labels.splice(index, 1);
        } else {
            this.ticket.labels.push(label);
        }

        console.log(this.ticket.labels);
        this.onSave('labels', this.ticket.labels);
        this.refreshProperty('labels');
    }

    setDueDate(daysFromNow) {
        const date = new Date();
        date.setDate(date.getDate() + daysFromNow);
        const dateStr = date.toISOString().split('T')[0];
        this.updateProperty('dueDate', dateStr);
    }

    // Comments
    submitComment() {
        const content = this.commentEditor.root.innerHTML;
        const text = this.commentEditor.getText().trim();

        if (!text) return;

        // Create comment object
        const comment = {
            type: 'comment',
            id: 'temp-' + Date.now(),
            author: this.currentUser,
            content: content,
            createdAt: new Date().toISOString()
        };

        // Add to activity
        this.activity.push(comment);
        this.refreshActivityList();

        // Clear editor
        this.commentEditor.setText('');

        // Callback
        this.onComment(content, comment);
    }

    deleteComment(commentId) {
        const index = this.activity.findIndex(item => item.id === commentId);
        if (index > -1) {
            this.activity.splice(index, 1);
            this.refreshActivityList();
            this.onDeleteComment(commentId);
        }
    }

    editComment(commentId) {
        // For now, just log - could implement inline editing
        const comment = this.activity.find(item => item.id === commentId);
        if (comment) {
            this.onEditComment(commentId, comment.content);
        }
    }

    refreshActivityList() {
        // Update tabs
        this.container.querySelectorAll('.ticket-activity-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.filter === this.activityFilter);
        });

        // Update list
        const list = this.container.querySelector('.ticket-activity-list');
        if (list) {
            list.innerHTML = this.renderActivityItems();
        }

        this.renderAvatarIconJdenticon();
    }

    // Add activity (for external use)
    addActivity(item) {
        this.activity.push(item);
        this.refreshActivityList();
    }

    // Save helpers
    debounceSave(field, value) {
        clearTimeout(this.saveTimer);
        this.saveTimer = setTimeout(() => {
            this.ticket[field] = value;
            this.onSave(field, value);
            this.showSaveIndicator('saved');
        }, 500);
    }

    showSaveIndicator(state) {
        const indicator = this.container.querySelector('.ticket-save-indicator');
        if (!indicator) return;

        indicator.classList.remove('saving', 'saved');
        indicator.classList.add('show', state);

        if (state === 'saving') {
            indicator.innerHTML = '<i class="ph ph-circle-notch"></i> Saving...';
        } else if (state === 'saved') {
            indicator.innerHTML = '<i class="ph ph-check"></i> Saved';
            setTimeout(() => {
                indicator.classList.remove('show');
            }, 2000);
        }
    }

    // Utility methods
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    getInitials(name) {
        if (!name) return '?';
        return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    }

    formatRelativeTime(dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    }

    formatDueDate() {
        if (!this.ticket.dueDate) return 'No due date';

        const date = new Date(this.ticket.dueDate);
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const tomorrow = new Date(today);
        tomorrow.setDate(tomorrow.getDate() + 1);

        if (date.toDateString() === today.toDateString()) {
            return 'Today';
        } else if (date.toDateString() === tomorrow.toDateString()) {
            return 'Tomorrow';
        }

        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    getDueDateClass() {
        if (!this.ticket.dueDate) return '';

        const date = new Date(this.ticket.dueDate);
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const diffDays = Math.ceil((date - today) / (1000 * 60 * 60 * 24));

        if (diffDays < 0) return 'overdue';
        if (diffDays <= 2) return 'soon';
        return '';
    }

    formatFieldName(field) {
        const names = {
            status: 'status',
            priority: 'priority',
            assignees: 'assignees',
            labels: 'labels',
            dueDate: 'due date',
            title: 'title',
            description: 'description'
        };
        return names[field] || field;
    }

    formatFieldValue(field, value) {
        if (field === 'status') {
            const status = StatusList.find(s => s.value === value);
            return status ? status.label : value;
        }
        if (field === 'priority') {
            const priority = PriorityList.find(p => p.value === value);
            return priority ? priority.label : value;
        }
        if (field === 'dueDate') {
            return value ? new Date(value).toLocaleDateString() : 'None';
        }
        if (Array.isArray(value)) {
            return value.map(v => v.name || v.text || v).join(', ') || 'None';
        }
        return value || 'None';
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TicketEditor;
}
