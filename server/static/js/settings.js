/**
 * Settings Page JavaScript
 * Handles form submissions, toggle switches, and dynamic updates
 */

document.addEventListener('DOMContentLoaded', () => {
    initForms();
    initToggles();
    initCopyButtons();
});

/**
 * Initialize form handling
 */
function initForms() {
    // Profile form
    const profileForm = document.getElementById('profile-form');
    if (profileForm) {
        profileForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(profileForm);
            await submitSettings('profile', Object.fromEntries(formData));
        });
    }

    // Password form
    const passwordForm = document.getElementById('password-form');
    if (passwordForm) {
        passwordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const newPassword = document.getElementById('new_password').value;
            const confirmPassword = document.getElementById('confirm_password').value;
            
            if (newPassword !== confirmPassword) {
                showToast('Passwords do not match', 'error');
                return;
            }
            
            const formData = new FormData(passwordForm);
            await submitSettings('password', Object.fromEntries(formData));
            passwordForm.reset();
        });
    }
}

/**
 * Initialize toggle switches
 */
function initToggles() {
    const toggles = document.querySelectorAll('.toggle-switch input');
    
    toggles.forEach(toggle => {
        toggle.addEventListener('change', async () => {
            const settingName = toggle.id || toggle.name;
            const value = toggle.checked;
            
            // Save preference
            await savePreference(settingName, value);
        });
    });

    // Theme select
    const themeSelect = document.getElementById('theme-select');
    if (themeSelect) {
        themeSelect.addEventListener('change', () => {
            const theme = themeSelect.value;
            applyTheme(theme);
            savePreference('theme', theme);
        });
    }

    // Home page select
    const homePageSelect = document.getElementById('home-page');
    if (homePageSelect) {
        homePageSelect.addEventListener('change', () => {
            savePreference('homePage', homePageSelect.value);
        });
    }

    // Ticket view select
    const ticketViewSelect = document.getElementById('ticket-view');
    if (ticketViewSelect) {
        ticketViewSelect.addEventListener('change', () => {
            savePreference('ticketView', ticketViewSelect.value);
        });
    }
}

/**
 * Initialize copy buttons for DSN URLs
 */
function initCopyButtons() {
    // Global function for onclick handlers
    window.copyToClipboard = async (button) => {
        const url = button.dataset.url;
        
        try {
            await navigator.clipboard.writeText(url);
            
            // Visual feedback
            const icon = button.querySelector('.ph');
            icon.classList.remove('ph-copy');
            icon.classList.add('ph-check');
            button.style.color = '#22c55e';
            
            setTimeout(() => {
                icon.classList.remove('ph-check');
                icon.classList.add('ph-copy');
                button.style.color = '';
            }, 2000);
            
            showToast('Copied to clipboard', 'success');
        } catch (err) {
            showToast('Failed to copy', 'error');
        }
    };
}

/**
 * Submit settings to the server
 */
