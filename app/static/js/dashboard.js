(function () {
    const orgInput = document.getElementById('orgName');
    const meetingInput = document.getElementById('meetingUrl');
    const saveTranscriptCheckbox = document.getElementById('saveTranscript');
    const addScoobyBtn = document.getElementById('addScoobyBtn');
    const addScoobyStatus = document.getElementById('addScoobyStatus');
    const summaryStatus = document.getElementById('summaryStatus');
    const summaryContent = document.getElementById('summaryContent');

    let eventSource = null;

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
        summaryContent.innerHTML = '';
        const pre = document.createElement('pre');
        pre.style.margin = '0';
        pre.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';
        pre.style.fontSize = '12px';
        pre.textContent = text || '';
        summaryContent.appendChild(pre);
        summaryContent.scrollTop = summaryContent.scrollHeight;
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
                    // We intentionally ignore bot_id in the UI; it is only
                    // included for correlation/debugging on the client side.
                    summaryText = parsed.summary || '';
                } catch (e) {
                    // Fallback: if server ever sends plain text, show it.
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

    if (addScoobyBtn) {
        addScoobyBtn.addEventListener('click', function (e) {
            e.preventDefault();
            handleAddScoobyClick();
        });
    }
})();
