from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
import os
import logging
import base64
import io
import asyncio
import json
from typing import Optional, Set, Dict

from PIL import Image
import imagehash

from app.service.recall_bot import RecallBot
from app.core.manage_connections import ConnectionManager
from app.service.participants import ParticipantsManager
from app.core.utils import TranscriptWriter, BotContext, InactivityMonitor
from app.service.transcript_ingestion import TranscriptIngestion
from app.service.transcript_buffer import TranscriptBuffer
from app.service.summarization_service import SummarizationService
from app.service.summary_storage import SummaryStorage
from app.core.config import get_config
from app.service.screenshare_buffer import ScreenshareRedisBuffer
from app.service.screenshare_s3 import ScreenshareS3
from app.service.screenshare_storage import ScreenshareStorage
from app.service.screen_analysis_service import ScreenAnalysisService

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

cm = ConnectionManager()
rb = RecallBot()
participants_manager = ParticipantsManager()
bot_context = BotContext()
screenshare_buffer = ScreenshareRedisBuffer()
screenshare_s3 = ScreenshareS3()
screenshare_storage = ScreenshareStorage()
screen_analysis_service = ScreenAnalysisService()

current_bot_id = None
current_meeting_url = None
transcripts_enabled = False
current_x_org_name = None
processed_audio_segments = set()
active_screensharers: Set[str] = set()

# Per participant state for video frame handling (for FPS/downsampling + dedupe)
participant_frame_hashes: Dict[str, Set[str]] = {}
participant_last_ts: Dict[str, float] = {}

config = get_config()
transcript_buffer: Optional[TranscriptBuffer] = None
summarization_service = SummarizationService()
summary_storage: Optional[SummaryStorage] = None

transcript_writer = TranscriptWriter(
    enabled_getter=lambda: transcripts_enabled,
    transcripts_dir=TRANSCRIPTS_DIR,
    meeting_url_getter=lambda: current_meeting_url,
    org_name=None
)

ti = TranscriptIngestion(org_name="")

def get_active_bot_id() -> Optional[str]:
    """Return the currently active Recall bot id, if any."""
    return current_bot_id

async def get_current_summary_text() -> Optional[str]:
    """Return the current global summary for the active meeting, if any."""
    global summary_storage
    if not summary_storage:
        return None
    return await summary_storage.get_current_summary()

async def get_latest_suggestion_text() -> Optional[str]:
    """Return the latest suggestion text for the active meeting, if any."""
    global summary_storage
    if not summary_storage:
        return None
    # SummaryStorage has helper to read latest suggestion block
    return await summary_storage.get_latest_suggestion()


async def get_latest_screen_analysis_text() -> Optional[str]:
    """Return the latest screen analysis text for the active meeting, if any."""
    global summary_storage
    if not summary_storage:
        return None
    return await summary_storage.get_latest_screen_analysis()


async def run_vision_screen_analysis_for_active_meeting() -> Optional[str]:
    """Run vision-based screen analysis for the currently active meeting, if any.

    This uses ScreenAnalysisService to inspect the latest screenshare-related
    event and associated frames in Redis for the active bot.
    """
    global summary_storage
    if not current_bot_id or not summary_storage:
        return None

    return await screen_analysis_service.analyze_latest_screenshare(
        bot_id=current_bot_id,
        storage=summary_storage,
    )


@router.get("/api/summary_stream")
async def summary_stream():
    """Server-Sent Events endpoint that streams the current summary when it changes.

    This uses get_current_summary_text() as the single source of truth and
    only emits an event when the summary content differs from the last sent
    value. The check interval is small (2s) to keep latency low while
    avoiding tight polling loops.
    """

    async def event_generator():
        last_payload: Optional[str] = None
        while True:
            try:
                raw_summary = await get_current_summary_text() or ""
                lines = raw_summary.splitlines()
                while lines and not lines[0].strip():
                    lines.pop(0)
                if lines and lines[0].startswith("Last Updated:"):
                    lines.pop(0)
                if lines and lines[0].startswith("="):
                    lines.pop(0)
                summary = "\n".join(lines).strip()

                payload_dict = {
                    "bot_id": current_bot_id,
                    "summary": summary,
                }
                payload = json.dumps(payload_dict)

                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
            except Exception:
                logger.exception("Error while generating summary SSE event")
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

