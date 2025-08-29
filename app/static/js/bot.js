let audioContext;
let isModelSpeaking = false;
const BOT_TYPE = 'scooby'; // This bot only responds to scooby messages
const ORG_NAME = new URLSearchParams(window.location.search).get('org_name') || 'default';
let ws;

const pulseCoreEl = document.getElementById('pulseCore');
const waveVisualizationEl = document.getElementById('waveVisualization');

async function initAudio() {
    console.group("initAudio()");
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        console.log("🔊 AudioContext created:", audioContext);
        console.log("🔍 AudioContext state:", audioContext.state);
        console.log("ℹ️  Output sampleRate:", audioContext.sampleRate);
        console.log("ℹ️  Base latency (if supported):", audioContext.baseLatency);
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
            console.log("▶️ Resumed AudioContext from suspended");
        }
        console.log('✅ Audio context initialized for Scooby AI');
    } catch (error) {
        console.error('❌ Failed to initialize audio context:', error);
    } finally {
        console.groupEnd();
    }
}

function connectWebSocket(org_name) { 
    console.group("connectWebSocket()");
    const wsUrl = `wss://567dccc1b88f.ngrok-free.app/ws/${org_name}`;
    console.log("🌐 Connecting to:", wsUrl);
    ws = new WebSocket(wsUrl);
    
    ws.onopen = function() {
        console.log('✅ WS open');
        updateStatus('connected');
    };
    
    ws.onmessage = function(event) {
        console.groupCollapsed("📩 WS message");

        console.log("Raw event.data typeof:", typeof event.data);
        console.log("Preview:", typeof event.data === "string" ? event.data.slice(0, 80) : event.data);
        const preview = typeof event.data === 'string'
            ? event.data.slice(0, 200)
            : '[non-string payload]';
        console.log("raw:", preview, preview.length >= 200 ? '…' : '');
        try {
            const data = JSON.parse(event.data);
            console.log("✅ Parsed WS JSON:", data);
            handleWebSocketMessage(data);
        } catch(e) {
            console.error("❌ JSON parse error:", e, event.data);
        } finally {
            console.groupEnd();
        }
    };
    
    ws.onclose = function(evt) {
        console.warn('⚠️ WS close:', { code: evt.code, reason: evt.reason, wasClean: evt.wasClean });
        updateStatus('disconnected');
        setTimeout(connectWebSocket(org_name), 3000);
    };
    
    ws.onerror = function(error) {
        console.error('❌ WS error:', error);
        updateStatus('disconnected');
    };

    console.groupEnd();
}

function handleWebSocketMessage(data) {
    console.log("➡️ handleWebSocketMessage:", data);
    console.group("handleWebSocketMessage()");
    console.log("incoming:", data);

    // Only handle messages intended for this bot
    if (data.bot_type && data.bot_type !== BOT_TYPE) {
        console.log("⏭️ Ignored (bot mismatch):", data.bot_type, "expected:", BOT_TYPE);
        console.groupEnd();
        return; // Ignore messages for other bots
    }

    switch (data.type) {
        case 'status':
            console.log("📡 Status:", data.connected);
            updateStatus(data.connected ? 'connected' : 'disconnected');
            break;
            
        case 'audio':
            console.log("🎧 Audio payload received");
            console.log("🎧 Audio message:", {
                payloadType: typeof data.data,
                length: data.data ? data.data.length : 0
            });
            // Show wave animation during audio playback
            if (!isModelSpeaking) {
                showWaveVisualization(true, 'listening');
            }
            playAudio(data.data);
            break;
            
        case 'model_speaking':
            console.log("🗣️ model_speaking:", data.speaking);
            isModelSpeaking = data.speaking;
            if (data.speaking) {
                updateStatus('speaking');
                showWaveVisualization(true, 'speaking');
                audioScheduleTime = audioContext ? audioContext.currentTime : 0;
                console.log("🎼 Reset audioScheduleTime to", audioScheduleTime);
            } else {
                updateStatus('connected');
                showWaveVisualization(false);
            }
            break;
            
        default:
            console.log("ℹ️ Unhandled WS type:", data.type);
            console.warn('❓ Unknown message type:', data.type, data);
    }
    console.groupEnd();
}
                     
let audioScheduleTime = 0;

function playAudio(base64Data) {
    console.group("playAudio()");
    console.time("playAudio_total");
    console.log("▶️ base64 length:", base64Data ? base64Data.length : 0);

    if (!audioContext) {
        console.error('❌ Audio context not initialized');
        console.groupEnd();
        return;
    }
    
    try {
        if (typeof base64Data !== 'string' || base64Data.length === 0) {
            console.error("❌ Invalid base64 payload:", base64Data);
            console.groupEnd();
            return;
        }

        console.time("atob_decode");
        const raw = atob(base64Data);
        console.timeEnd("atob_decode");
        console.log("🔎 Decoded raw length:", raw.length);

        console.time("raw_to_uint8");
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) {
            bytes[i] = raw.charCodeAt(i);
        }
        console.timeEnd("raw_to_uint8");
        console.log("📊 Uint8Array length:", bytes.length);

        console.time("build_wav");
        const wav = createWAVHeaderAndBlob(bytes, 24000);
        console.timeEnd("build_wav");
        console.log("📀 WAV total bytes:", wav.byteLength);

        console.time("decodeAudioData");
        
        audioContext.decodeAudioData(
            wav.buffer,
            (decodedBuffer) => {
                console.timeEnd("decodeAudioData");
                console.log("✅ decodeAudioData success:", {
                    duration: decodedBuffer.duration,
                    numberOfChannels: decodedBuffer.numberOfChannels,
                    sampleRate: decodedBuffer.sampleRate,
                    length: decodedBuffer.length
                });
                scheduleAudioChunk(decodedBuffer);
                console.timeEnd("playAudio_total");
                console.groupEnd();
            },
            (err) => {
                console.timeEnd("decodeAudioData");
                console.error("❌ decodeAudioData error:", err);
                console.timeEnd("playAudio_total");
                console.groupEnd();
            }
        );

    } catch (e) {
        console.error("❌ Error processing audio:", e);
        console.timeEnd("playAudio_total");
        console.groupEnd();
    }
}