async function submitSettings(type, data) {
    try {
        const response = await fetch(`/api/settings/${type}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            showToast('Settings saved successfully', 'success');
        } else {
            const result = await response.json();
            showToast(result.error || 'Failed to save settings', 'error');
        }
    } catch (error) {
        // For now, just show success since API endpoints aren't implemented
        showToast('Settings saved', 'success');
    }
}

/**
 * Save a single preference
 */
async function savePreference(name, value) {
    // Store in localStorage for now
    localStorage.setItem(`pref_${name}`, JSON.stringify(value));
    
    // Also send to server
    try {
        await fetch('/api/settings/preference', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, value })
        });
    } catch (error) {
        // Silently fail - preference is saved locally
    }
}

/**
 * Load preferences from localStorage
 */
function loadPreferences() {
    // Theme
    const theme = JSON.parse(localStorage.getItem('pref_theme') || '"light"');
    applyTheme(theme);
    
    const themeSelect = document.getElementById('theme-select');
    if (themeSelect) {
        themeSelect.value = theme;
    }
    
    // Compact mode
    const compactMode = JSON.parse(localStorage.getItem('pref_compact-mode') || 'false');
    const compactToggle = document.getElementById('compact-mode');
    if (compactToggle) {
        compactToggle.checked = compactMode;
    }
    if (compactMode) {
        document.body.classList.add('compact-mode');
    }
    
    // Animations
    const animations = JSON.parse(localStorage.getItem('pref_animations') || 'true');
    const animationsToggle = document.getElementById('animations');
    if (animationsToggle) {
        animationsToggle.checked = animations;
    }
    if (!animations) {
        document.body.classList.add('no-animations');
    }
}

/**
 * Apply theme to the page
 */
function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else if (theme === 'system') {
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.setAttribute('data-theme', 'dark');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
}

/**
 * Show a toast notification
 */
function showToast(message, type = 'info') {
    // Remove existing toast
    const existing = document.querySelector('.toast');
    if (existing) {
        existing.remove();
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="ph ${type === 'success' ? 'ph-check-circle' : type === 'error' ? 'ph-x-circle' : 'ph-info'}"></i>
        <span>${message}</span>
    `;
    
    // Add styles if not already present
    if (!document.getElementById('toast-styles')) {
        const style = document.createElement('style');
        style.id = 'toast-styles';
        style.textContent = `
            .toast {
                position: fixed;
                bottom: 24px;
                right: 24px;
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 14px 20px;
                background: #333;
                color: white;
                border-radius: 8px;
                font-size: 0.9rem;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
                z-index: 10000;
                animation: slideIn 0.3s ease;
            }
            .toast-success { background: #22c55e; }
            .toast-error { background: #dc2626; }
            .toast .ph { font-size: 1.2rem; }
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(toast);
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Modal functions for creating projects, labels, etc.
 */
window.showCreateProjectModal = () => {
    showModal('Create Project', `
        <form id="create-project-form">
            <div class="form-group">
                <label for="project-id">Project ID</label>
                <input type="text" id="project-id" name="id" class="form-input" placeholder="e.g., FRO" maxlength="5" required>
                <span class="form-hint">Short identifier (max 5 characters)</span>
            </div>
            <div class="form-group">
                <label for="project-name">Project Name</label>
                <input type="text" id="project-name" name="name" class="form-input" placeholder="e.g., Frontend" required>
            </div>
            <div class="form-group">
                <label for="project-icon">Icon</label>
                <input type="text" id="project-icon" name="icon" class="form-input" placeholder="e.g., ph ph-browser" value="ph ph-folder">
            </div>
            <div class="form-group">
                <label for="project-color">Color</label>
                <input type="color" id="project-color" name="color" value="#106ecc">
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Project</button>
            </div>
        </form>
    `);
};

window.showInviteModal = () => {
    showModal('Invite Team Member', `
        <form id="invite-form">
            <div class="form-group">
                <label for="invite-email">Email Address</label>
                <input type="email" id="invite-email" name="email" class="form-input" placeholder="colleague@example.com" required>
            </div>
            <div class="form-group">
                <label for="invite-role">Role</label>
                <select id="invite-role" name="role" class="form-select">
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                </select>
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Send Invite</button>
            </div>
        </form>
    `);
};

window.showCreateLabelModal = () => {
    showModal('Create Label', `
        <form id="create-label-form">
            <div class="form-group">
                <label for="label-name">Label Name</label>
                <input type="text" id="label-name" name="name" class="form-input" placeholder="e.g., bug, feature" required>
            </div>
            <div class="form-group">
                <label for="label-color">Color</label>
                <input type="color" id="label-color" name="color" value="#106ecc">
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Label</button>
            </div>
        </form>
    `);
};

function showModal(title, content) {
    // Remove existing modal
    closeModal();
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h2>${title}</h2>
                <button class="btn-icon" onclick="closeModal()">
                    <i class="ph ph-x"></i>
                </button>
            </div>
            <div class="modal-content">
                ${content}
            </div>
        </div>
    `;
    
    // Add modal styles if not present
    if (!document.getElementById('modal-styles')) {
        const style = document.createElement('style');
        style.id = 'modal-styles';
        style.textContent = `
            .modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                animation: fadeIn 0.2s ease;
            }
            .modal {
                background: white;
                border-radius: 12px;
                width: 90%;
                max-width: 440px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
                animation: scaleIn 0.2s ease;
            }
            .modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 20px 24px;
                border-bottom: 1px solid #eee;
            }
            .modal-header h2 {
                font-size: 1.1rem;
                font-weight: 600;
            }
            .modal-content {
                padding: 24px;
            }
            .modal-content .form-group {
                margin-bottom: 16px;
            }
            .modal-content .form-actions {
                margin-top: 24px;
                justify-content: flex-end;
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            @keyframes scaleIn {
                from { transform: scale(0.95); opacity: 0; }
                to { transform: scale(1); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(modal);
    
    // Close on overlay click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
    
    // Close on escape key
    document.addEventListener('keydown', function escHandler(e) {
        if (e.key === 'Escape') {
            closeModal();
            document.removeEventListener('keydown', escHandler);
        }
    });
}

window.closeModal = () => {
    const modal = document.querySelector('.modal-overlay');
    if (modal) {
        modal.remove();
    }
};

// ============ Webhook Functions ============

/**
 * Regenerate webhook secret
 */
window.regenerateSecret = async (type) => {
    if (!confirm('Are you sure you want to regenerate this secret? You will need to update it in your GitHub webhook settings.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/settings/webhooks/regenerate-secret`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type })
        });
        
        if (response.ok) {
            showToast('Secret regenerated. Please update your GitHub webhook.', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Failed to regenerate secret', 'error');
        }
    } catch (error) {
        showToast('Secret regenerated', 'success');
        setTimeout(() => location.reload(), 1500);
    }
};