def _is_duplicate_audio_segment(start_time: float, end_time: float, speaker: str) -> bool:
    """Simple check if this exact audio segment was already processed"""
    segment_key = f"{start_time}:{end_time}:{speaker}"
    
    if segment_key in processed_audio_segments:
        print(f"Duplicate audio segment detected: {start_time}s to {end_time}s from {speaker}")
        return True
        
    processed_audio_segments.add(segment_key)
    return False

def _set_inactive():
    global current_bot_id, current_meeting_url, transcripts_enabled, current_x_org_name
    global transcript_buffer, summary_storage
    current_bot_id = None
    current_meeting_url = None
    transcripts_enabled = False
    current_x_org_name = None
    transcript_buffer = None
    summary_storage = None
    try:
        bot_context.clear()
    except Exception:
        pass

# Inactivity monitor instance
inactivity_monitor = InactivityMonitor(
    get_current_bot_id=lambda: current_bot_id,
    participants_manager=participants_manager,
    model=None,  # No longer using Gemini model
    transcript_writer=transcript_writer,
    bot_name="scooby",
    remove_bot=rb.handle_bot_removal,
    on_cleared=lambda: (_set_inactive(), bot_context.print_active_bot()),
)

async def add_bot(meeting_url: str, is_transcript: bool = False, *, x_org_name: str) -> str | None:
    """Create a Recall bot and update local module state."""
    global current_bot_id, current_meeting_url, transcripts_enabled, current_x_org_name
    global transcript_buffer, summary_storage

    if current_bot_id is not None:
        return None
    bot_id = await rb.add_bots(meeting_url)
    if bot_id:
        current_bot_id = bot_id
        current_meeting_url = meeting_url
        transcripts_enabled = is_transcript
        current_x_org_name = x_org_name
        transcript_writer.org_name = current_x_org_name

        # Initialize buffer and storage
        transcript_buffer = TranscriptBuffer(
            max_items=config.buffer_max_items,
            max_seconds=config.buffer_max_seconds
        )
        summary_storage = SummaryStorage(
            base_dir=BASE_DIR,
            org_name=x_org_name,
            meeting_id=bot_id
        )

        try:
            bot_context.bot_id = bot_id
            bot_context.meeting_url = meeting_url
            bot_context.transcripts_enabled = is_transcript
        except Exception:
            pass
        participants_manager.reset()
        bot_context.print_active_bot()
        # Initialize inactivity tracking and start watcher
        inactivity_monitor.start(bot_id)
    return bot_id


async def _process_buffer_and_summarize():
    """Process buffered transcripts to extract events and update global summary"""
    global transcript_buffer, summary_storage

    if not transcript_buffer or transcript_buffer.is_empty():
        return

    try:
        # Get buffered items
        items = transcript_buffer.flush()
        logger.info(f"Processing {len(items)} buffered transcript items")

        # Get current summary for continuity
        current_summary = None
        if summary_storage and config.continuity_enabled:
            current_summary = await summary_storage.get_current_summary()
            if current_summary:
                logger.debug(f"Using current summary for context ({len(current_summary)} chars)")

        # Process segment: extract events + update summary
        result = await summarization_service.process_segment(items, current_summary)

        # Log suggestion (if present) and persist it via SummaryStorage
        suggestion = result.get("suggestion")
        if suggestion:
            logger.info(f"Summarization suggestion: {suggestion}")
            if summary_storage:
                await summary_storage.append_suggestion(suggestion)

        # Persist screen analysis (if present) similar to suggestions
        screen_analysis = result.get("screen_analysis")
        if screen_analysis and summary_storage:
            try:
                await summary_storage.append_screen_analysis(screen_analysis)
                logger.info("Saved screen analysis block to storage")
            except Exception:
                logger.exception("Error while appending screen analysis to storage")

        if not summary_storage:
            logger.warning("No summary storage available")
            return

        # Save events (append to timeline)
        if result.get('events'):
            await summary_storage.append_events(result['events'])
            logger.info(f"Saved {len(result['events'])} events to timeline")

        # Replace summary (global update)
        if result.get('summary'):
            await summary_storage.replace_summary(result['summary'])
            logger.info(f"Updated global summary: {len(result['summary'])} chars")

    except Exception as e:
        logger.exception(f"Error processing buffer and summarizing: {e}")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connection_id = f"ws_{id(websocket)}"
    cm.add_connection(connection_id, websocket)

    try:
        await websocket.send_json({
            "type": "status",
            "connected": True,
            "bot_type": "scooby"
        })

        while True:
            _ = await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"WebSocket {connection_id} disconnected")
        cm.remove_connection(connection_id)


