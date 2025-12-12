(function () {
    'use strict';

    // ============================================
    // DOM Elements
    // ============================================
    const elements = {
        orgInput: document.getElementById('orgName'),
        meetingInput: document.getElementById('meetingUrl'),
        saveTranscriptCheckbox: document.getElementById('saveTranscript'),
        addScoobyBtn: document.getElementById('addScoobyBtn'),
        removeScoobyBtn: document.getElementById('removeScoobyBtn'),
        addScoobyStatus: document.getElementById('addScoobyStatus'),
        summaryStatus: document.getElementById('summaryStatus'),
        summaryContent: document.getElementById('summaryContent')
    };

    // ============================================
    // Constants
    // ============================================
    const STORAGE_KEY = 'scooby_dashboard_state';

    let eventSource = null;

    // ============================================
    // State Management
    // ============================================
    function loadState() {
        try {
            const raw = window.localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (error) {
            console.warn('Failed to load dashboard state:', error);
            return null;
        }
    }

    function saveState(partial) {
        try {
            const existing = loadState() || {};
            const updated = Object.assign({}, existing, partial);
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
        } catch (error) {
            console.warn('Failed to save dashboard state:', error);
        }
    }

    function clearState() {
        try {
            window.localStorage.removeItem(STORAGE_KEY);
        } catch (error) {
            console.warn('Failed to clear dashboard state:', error);
        }
    }

    // ============================================
    // UI Updates
    // ============================================
    function setAddScoobyStatus(message, type) {
        if (!elements.addScoobyStatus) return;

        elements.addScoobyStatus.textContent = message || '';
        elements.addScoobyStatus.classList.remove('ok', 'error');
        
        if (type) {
            elements.addScoobyStatus.classList.add(type);
        }
    }

    function setSummaryStatus(label) {
        if (elements.summaryStatus) {
            elements.summaryStatus.textContent = label;
        }
    }

    function renderSummary(text) {
        if (!elements.summaryContent) return;

        const value = String(text || '').trim();
        elements.summaryContent.innerHTML = '';

        if (!value) return;

        // Split into paragraphs and render
        const blocks = value.split(/\n\s*\n/);
        blocks.forEach(block => {
            const trimmed = block.trim();
            if (!trimmed) return;

            const paragraph = document.createElement('p');
            paragraph.textContent = trimmed;
            elements.summaryContent.appendChild(paragraph);
        });

        // Auto-scroll to bottom
        elements.summaryContent.scrollTop = elements.summaryContent.scrollHeight;
        saveState({ summaryText: value });
    }

    function resetDashboard() {
        clearState();

        // Reset inputs
        if (elements.orgInput) elements.orgInput.value = '';
        if (elements.meetingInput) elements.meetingInput.value = '';
        if (elements.saveTranscriptCheckbox) elements.saveTranscriptCheckbox.checked = true;

        // Reset status
        setAddScoobyStatus('', null);
        setSummaryStatus('Waiting for summary...');

        // Clear summary with placeholder
        if (elements.summaryContent) {
            elements.summaryContent.innerHTML = `
                <div class="summary-placeholder">
                    <svg class="placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <p>No summary yet</p>
                    <p class="placeholder-subtext">Once Scooby joins the meeting, summaries will appear here automatically</p>
                </div>
            `;
        }

        // Close SSE connection
        closeEventSource();
    }

    // ============================================
    // Event Source Management
    // ============================================
    function closeEventSource() {
        if (eventSource) {
            try {
                eventSource.close();
            } catch (error) {
                console.warn('Error closing EventSource:', error);
            }
            eventSource = null;
        }
    }

    function startSummaryStream() {
        closeEventSource();

        try {
            eventSource = new EventSource('/api/summary_stream');
            setSummaryStatus('Listening for updates...');

            eventSource.onmessage = function (event) {
                const raw = event.data || '';
                if (!raw.trim()) return;

                let payload;
                try {
                    payload = JSON.parse(raw);
                } catch (error) {
                    console.warn('Non-JSON SSE payload:', error);
                    return;
                }

                const botId = payload.bot_id || null;
                const botActive = !!payload.bot_active;
                const summaryText = payload.summary || '';

                if (!botActive) {
                    // Bot is inactive according to backend -> clear local cache/UI
                    resetDashboard();
                    return;
                }

                // Bot is active
                if (botId) {
                    setAddScoobyStatus(`Scooby is active. Bot ID: ${botId}`, 'ok');
                    saveState({ botId });
                }

                if (summaryText && summaryText.trim()) {
                    renderSummary(summaryText);
                    setSummaryStatus('Summary updated');
                }
            };

            eventSource.onerror = function (error) {
                console.error('Summary SSE error:', error);
                setSummaryStatus('Disconnected from summary stream');
            };
        } catch (error) {
            console.error('Failed to start summary EventSource:', error);
            setSummaryStatus('Failed to start summary stream');
        }
    }

    // ============================================
    // API Calls
    // ============================================
    async function addScoobyToMeeting() {
        const orgName = (elements.orgInput?.value || '').trim();
        const meetingUrl = (elements.meetingInput?.value || '').trim();
        const saveTranscript = !!elements.saveTranscriptCheckbox?.checked;

        if (!orgName || !meetingUrl) {
            setAddScoobyStatus('Please provide both organization name and meeting link.', 'error');
            return;
        }

        elements.addScoobyBtn.disabled = true;
        setAddScoobyStatus('Adding Scooby to meeting...', null);

        try {
            const response = await fetch('/add_scooby', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    meeting_url: meetingUrl,
                    isTranscript: saveTranscript,
                    x_org_name: orgName,
                    saveTranscript: saveTranscript
                })
            });

            const data = await response.json();

            if (!response.ok) {
                setAddScoobyStatus(data?.message || 'Failed to add Scooby to meeting.', 'error');
                return;
            }

            if (data.bot_id) {
                setAddScoobyStatus(`Scooby added to meeting. Bot ID: ${data.bot_id}`, 'ok');
                saveState({
                    orgName,
                    meetingUrl,
                    saveTranscript,
                    botId: data.bot_id
                });
                startSummaryStream();
            } else {
                setAddScoobyStatus(data.message || 'Unexpected response from server.', 'error');
            }
        } catch (error) {
            console.error('Error calling /add_scooby:', error);
            setAddScoobyStatus('Error adding Scooby to meeting.', 'error');
        } finally {
            elements.addScoobyBtn.disabled = false;
        }
    }

    async function removeScoobyFromMeeting() {
        const state = loadState() || {};
        const botId = state.botId;

        resetDashboard();

        if (!botId) {
            setAddScoobyStatus('No active Scooby bot to remove.', 'error');
            return;
        }

        elements.removeScoobyBtn.disabled = true;
        setAddScoobyStatus('Removing Scooby from meeting...', null);

        try {
            const response = await fetch('/remove_scooby', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot_id: botId })
            });

            let data = {};
            try {
                data = await response.json();
            } catch (error) {
                console.warn('Failed to parse remove response:', error);
            }

            if (!response.ok) {
                const message = data?.detail || data?.message || 
                    'Failed to remove Scooby from meeting on server. Local data has been cleared.';
                setAddScoobyStatus(message, 'error');
                return;
            }

            setAddScoobyStatus('Scooby removed from meeting.', 'ok');
            setSummaryStatus('Bot removed');
        } catch (error) {
            console.error('Error calling /remove_scooby:', error);
            setAddScoobyStatus('Error removing Scooby from meeting on server. Local data has been cleared.', 'error');
        } finally {
            elements.removeScoobyBtn.disabled = false;
        }
    }

    // ============================================
    // Initialization
    // ============================================
    function initializeFromState() {
        const state = loadState();
        if (!state) return;

        if (typeof state.orgName === 'string') {
            elements.orgInput.value = state.orgName;
        }
        if (typeof state.meetingUrl === 'string') {
            elements.meetingInput.value = state.meetingUrl;
        }
        if (typeof state.saveTranscript !== 'undefined') {
            elements.saveTranscriptCheckbox.checked = !!state.saveTranscript;
        }
    }

    function attachEventListeners() {
        if (elements.addScoobyBtn) {
            elements.addScoobyBtn.addEventListener('click', function (event) {
                event.preventDefault();
                addScoobyToMeeting();
            });
        }

        if (elements.removeScoobyBtn) {
            elements.removeScoobyBtn.addEventListener('click', function (event) {
                event.preventDefault();
                removeScoobyFromMeeting();
            });
        }
    }

    // ============================================
    // Application Entry Point
    // ============================================
    function init() {
        initializeFromState();
        attachEventListeners();
        // Always start SSE stream; backend will drive both summary and bot status.
        startSummaryStream();
    }

    // Start the application
    init();
})();