function scheduleAudioChunk(audioBuffer) {
    console.group("scheduleAudioChunk()");
    try {
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        
        // Enhanced animation control during audio playback
        source.onended = () => {
            console.log("🔚 Source ended at", audioContext.currentTime.toFixed(3));
            // Hide wave animation when audio chunk ends (if not still speaking)
            if (!isModelSpeaking) {
                showWaveVisualization(false);
            }
        };

        const currentTime = audioContext.currentTime;
        const startTime = Math.max(currentTime, audioScheduleTime);
        
        console.log("🕒 Timing:", {
            currentTime,
            audioScheduleTime,
            chosenStart: startTime,
            duration: audioBuffer.duration
        });

        source.start(startTime);
        audioScheduleTime = startTime + audioBuffer.duration;
        
        console.log(`✅ Scheduled chunk: duration=${audioBuffer.duration.toFixed(3)}s, nextSlot=${audioScheduleTime.toFixed(3)}`);
    } catch (e) {
        console.error("❌ scheduleAudioChunk failed:", e);
    } finally {
        console.groupEnd();
    }
}

function createWAVHeaderAndBlob(pcmBytes, sampleRate = 24000) {
    console.group("createWAVHeaderAndBlob()");
    console.log("🔧 PCM size:", pcmBytes.length, "sampleRate:", sampleRate);
    const numChannels = 1;
    const bitsPerSample = 16;
    const byteRate = sampleRate * numChannels * bitsPerSample / 8;
    const blockAlign = numChannels * bitsPerSample / 8;
    const dataSize = pcmBytes.length;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    const writeString = (offset, str) => {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset + i, str.charCodeAt(i));
        }
    };

    // WAV header
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); // Fixed: should be 1 for mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitsPerSample, true);
    writeString(36, 'data');
    view.setUint32(40, dataSize, true);

    new Uint8Array(buffer, 44).set(pcmBytes);
    console.log("✅ WAV header ok, total size:", buffer.byteLength);
    console.groupEnd();
    return new Uint8Array(buffer);
}

function updateStatus(type) {
    console.log("🔔 updateStatus:", type);
    pulseCoreEl.className = `pulse-core ${type}`;
    
    // Add pulse animation for speaking state
    if (type === 'speaking') {
        addPulseAnimation();
    } else {
        removePulseAnimation();
    }
}

function addPulseAnimation() {
    // Create pulse animation effect for the core
    if (!pulseCoreEl.classList.contains('pulse-animation')) {
        pulseCoreEl.classList.add('pulse-animation');
        // Add dynamic CSS for pulse effect
        if (!document.getElementById('pulse-style')) {
            const style = document.createElement('style');
            style.id = 'pulse-style';
            style.textContent = `
                .pulse-core.pulse-animation {
                    animation: pulseEffect 1s ease-in-out infinite;
                }
                
                @keyframes pulseEffect {
                    0% {
                        transform: scale(1);
                        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
                    }
                    50% {
                        transform: scale(1.1);
                        box-shadow: 0 6px 25px rgba(255, 193, 7, 0.4);
                    }
                    100% {
                        transform: scale(1);
                        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
                    }
                }
            `;
            document.head.appendChild(style);
        }
    }
}

function removePulseAnimation() {
    pulseCoreEl.classList.remove('pulse-animation');
}

function showWaveVisualization(show, type = 'listening') {
    console.log(`🌊 showWaveVisualization show=${show}, type=${type}`);
    if (show) {
        waveVisualizationEl.classList.add('active');
        const waveBars = waveVisualizationEl.querySelectorAll('.wave-bar');
        waveBars.forEach(bar => {
            if (type === 'speaking') {
                bar.classList.add('speaking');
            } else {
                bar.classList.remove('speaking');
            }
        });
    } else {
        waveVisualizationEl.classList.remove('active');
        const waveBars = waveVisualizationEl.querySelectorAll('.wave-bar');
        waveBars.forEach(bar => {
            bar.classList.remove('speaking');
        });
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    console.group("DOMContentLoaded");
    console.log("📂 DOM ready, init audio + WS…");
    await initAudio();
    connectWebSocket(ORG_NAME);
    console.groupEnd();
});

document.addEventListener('click', async function() {
    console.log("👆 Click: resume AudioContext if suspended");
    if (audioContext && audioContext.state === 'suspended') {
        await audioContext.resume();
        console.log("▶️ AudioContext resumed on user gesture");
    }
});