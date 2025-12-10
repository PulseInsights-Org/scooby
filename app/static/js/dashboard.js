(function () {
    const orgInput = document.getElementById('orgName');
    const meetingInput = document.getElementById('meetingUrl');
    const saveTranscriptCheckbox = document.getElementById('saveTranscript');
    const addScoobyBtn = document.getElementById('addScoobyBtn');
    const addScoobyStatus = document.getElementById('addScoobyStatus');
    const summaryStatus = document.getElementById('summaryStatus');
    const summaryContent = document.getElementById('summaryContent');
    const removeScoobyBtn = document.getElementById('removeScoobyBtn');

    const STORAGE_KEY = 'scooby_dashboard_state';

    let eventSource = null;

    function loadState() {
        try {
            const raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                return null;
            }
            return JSON.parse(raw);
        } catch (e) {
            console.warn('Failed to load dashboard state', e);
            return null;
        }
    }

    function saveState(partial) {
        try {
            const existing = loadState() || {};
            const next = Object.assign({}, existing, partial || {});
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        } catch (e) {
            console.warn('Failed to save dashboard state', e);
        }
    }

    function clearState() {
        try {
            window.localStorage.removeItem(STORAGE_KEY);
        } catch (e) {
            console.warn('Failed to clear dashboard state', e);
        }
    }

    function resetDashboardFromInactive() {
        // Clear any persisted state
        clearState();

        // Reset inputs
        if (orgInput) orgInput.value = '';
        if (meetingInput) meetingInput.value = '';
        if (saveTranscriptCheckbox) saveTranscriptCheckbox.checked = true;

        // Reset status text
        setAddScoobyStatus('', null);
        setSummaryStatus('Waiting for summary...');

        // Clear summary content
        if (summaryContent) {
            summaryContent.innerHTML = '';
        }

        // Close any active SSE connection
        if (eventSource) {
            try {
                eventSource.close();
            } catch (e) {
                console.warn('Error closing EventSource while resetting dashboard', e);
            }
            eventSource = null;
        }
    }

    function setAddScoobyStatus(message, type) {
        addScoobyStatus.textContent = message || '';
        addScoobyStatus.classList.remove('ok', 'error');
        if (type) {
            addScoobyStatus.classList.add(type);
        }
    }

    function setSummaryStatus(label) {
        if (summaryStatus) {
            summaryStatus.textContent = label;
        }
    }

    function renderSummary(text) {
        const value = String(text || '');
        summaryContent.innerHTML = '';

        if (!value.trim()) {
            return;
        }

        const blocks = value.split(/\n\s*\n/);
        for (let i = 0; i < blocks.length; i++) {
            const block = blocks[i];
            if (!block.trim()) {
                continue;
            }
            const p = document.createElement('p');
            p.style.margin = '0 0 8px 0';
            p.textContent = block.trim();
            summaryContent.appendChild(p);
        }

        summaryContent.scrollTop = summaryContent.scrollHeight;
        saveState({ summaryText: value });
    }

    function startSummaryStream() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        try {
            eventSource = new EventSource('/api/summary_stream');
            setSummaryStatus('Listening for updates...');

            eventSource.onmessage = function (event) {
                const raw = event.data || '';
                if (!raw.trim()) {
                    return;
                }

                let summaryText = '';
                try {
                    const parsed = JSON.parse(raw);
                    summaryText = parsed.summary || '';
                } catch (e) {
                    console.warn('Non-JSON SSE payload for summary_stream', e);
                    summaryText = raw;
                }

                if (!summaryText.trim()) {
                    return;
                }

                renderSummary(summaryText);
                setSummaryStatus('Summary updated');
            };

            eventSource.onerror = function (err) {
                console.error('Summary SSE error', err);
                setSummaryStatus('Disconnected from summary stream');
            };
        } catch (e) {
            console.error('Failed to start summary EventSource', e);
            setSummaryStatus('Failed to start summary stream');
        }
    }

    async function syncWithBackendBotStatus() {
        try {
            const resp = await fetch('/api/bot_status', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json'
                }
            });

            if (!resp.ok) {
                return;
            }

            const data = await resp.json();
            const state = loadState() || {};
            const activeBotId = data && data.bot_id ? String(data.bot_id) : null;

            if (activeBotId && state.botId && String(state.botId) === activeBotId) {
                setAddScoobyStatus('Scooby is active. Bot ID: ' + activeBotId, 'ok');
                if (state.summaryText) {
                    renderSummary(state.summaryText);
                }
                if (!eventSource) {
                    startSummaryStream();
                }
            } else if (!activeBotId) {
                // No active bot on the backend -> clear all cached UI
                resetDashboardFromInactive();
            }
        } catch (e) {
            console.warn('Failed to sync bot status with backend', e);
        }
    }

    async function handleAddScoobyClick() {
        const orgName = (orgInput.value || '').trim();
        const meetingUrl = (meetingInput.value || '').trim();
        const saveTranscript = !!saveTranscriptCheckbox.checked;

        if (!orgName || !meetingUrl) {
            setAddScoobyStatus('Please provide both organization name and meeting link.', 'error');
            return;
        }

        addScoobyBtn.disabled = true;
        setAddScoobyStatus('Adding Scooby to meeting...', null);

        try {
            const body = {
                meeting_url: meetingUrl,
                isTranscript: saveTranscript,
                x_org_name: orgName,
                saveTranscript: saveTranscript
            };

            const resp = await fetch('/add_scooby', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(body)
            });

            const data = await resp.json();

            if (!resp.ok) {
                setAddScoobyStatus(data?.message || 'Failed to add Scooby to meeting.', 'error');
                return;
            }

            if (data.bot_id) {
                setAddScoobyStatus('Scooby added to meeting. Bot ID: ' + data.bot_id, 'ok');
                saveState({
                    orgName: orgName,
                    meetingUrl: meetingUrl,
                    saveTranscript: saveTranscript,
                    botId: data.bot_id
                });
                startSummaryStream();
            } else if (data.message) {
                setAddScoobyStatus(data.message, 'error');
            } else {
                setAddScoobyStatus('Unexpected response from server.', 'error');
            }
        } catch (e) {
            console.error('Error calling /add_scooby', e);
            setAddScoobyStatus('Error adding Scooby to meeting.', 'error');
        } finally {
            addScoobyBtn.disabled = false;
        }
    }

    async function handleRemoveScoobyClick() {
        const state = loadState() || {};
        const botId = state.botId;

        // Always clear local UI/cache immediately when user clicks Remove,
        // regardless of backend state. This guarantees no stale data is shown.
        resetDashboardFromInactive();

        if (!botId) {
            // Nothing to tell backend; just inform the user.
            setAddScoobyStatus('No active Scooby bot to remove.', 'error');
            return;
        }

        removeScoobyBtn.disabled = true;
        setAddScoobyStatus('Removing Scooby from meeting...', null);

        try {
            const resp = await fetch('/remove_scooby', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ bot_id: botId })
            });

            let data = {};
            try {
                data = await resp.json();
            } catch (_) {
                data = {};
            }

            if (!resp.ok) {
                const msg = data && (data.detail || data.message);
                setAddScoobyStatus(msg || 'Failed to remove Scooby from meeting on server. Local data has been cleared.', 'error');
                return;
            }

            setAddScoobyStatus('Scooby removed from meeting.', 'ok');
            setSummaryStatus('Bot removed');
        } catch (e) {
            console.error('Error calling /remove_scooby', e);
            setAddScoobyStatus('Error removing Scooby from meeting on server. Local data has been cleared.', 'error');
        } finally {
            removeScoobyBtn.disabled = false;
        }
    }

    (function initFromState() {
        const state = loadState();
        if (!state) {
            return;
        }

        if (typeof state.orgName === 'string') {
            orgInput.value = state.orgName;
        }
        if (typeof state.meetingUrl === 'string') {
            meetingInput.value = state.meetingUrl;
        }
        if (typeof state.saveTranscript !== 'undefined') {
            saveTranscriptCheckbox.checked = !!state.saveTranscript;
        }
    })();

    if (addScoobyBtn) {
        addScoobyBtn.addEventListener('click', function (e) {
            e.preventDefault();
            handleAddScoobyClick();
        });
    }

    if (removeScoobyBtn) {
        removeScoobyBtn.addEventListener('click', function (e) {
            e.preventDefault();
            handleRemoveScoobyClick();
        });
    }

    syncWithBackendBotStatus();
})();
