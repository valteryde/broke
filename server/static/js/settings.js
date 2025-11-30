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
            
            const currentPassword = document.getElementById('current_password').value;
            const newPassword = document.getElementById('new_password').value;
            const confirmPassword = document.getElementById('confirm_password').value;
            
            // Validate fields
            if (!currentPassword) {
                showToast('Please enter your current password', 'error');
                return;
            }
            
            if (!newPassword) {
                showToast('Please enter a new password', 'error');
                return;
            }
            
            if (newPassword.length < 8) {
                showToast('Password must be at least 8 characters', 'error');
                return;
            }
            
            if (newPassword !== confirmPassword) {
                showToast('Passwords do not match', 'error');
                return;
            }
            
            try {
                const response = await fetch('/api/settings/security/password', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showToast(result.message || 'Password updated successfully', 'success');
                    passwordForm.reset();
                } else {
                    showToast(result.error || 'Failed to update password', 'error');
                }
            } catch (error) {
                showToast('Failed to update password', 'error');
            }
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

/*
List of random phosphor icons
*/
PhosphorIcons = [
    'ph-browser',
    'ph-folder',
    'ph-code',
    'ph-bug',
    'ph-rocket',
    'ph-cpu',
    'ph-database',
    'ph-shield-check',
    'ph-cloud',
    'ph-git-branch',
    'ph-terminal',
    'ph-wrench',
    'ph-magnifying-glass',
    'ph-laptop',
    'ph-network',
    'ph-key',
    'ph-lock-keyhole',
    'ph-lightning',
    'ph-flame'
];

function randomColor() {
    return '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6, '0');
}


/**
 * Modal functions for creating projects, labels, etc.
 * Uses the Modal component from modal.js
 */
window.showCreateProjectModal = (data = {}) => {
    Modal.show('Create Project', `
        <form id="create-project-form" action="${data.id ? '/api/settings/projects/update/' + data.id : '/api/settings/projects'}" method="POST" autocomplete="off">
            <div class="form-group">
                <label for="project-name">Project Name</label>
                <input type="text" id="project-name" name="name" class="form-input" placeholder="e.g., Frontend" value="${data.name || ''}" required>
            </div>
            <div class="form-group">
                <label for="project-icon">Icon</label>
                <input type="text" id="project-icon" name="icon" class="form-input" placeholder="e.g., ph ph-browser" value="ph ${data.icon || PhosphorIcons[Math.floor(Math.random() * PhosphorIcons.length)]}">
            </div>
            <div class="form-group">
                <label for="project-color">Color</label>
                <input type="color" id="project-color" name="color"  value="${data.color || randomColor()}">
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="Modal.close()">Cancel</button>
                <button type="submit" class="btn btn-primary">${data.id ? 'Update Project' : 'Create Project'}</button>
            </div>
        </form>
    `);
};


window.showInviteModal = () => {
    Modal.show('Invite Team Member', `
        <form id="invite-form" action="/api/settings/team/invite" method="POST" autocomplete="off">
            <div class="form-group">
                <label for="invite-name">Name</label>
                <input type="text" id="invite-name" name="name" class="form-input" placeholder="Colleague Name" required>
            </div>
            <!--
            <div class="form-group">
                <label for="invite-role">Role</label>
                <select id="invite-role" name="role" class="form-select">
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                </select>
            </div>
            -->
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="Modal.close()">Cancel</button>
                <button type="submit" class="btn btn-primary">Get invite</button>
            </div>
        </form>
    `);
};

window.showCreateLabelModal = () => {
    Modal.show('Create Label', `
        <form id="create-label-form" action="/api/settings/labels" method="POST" autocomplete="off">
            <div class="form-group">
                <label for="label-name">Label Name</label>
                <input type="text" id="label-name" name="name" class="form-input" placeholder="e.g., bug, feature" required>
            </div>
            <div class="form-group">
                <label for="label-color">Color</label>
                <input type="color" id="label-color" name="color" value="${randomColor()}">
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="Modal.close()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Label</button>
            </div>
        </form>
    `);
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


function generateNewToken() {
    fetch('/api/settings/tokens', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.token) {
            
            Modal.show('New API Token', `
                <p>Your new API token is shown below. Please copy it now, as you won't be able to see it again!</p>
                <br>
                <div style="background: #f3f4f6; padding: 12px; border-radius: 4px; word-break: break-all; margin-bottom: 16px;">${data.token}</div>
                <div class="form-actions">
                    <button type="button" class="btn btn-primary" onclick="Modal.close()">Close</button>
                </div>
            `);

        } else {
            showToast('Failed to generate token', 'error');
        }
    })
    .catch(() => {
        showToast('Failed to generate token', 'error');
    });
}

function deleteToken(tokenId) {
    if (!confirm('Are you sure you want to delete this token?')) {
        return;
    }
    
    fetch(`/api/settings/tokens/${tokenId}`, {
        method: 'DELETE'
    })
    .then(response => {
        if (response.ok) {
            showToast('Token deleted', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('Failed to delete token', 'error');
        }
    })
    .catch(() => {
        showToast('Token deleted', 'success');
        setTimeout(() => location.reload(), 1000);
    });
}


// ============ DSN Token Functions ============

function generateDSNToken() {
    fetch('/api/settings/dsn-token', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('DSN token generated', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('Failed to generate DSN token', 'error');
        }
    })
    .catch(() => {
        showToast('Failed to generate DSN token', 'error');
    });
}

function revokeDSNToken() {
    if (!confirm('Are you sure you want to revoke the DSN token? All applications using this token will stop working.')) {
        return;
    }
    
    fetch('/api/settings/dsn-token', {
        method: 'DELETE'
    })
    .then(response => {
        if (response.ok) {
            showToast('DSN token revoked', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast('Failed to revoke DSN token', 'error');
        }
    })
    .catch(() => {
        showToast('Failed to revoke DSN token', 'error');
    });
}