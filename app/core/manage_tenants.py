from typing import Dict, List, Optional
from app.service.participants import ParticipantsManager
from app.core.utils import TranscriptWriter, BotContext, InactivityMonitor, get_global_transcript_writer
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
        self.bot_id = bot_id
        self.meeting_url = meeting_url
        self.org_name = org_name
        self.bc = BotContext()
        self.pm = ParticipantsManager(org_name=org_name)
        self.processed_audios = processed_audio
        self.model.bot_id = self.bot_id
        self.rb = recall
        self.writer = get_global_transcript_writer()
        # Update the global writer with current org info
        self.writer.org_name = org_name
        self.writer._meeting_url = meeting_url
        self.monitor = InactivityMonitor(
            get_current_bot_id=self.get_bot_id,
            participants_manager=self.pm,
            model=self.model,
            transcript_writer=self.writer,
            bot_name="scooby",
            remove_bot=self.rb.handle_bot_removal,
            on_cleared=lambda: (self._set_inactive(), self.bc.print_active_bot()),
        )
        self.monitor.start(self.bot_id)
        self.model.org_name = org_name
    
    def get_bot_id(self):
        return self.bot_id
    
    def _is_duplicate_audio_segment(self, start_time: float, end_time: float, speaker: str) -> bool:
        """Simple check if this exact audio segment was already processed"""
        segment_key = f"{start_time}:{end_time}:{speaker}"
        
        if segment_key in self.processed_audios:
            print(f"Duplicate audio segment detected: {start_time}s to {end_time}s from {speaker}")
            return True
            
        self.processed_audios.add(segment_key)
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
        # dict[org_name] = set of active bot_ids
        self._org_bots: Dict[str, set] = {}

    def add_manager(self, bot_id: str, manager: TenantManager):
        self._registry[bot_id] = manager
        org_name = manager.org_name
        if org_name not in self._org_bots:
            self._org_bots[org_name] = set()
        self._org_bots[org_name].add(bot_id)

    def get_manager(self, bot_id: str) -> TenantManager:
        return self._registry.get(bot_id)

    def remove_manager(self, bot_id: str):
        manager = self._registry.pop(bot_id, None)
        if manager:
            org_name = manager.org_name
            if org_name in self._org_bots:
                self._org_bots[org_name].discard(bot_id)
                if not self._org_bots[org_name]:
                    del self._org_bots[org_name]

    def list_managers(self):
        return list(self._registry.values())