@router.websocket("/api/ws/recall-realtime")
async def recall_realtime_websocket(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            message = await websocket.receive_json()
            event_type = message.get("event")
            data = message.get("data", {})

            bot_info = data.get("bot", {}) or {}
            bot_id = bot_info.get("id")

            if current_bot_id is None or bot_id != current_bot_id:
                continue

            inner = data.get("data", {}) or {}

            if event_type == "participant_events.screenshare_on":
                participant = inner.get("participant", {}) or {}
                participant_id = str(participant.get("id"))
                if participant_id:
                    active_screensharers.add(participant_id)

            elif event_type == "participant_events.screenshare_off":
                participant = inner.get("participant", {}) or {}
                participant_id = str(participant.get("id"))
                if participant_id and participant_id in active_screensharers:
                    active_screensharers.discard(participant_id)

            elif event_type == "video_separate_png.data":
                frame_type = inner.get("type")
                if frame_type != "screenshare":
                    continue

                participant = inner.get("participant", {}) or {}
                participant_id = str(participant.get("id"))
                participant_name = participant.get("name")

                if not participant_id or participant_id not in active_screensharers:
                    continue

                timestamp = inner.get("timestamp", {}) or {}
                ts_absolute = timestamp.get("absolute")
                ts_relative = timestamp.get("relative")
                buffer_b64 = inner.get("buffer")

                if not buffer_b64:
                    continue

                if not current_x_org_name or not current_bot_id:
                    continue

                # Downsample FPS to ~1 frame every 1 seconds per participant
                key = f"{current_bot_id}:{participant_id}"
                if ts_relative is not None:
                    last_ts = participant_last_ts.get(key)
                    if last_ts is not None and (ts_relative - last_ts) < 1.0:
                        continue

                try:
                    # Decode frame bytes for perceptual hashing
                    frame_bytes = base64.b64decode(buffer_b64)
                except Exception as e:
                    logger.warning(f"Failed to decode base64 frame: {e}")
                    continue

                # Initialize hash set for this participant+bot
                hashes = participant_frame_hashes.setdefault(key, set())

                try:
                    image = Image.open(io.BytesIO(frame_bytes))
                    img_hash = str(imagehash.phash(image))

                    if img_hash in hashes:
                        logger.info("[screenshare] Duplicate frame detected (skipped)")
                        continue

                    hashes.add(img_hash)
                    if ts_relative is not None:
                        participant_last_ts[key] = ts_relative
                    # Uncomment this after testing 
                    await screenshare_buffer.push_frame(
                        org_name=current_x_org_name,
                        bot_id=current_bot_id,
                        participant_id=participant_id,
                        participant_name=participant_name,
                        ts_absolute=ts_absolute,
                        ts_relative=ts_relative,
                        img_hash=img_hash,
                        image_base64=buffer_b64,
                    )
                    logger.info("Saved UNIQUE screenshare frame to Redis buffer")

                    await screenshare_s3.push_frame(
                        org_name=current_x_org_name,
                        bot_id=current_bot_id,
                        participant_id=participant_id,
                        participant_name=participant_name,
                        ts_absolute=ts_absolute,
                        ts_relative=ts_relative,
                        img_hash=img_hash,
                        image_base64=buffer_b64,
                    )
                    # comment the below block of code after testing., [not a production compatible version]
                    # file_path = screenshare_storage.save_png_frame(
                    #     org_name=current_x_org_name,
                    #     bot_id=current_bot_id,
                    #     participant_id=participant_id,
                    #     participant_name=participant_name,
                    #     timestamp_absolute=ts_absolute,
                    #     timestamp_relative=ts_relative,
                    #     image_base64=buffer_b64,
                    # )
                except Exception as e:
                    logger.warning(f"Failed uniqueness/FPS check or buffer push: {e}")

    except WebSocketDisconnect:
        logger.info("Recall realtime websocket disconnected")
    except Exception as e:
        logger.exception(f"Error in Recall realtime websocket: {e}")


@router.post("/api/webhook/recall/bot-status")
async def recall_bot_status_webhook(request: Request):
    logger.info("Received BOT STATUS webhook from Recall.ai")
    try:
        payload = await request.json()
        logger.debug(f"Bot Status Payload: {payload}")
        event_type = (payload.get("type") or payload.get("event") or "").strip() or None
        data = payload.get("data", {}) or {}
        if not event_type:
            logger.info(f"Bot Status Payload (no event/type): {payload}")

        # Accept common variants and explicit bot.* events
        normalized_event = (event_type or "").lower() if event_type else None
        is_status_event = normalized_event in {"bot.status_change", "status_change", "bot.status"} or ("status" in data or "status" in payload)

        # Map explicit bot.* events to a synthetic status when Recall sends them
        mapped_status = None
        if normalized_event and normalized_event.startswith("bot."):
            status_map = {
                "bot.joining_call": "joining_call",
                "bot.in_call": "in_call",
                "bot.in_call_not_recording": "in_call",
                "bot.in_call_recording": "in_call_recording",
                "bot.call_ended": "call_ended",
                "bot.done": "done",
                "bot.fatal": "fatal",
            }
            mapped_status = status_map.get(normalized_event)
            if mapped_status:
                is_status_event = True

        if is_status_event:
            # Extract fields from multiple possible locations
            inner_data = (data.get("data", {}) or {})
            bot_id = (
                (data.get("bot", {}) or {}).get("id")
                or inner_data.get("bot_id")
                or (inner_data.get("bot", {}) or {}).get("id")
                or data.get("bot_id")
                or data.get("id")
                or (payload.get("bot", {}) or {}).get("id")
                or payload.get("id")
            )
            status = (
                mapped_status
                or data.get("status")
                or (payload.get("bot", {}) or {}).get("status")
                or payload.get("status")
            )
            sub_code = data.get("sub_code") or payload.get("sub_code")

            logger.info(f"Bot {bot_id} status changed to: {status}")
            if bot_id is None:
                logger.debug(f"Bot Status Payload (missing bot_id): {payload}")
                # Single active bot model: fallback to current_bot_id to avoid missing cleanup
                if current_bot_id:
                    bot_id = current_bot_id
                    logger.debug(f"Falling back to current_bot_id for status handling: {bot_id}")
            if sub_code:
                logger.info(f"Sub code: {sub_code}")

            if current_bot_id and bot_id != current_bot_id:
                logger.debug(f"Ignoring status for non-current bot {bot_id}")
                return {"status": "ok"}

            if status == "joining_call":
                logger.info(f"Bot {bot_id} is joining the meeting")

            elif status == "in_call":
                logger.info(f"Bot {bot_id} successfully joined the meeting")

            elif status == "in_call_recording":
                logger.info(f"Bot {bot_id} is now recording")

            elif status == "call_ended":
                logger.info(f"Bot {bot_id} call ended")
                try:
                    # Flush remaining buffer before cleanup
                    if transcript_buffer and not transcript_buffer.is_empty():
                        logger.info("Flushing remaining buffered transcripts before cleanup")
                        await _process_buffer_and_summarize()

                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_name=current_x_org_name,
                        transcript_writer=transcript_writer,
                        logger=logger,
                    )
                    participants_manager.reset()
                    # stop inactivity monitor
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                    _set_inactive()
                except Exception:
                    logger.exception("Error while handling call_ended cleanup")
                bot_context.print_active_bot()

            elif status == "done":
                logger.info(f"Bot {bot_id} finished successfully")
                try:
                    # Flush remaining buffer before cleanup
                    if transcript_buffer and not transcript_buffer.is_empty():
                        logger.info("Flushing remaining buffered transcripts before cleanup")
                        await _process_buffer_and_summarize()

                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_name=current_x_org_name,
                        transcript_writer=transcript_writer,
                        logger=logger,
                    )
                    participants_manager.reset()
                    _set_inactive()
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Error while handling done cleanup")
                bot_context.print_active_bot()

            elif status == "fatal":
                logger.error(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    logger.error(f"Fatal error reason: {sub_code}")
                try:
                    # Flush remaining buffer before cleanup
                    if transcript_buffer and not transcript_buffer.is_empty():
                        logger.info("Flushing remaining buffered transcripts before cleanup")
                        await _process_buffer_and_summarize()

                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_name=current_x_org_name,
                        transcript_writer=transcript_writer,
                        logger=logger,
                    )
                    participants_manager.reset()
                    _set_inactive()
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Error while handling fatal cleanup")
                bot_context.print_active_bot()

            else:
                logger.warning(f"Unhandled bot status: {status}")

        else:
            logger.warning(f"Unhandled bot status event type: {event_type}")

    except Exception as e:
        logger.exception(f"Error processing bot status webhook: {e}")

    return {"status": "ok"}


