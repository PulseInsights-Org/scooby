import uuid
from typing import Dict, Optional, Union

import os
import httpx


class TranscriptIngestion:
    def __init__(self, org_id: str, base_url: str = "https://dev.pulse-api.getpulseinsights.ai", timeout: float = 30.0):
        self.org_id = org_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def init_intake(self) -> Dict:
        url = f"{self.base_url}/api/intakes/init"
        headers = {"x-org-id": self.org_id, "x-idempotency-key": str(uuid.uuid4())}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            return {"success": False, "message": str(e)}
    async def upload_file(self, intake_id: Union[str, int], file_path: str) -> Dict:
        url = f"{self.base_url}/api/upload/file/{intake_id}"
        headers = {"x-org-id": self.org_id}
        try:
            filename = os.path.basename(file_path)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (filename, f)}
                    r = await client.post(url, headers=headers, files=files)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def get_intake_status(self, intake_id: Union[str, int]) -> Dict:
        url = f"{self.base_url}/api/intakes/{intake_id}"
        headers = {"x-org-id": self.org_id}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=headers)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def finalize_intake(self, intake_id: Union[str, int]) -> Dict:
        url = f"{self.base_url}/api/intakes/{intake_id}/finalize"
        headers = {"x-org-id": self.org_id}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def ingest_transcript(self, x_org_id: str, tenant_id: str, transcript_filepath: str) -> Dict:

        self.org_id = x_org_id
        init_res = await self.init_intake()
        
        if not init_res.get("success"):
            return {"step": "init_intake", **init_res}

        data = init_res.get("data") or {}
        intake_id = data.get("intake_id") or data.get("id") or data.get("intakeId")
        if not intake_id:
            return {"success": False, "step": "init_intake", "message": "Missing intake_id in response"}

        upload_res = await self.upload_file(intake_id, transcript_filepath)
        if not upload_res.get("success"):
            return {"step": "upload_file", **upload_res, "intake_id": intake_id}

        status_res = await self.get_intake_status(intake_id)
        if not status_res.get("success"):
            return {"step": "get_intake_status", **status_res, "intake_id": intake_id}

        finalize_res = await self.finalize_intake(intake_id)
        return {
            "success": finalize_res.get("success", False),
            "step": "finalize_intake",
            "intake_id": intake_id,
            "init": init_res,
            "upload": upload_res,
            "status": status_res,
            "finalize": finalize_res,
            "tenant_id": tenant_id,
        }
 