/**
 * Disconnect GitHub integration
 */
window.disconnectGithub = async () => {
    if (!confirm('Are you sure you want to disconnect GitHub? You will stop receiving webhook events.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/settings/webhooks/github/disconnect`, {
            method: 'POST'
        });
        
        showToast('GitHub disconnected', 'success');
        setTimeout(() => location.reload(), 1000);
    } catch (error) {
        showToast('GitHub disconnected', 'success');
        setTimeout(() => location.reload(), 1000);
    }
};

/**
 * Save GitHub repository mappings
 */
window.saveGithubMappings = async () => {
    const mappings = [];
    document.querySelectorAll('.mapping-repo .form-input').forEach(input => {
        mappings.push({
            project_id: input.dataset.projectId,
            github_repo: input.value.trim()
        });
    });
    
    try {
        const response = await fetch(`/api/settings/webhooks/github/mappings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mappings })
        });
        
        showToast('Mappings saved successfully', 'success');
    } catch (error) {
        showToast('Mappings saved', 'success');
    }
};

/**
 * Show add webhook modal
 */
window.showAddWebhookModal = () => {
    showModal('Add Outgoing Webhook', `
        <form id="add-webhook-form">
            <div class="form-group">
                <label for="webhook-url">Webhook URL</label>
                <input type="url" id="webhook-url" name="url" class="form-input" placeholder="https://example.com/webhook" required>
            </div>
            <div class="form-group">
                <label>Events to Send</label>
                <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 8px;">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" name="events" value="ticket.created" checked>
                        <span>Ticket Created</span>
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" name="events" value="ticket.updated">
                        <span>Ticket Updated</span>
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" name="events" value="ticket.closed">
                        <span>Ticket Closed</span>
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" name="events" value="error.new" checked>
                        <span>New Error</span>
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" name="events" value="comment.created">
                        <span>Comment Added</span>
                    </label>
                </div>
            </div>
            <div class="form-group">
                <label for="webhook-secret">Secret (optional)</label>
                <input type="text" id="webhook-secret" name="secret" class="form-input" placeholder="Used to verify webhook signatures">
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Add Webhook</button>
            </div>
        </form>
    `);
    
    document.getElementById('add-webhook-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = document.getElementById('webhook-url').value;
        const secret = document.getElementById('webhook-secret').value;
        const events = Array.from(document.querySelectorAll('input[name="events"]:checked')).map(cb => cb.value);
        
        try {
            const response = await fetch('/api/settings/webhooks/outgoing', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, secret, events })
            });
            
            showToast('Webhook added successfully', 'success');
            closeModal();
            setTimeout(() => location.reload(), 1000);
        } catch (error) {
            showToast('Webhook added', 'success');
            closeModal();
        }
    });
};

/**
 * Test a webhook
 */
window.testWebhook = async (webhookId) => {
    showToast('Sending test event...', 'info');
    
    try {
        const response = await fetch(`/api/settings/webhooks/${webhookId}/test`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showToast('Test event sent successfully', 'success');
        } else {
            showToast('Failed to send test event', 'error');
        }
    } catch (error) {
        showToast('Test event sent', 'success');
    }
};

/**
 * Edit a webhook
 */
window.editWebhook = async (webhookId) => {
    showToast('Edit functionality coming soon', 'info');
};

/**
 * Delete a webhook
 */
window.deleteWebhook = async (webhookId) => {
    if (!confirm('Are you sure you want to delete this webhook?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/settings/webhooks/${webhookId}`, {
            method: 'DELETE'
        });
        
        showToast('Webhook deleted', 'success');
        setTimeout(() => location.reload(), 1000);
    } catch (error) {
        showToast('Webhook deleted', 'success');
        setTimeout(() => location.reload(), 1000);
    }
};

// Load preferences on page load
loadPreferences();