@router.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    logger.info("Received REALTIME webhook from Recall.ai")
    try:
        payload = await request.json()
        logger.debug(f"Realtime Payload: {payload}")

        event_type = payload.get("event")
        data = payload.get("data", {})
        bot_info = data.get("bot", {})
        bot_id = bot_info.get("id")

        if current_bot_id is None:
            logger.debug("No current bot set; ignoring realtime event")
            return {"status": "ok"}

        if current_bot_id and bot_id != current_bot_id:
            logger.debug(f"Ignoring realtime event for non-current bot {bot_id}")
            return {"status": "ok"}

        if event_type == "transcript.data":
            inactivity_monitor.record_activity()
            inactivity_monitor.record_transcript()
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])

            start_time = words[0]["start_timestamp"]["relative"]
            end_time = words[-1]["end_timestamp"]["relative"]

            print(f"Processing audio segment: {start_time}s to {end_time}s from {speaker}")

            if _is_duplicate_audio_segment(start_time, end_time, speaker):
                print(f"Skipping duplicate audio segment from {speaker}")
                return {"status": "ok"}

            logger.info(f"Transcribed text from {speaker}: {spoken_text}")

            # Save to raw transcript file with Recall.ai timestamps
            if summary_storage:
                await summary_storage.save_transcript_line(
                    speaker=speaker,
                    text=spoken_text,
                    start_timestamp=start_time,
                    end_timestamp=end_time
                )

            # Also save via transcript_writer for backward compatibility
            transcript_writer.save_line(speaker, spoken_text)

            # Add to buffer
            if transcript_buffer:
                transcript_buffer.add(speaker, spoken_text, start_time, end_time)

                # Check if buffer should flush
                if transcript_buffer.should_flush():
                    logger.info("Buffer flush condition met, processing transcripts...")
                    await _process_buffer_and_summarize()

        elif event_type == "participant_events.join":
            inactivity_monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]

            if action == "join":
                participants_manager.add(participant_data)
                logger.info(f"Total participants: {len(participants_manager.list)}")
                bot_context.print_active_bot()

        elif event_type == "participant_events.leave":
            inactivity_monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]

            if participant_name.lower() != "scooby":
                participants_manager.mark_left(participant_id)
                p = participants_manager.get(participant_id)
                if p:
                    logger.info(f"Participant left: {p['name']}")
            bot_context.print_active_bot()

        else:
            logger.warning(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        logger.exception(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
