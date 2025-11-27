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

// Status options
const TicketStatuses = [
    { value: 'backlog', label: 'Backlog', icon: 'ph-circle-dashed', colorClass: 'status-backlog' },
    { value: 'todo', label: 'Todo', icon: 'ph-circle', colorClass: 'status-todo' },
    { value: 'in-progress', label: 'In Progress', icon: 'ph-circle-half', colorClass: 'status-in-progress' },
    { value: 'in-review', label: 'In Review', icon: 'ph-circle-notch', colorClass: 'status-in-review' },
    { value: 'done', label: 'Done', icon: 'ph-check-circle', colorClass: 'status-done' },
    { value: 'cancelled', label: 'Cancelled', icon: 'ph-x-circle', colorClass: 'status-cancelled' }
];

// Priority options
const TicketPriorities = [
    { value: 'urgent', label: 'Urgent', icon: 'ph-warning'},
    { value: 'high', label: 'High', icon: 'ph-cell-signal-high'},
    { value: 'medium', label: 'Medium', icon: 'ph-cell-signal-medium'},
    { value: 'low', label: 'Low', icon: 'ph-cell-signal-low'},
    { value: 'none', label: 'No priority', icon: 'ph-cell-signal-none'}
];

class TicketEditor {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = options;
        this.ticket = options.ticket || {};
        this.currentUser = options.currentUser;
        this.activity = options.activity || [];
        this.activityFilter = 'all'; // 'all', 'comments', 'updates'
        
        // Callbacks
        this.onSave = options.onSave || (() => {});
        this.onComment = options.onComment || (() => {});
        this.onDeleteComment = options.onDeleteComment || (() => {});
        this.onEditComment = options.onEditComment || (() => {});
        
        // Quill instances
        this.descriptionEditor = null;
        this.commentEditor = null;
        
        // Save debounce timer
        this.saveTimer = null;
        
        this.init();
    }
    
    init() {
        this.render();
        this.initQuillEditors();
        this.initPropertyDropdowns();
        this.initEventListeners();
        
        

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
        const status = TicketStatuses.find(s => s.value === this.ticket.status) || TicketStatuses[0];
        const priority = TicketPriorities.find(p => p.value === this.ticket.priority) || TicketPriorities[4];
        
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

        
        if (filtered.length === 0) {
            return '<div style="color: #999; font-size: 0.9rem; padding: 20px 0;">No activity yet.</div>';
        }

        const res = filtered.map(item => {
            console.log(item)
            if (item.type === 'comment') {
                return this.renderComment(item);
            } else if (item.type === 'update') {
                return this.renderUpdate(item);
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
    
    renderUpdate(update) {
        return `
            <div class="ticket-activity-item">
                <div class="ticket-activity-avatar">
                    
                </div>
                <div class="ticket-activity-content">
                    <div class="ticket-activity-meta">
                        <span class="ticket-activity-author"> <i class="ph ${update.icon}"> </i> </span>
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
            new Dropdown(statusBtn, {
                items: TicketStatuses.map(s => ({
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
            new Dropdown(priorityBtn, {
                items: TicketPriorities.map(p => ({
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
            new Dropdown(assigneesBtn, {
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
            new Dropdown(labelsBtn, {
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
        
        // Due date dropdown
        const dueDateBtn = this.container.querySelector('[data-property="dueDate"]');
        if (dueDateBtn) {
            new Dropdown(dueDateBtn, {
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
            const status = TicketStatuses.find(s => s.value === this.ticket.status) || TicketStatuses[0];
            btn.innerHTML = `
                <i class="ph ${status.icon} ${status.colorClass}"></i>
                <span class="property-value ${status.colorClass}">${status.label}</span>
                <i class="ph ph-caret-down"></i>
            `;
        } else if (field === 'priority') {
            const priority = TicketPriorities.find(p => p.value === this.ticket.priority) || TicketPriorities[4];
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
            const status = TicketStatuses.find(s => s.value === value);
            return status ? status.label : value;
        }
        if (field === 'priority') {
            const priority = TicketPriorities.find(p => p.value === value);
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
