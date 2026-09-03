(function () {
    const csrfHeaders = function () {
        return {
            'Content-Type': 'application/json',
            Accept: 'application/json',
            'X-CSRF-Token': window.BROKE_CSRF_TOKEN || '',
        };
    };

    async function readJson(response) {
        const raw = await response.text();
        let data = {};
        try {
            if (raw) data = JSON.parse(raw);
        } catch (_) {
            /* ignore */
        }
        return data;
    }

    function countMarks(text) {
        let actions = 0;
        let decisions = 0;
        let questions = 0;
        let topics = 0;
        const lines = String(text || '').split(/\n/);
        for (let i = 0; i < lines.length; i += 1) {
            const line = lines[i].trim();
            if (line.startsWith('# ')) topics += 1;
            else if (line.startsWith('!')) actions += 1;
            else if (line.startsWith('=')) decisions += 1;
            else if (line.startsWith('?')) questions += 1;
        }
        return { actions, decisions, questions, topics };
    }

    function formatCounts(counts) {
        const parts = [];
        if (counts.topics) parts.push(counts.topics + ' topic' + (counts.topics === 1 ? '' : 's'));
        if (counts.actions) parts.push(counts.actions + ' action' + (counts.actions === 1 ? '' : 's'));
        if (counts.decisions) parts.push(counts.decisions + ' decision' + (counts.decisions === 1 ? '' : 's'));
        if (counts.questions) parts.push(counts.questions + ' question' + (counts.questions === 1 ? '' : 's'));
        return parts.join(' · ') || 'No marks yet — that is fine';
    }

    async function createMeeting() {
        const response = await fetch(brokeAppUrl('/api/meetings'), {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfHeaders(),
            body: JSON.stringify({}),
        });
        const data = await readJson(response);
        if (!response.ok) {
            throw new Error(data.error || 'Could not start a meeting');
        }
        const id = data.meeting && data.meeting.id;
        if (id == null) {
            throw new Error('Unexpected response');
        }
        window.location.href = brokeAppUrl('/meetings/' + id);
    }

    async function startBrokeMeeting(btn) {
        if (btn) btn.disabled = true;
        try {
            await createMeeting();
        } catch (err) {
            if (btn) btn.disabled = false;
            if (typeof showToast === 'function') {
                showToast(err.message || 'Could not start a meeting', 'error');
            } else {
                alert(err.message || 'Could not start a meeting');
            }
        }
    }

    window.startBrokeMeeting = startBrokeMeeting;

    const newBtn = document.getElementById('meeting-new-btn');
    if (newBtn) {
        newBtn.addEventListener('click', function () {
            startBrokeMeeting(newBtn);
        });
    }

    const page = document.getElementById('meeting-page');
    if (!page) return;

    const meetingId = page.getAttribute('data-meeting-id');
    const isDone = page.getAttribute('data-done') === '1';
    const titleInput = document.getElementById('meeting-title');
    const notesInput = document.getElementById('meeting-notes');
    const countsEl = document.getElementById('meeting-counts');
    const saveEl = document.getElementById('meeting-save-state');
    const doneBtn = document.getElementById('meeting-done-btn');
    let saveTimer = null;
    let dirty = false;

    function refreshCounts() {
        if (!countsEl || !notesInput) return;
        countsEl.textContent = formatCounts(countMarks(notesInput.value));
    }

    function setSaveState(text) {
        if (saveEl) saveEl.textContent = text;
    }

    async function saveMeeting() {
        if (isDone || !dirty) return;
        const payload = {
            title: titleInput ? titleInput.value : '',
            notes: notesInput ? notesInput.value : '',
        };
        setSaveState('Saving…');
        const response = await fetch(brokeAppUrl('/api/meetings/' + encodeURIComponent(meetingId)), {
            method: 'PATCH',
            credentials: 'same-origin',
            headers: csrfHeaders(),
            body: JSON.stringify(payload),
        });
        const data = await readJson(response);
        if (!response.ok) {
            setSaveState(data.error || 'Save failed');
            return;
        }
        dirty = false;
        setSaveState('Saved');
    }

    function scheduleSave() {
        if (isDone) return;
        dirty = true;
        setSaveState('Editing…');
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            saveMeeting().catch(function () {
                setSaveState('Save failed');
            });
        }, 500);
    }

    async function finishMeeting() {
        if (isDone || !doneBtn) return;
        if (saveTimer) {
            clearTimeout(saveTimer);
            saveTimer = null;
        }
        doneBtn.disabled = true;
        setSaveState('Analyzing notes…');
        try {
            const response = await fetch(
                brokeAppUrl('/api/meetings/' + encodeURIComponent(meetingId) + '/done'),
                {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: csrfHeaders(),
                    body: JSON.stringify({
                        title: titleInput ? titleInput.value : '',
                        notes: notesInput ? notesInput.value : '',
                    }),
                }
            );
            const data = await readJson(response);
            if (!response.ok) {
                throw new Error(data.error || 'Could not finish the meeting');
            }
            window.location.reload();
        } catch (err) {
            doneBtn.disabled = false;
            setSaveState(err.message || 'Could not finish');
            if (typeof showToast === 'function') {
                showToast(err.message || 'Could not finish the meeting', 'error');
            }
        }
    }

    if (titleInput) {
        titleInput.addEventListener('input', scheduleSave);
    }
    if (notesInput) {
        notesInput.addEventListener('input', function () {
            refreshCounts();
            scheduleSave();
        });
        if (!isDone) {
            notesInput.focus();
            const value = notesInput.value;
            notesInput.selectionStart = value.length;
            notesInput.selectionEnd = value.length;
        }
    }
    if (doneBtn) {
        doneBtn.addEventListener('click', finishMeeting);
    }

    document.addEventListener('keydown', function (event) {
        if (isDone) return;
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            event.preventDefault();
            finishMeeting();
        }
    });

    window.addEventListener('beforeunload', function (event) {
        if (!dirty || isDone) return;
        event.preventDefault();
        event.returnValue = '';
    });

    refreshCounts();
    if (isDone) {
        setSaveState('Done');
    } else {
        setSaveState('Saved');
    }
})();
