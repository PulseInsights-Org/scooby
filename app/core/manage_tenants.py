from typing import Dict
from app.service.participants import ParticipantsManager
from app.core.utils import TranscriptWriter, BotContext, InactivityMonitor
from app.service.transcript_ingestion import TranscriptIngestion

class TenantManager():
    
    def __init__(self, 
                 bot_id,  
                 org_name, 
                 processed_audio,
                 meeting_url,
                 model,
                 recall) -> None:
        self.model = model
        self.bot_id = bot_id,
        self.meeting_url = meeting_url
        self.org_name = org_name
        self.bc = BotContext()
        self.pm = ParticipantsManager()
        self.processed_audios = processed_audio
        self.model.bot_id = self.bot_id
        self.rb = recall
        self.writer = TranscriptWriter(
                    enabled = False,
                    meeting_url =self.meeting_url,
                    org_name=None
        )
        self.monitor = InactivityMonitor(
            get_current_bot_id=self.bot_id,
            participants_manager=self.pm,
            model=self.model,
            transcript_writer=self.writer,
            bot_name="scooby",
            remove_bot=self.rb.handle_bot_removal,
            on_cleared=lambda: (self._set_inactive(), self.bc.print_active_bot()),
        )
        self.monitor.start(self.bot_id)
        self.model.org_name = org_name
    
    def _is_duplicate_audio_segment(self, start_time: float, end_time: float, speaker: str) -> bool:
        """Simple check if this exact audio segment was already processed"""
        segment_key = f"{start_time}:{end_time}:{speaker}"
        
        if segment_key in self.processed_audio:
            print(f"Duplicate audio segment detected: {start_time}s to {end_time}s from {speaker}")
            return True
            
        self.processed_audio.add(segment_key)
        return False

    def _set_inactive(self):
        # pop from the registery
        try:
            self.bc.clear()
            BotContext.remove_model_context(self.model)
        except Exception:
            pass
    
    async def remove_cleanup_ingest(self, ti):
        await BotContext.ingest_and_cleanup_transcript(
                        self.bot_id,
                        transcripts_enabled=True,
                        meeting_url=self.meeting_url,
                        ti=ti,
                        x_org_name=self.org_name,
                        transcript_writer=self.writer,
                    )
        self.pm.reset()
        self.monitor.stop()

class TenantRegistry:
    def __init__(self):
        # dict[bot_id] = TenantManager
        self._registry: Dict[str, TenantManager] = {}

    def add_manager(self, bot_id: str, manager: TenantManager):
        self._registry[bot_id] = manager

    def get_manager(self, bot_id: str) -> TenantManager:
        return self._registry.get(bot_id)

    def remove_manager(self, bot_id: str):
        self._registry.pop(bot_id)

    def list_managers(self):
        return list(self._registry.values())
