import uuid
from typing import Dict, Optional, Union

import os
import httpx
import logging

logger = logging.getLogger(__name__)

class TranscriptIngestion:
    def __init__(self, org_name: str, base_url: str = "https://dev.pulse-api.getpulseinsights.ai", timeout: float = 30.0):
        self.org_name = org_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        logger.debug("TranscriptIngestion initialized")

    async def init_intake(self) -> Dict:
        url = f"{self.base_url}/api/intakes/init"
        headers = {"x-org-name": self.org_name, "x-idempotency-key": str(uuid.uuid4())}
        try:
            logger.info("[init_intake] POST %s", url)
            logger.debug("[init_intake] headers=%s", headers)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers)
            logger.info("[init_intake] Response %s %s", r.status_code, r.text)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            logger.error("[init_intake] Timeout after %ss", self.timeout)
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            logger.exception("[init_intake] Exception: %s", e)
            return {"success": False, "message": str(e)}

    async def upload_file(self, intake_id: Union[str, int], file_path: str) -> Dict:
        url = f"{self.base_url}/api/upload/file/{intake_id}"
        headers = {"x-org-name": self.org_name}
        try:
            filename = os.path.basename(file_path)
            file_size = None
            try:
                file_size = os.path.getsize(file_path)
            except Exception:
                file_size = None
            logger.info("[upload_file] POST %s", url)
            logger.debug("[upload_file] headers=%s", headers)
            logger.info("[upload_file] file name=%s size=%s bytes", filename, file_size)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (filename, f)}
                    r = await client.post(url, headers=headers, files=files)
            logger.info("[upload_file] Response %s %s", r.status_code, r.text)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            logger.error("[upload_file] Timeout after %ss", self.timeout)
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            logger.exception("[upload_file] Exception: %s", e)
            return {"success": False, "message": str(e)}

    async def get_intake_status(self, intake_id: Union[str, int]) -> Dict:
        url = f"{self.base_url}/api/intakes/{intake_id}"
        headers = {"x-org-name": self.org_name}
        try:
            logger.info("[get_intake_status] GET %s", url)
            logger.debug("[get_intake_status] headers=%s", headers)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(url, headers=headers)
            logger.info("[get_intake_status] Response %s %s", r.status_code, r.text)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            logger.error("[get_intake_status] Timeout after %ss", self.timeout)
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            logger.exception("[get_intake_status] Exception: %s", e)
            return {"success": False, "message": str(e)}

    async def finalize_intake(self, intake_id: Union[str, int]) -> Dict:
        url = f"{self.base_url}/api/intakes/{intake_id}/finalize"
        headers = {"x-org-name": self.org_name}
        try:
            logger.info("[finalize_intake] POST %s", url)
            logger.debug("[finalize_intake] headers=%s", headers)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, headers=headers)
            logger.info("[finalize_intake] Response %s %s", r.status_code, r.text)
            if r.status_code in (200, 201):
                return {"success": True, "data": r.json()}
            return {"success": False, "message": r.text, "status_code": r.status_code}
        except httpx.TimeoutException:
            logger.error("[finalize_intake] Timeout after %ss", self.timeout)
            return {"success": False, "message": "Timeout", "status_code": 408}
        except Exception as e:
            logger.exception("[finalize_intake] Exception: %s", e)
            return {"success": False, "message": str(e)}

    async def ingest_transcript(self, x_org_name: str, transcript_filepath: str) -> Dict:
        self.org_name = x_org_name
        logger.info("[ingest_transcript] Start ingest for tenant_id=%s org_id=%s file=%s", x_org_name, transcript_filepath)
        init_res = await self.init_intake()
        logger.info("[ingest_transcript] init_intake result=%s", init_res)
        
        if not init_res.get("success"):
            return {"step": "init_intake", **init_res}

        data = init_res.get("data") or {}
        intake_id = data.get("intake_id") or data.get("id") or data.get("intakeId")
        if not intake_id:
            logger.error("[ingest_transcript] Missing intake_id in init response: %s", data)
            return {"success": False, "step": "init_intake", "message": "Missing intake_id in response"}

        upload_res = await self.upload_file(intake_id, transcript_filepath)
        logger.info("[ingest_transcript] upload_file result=%s", upload_res)
        if not upload_res.get("success"):
            return {"step": "upload_file", **upload_res, "intake_id": intake_id}

        status_res = await self.get_intake_status(intake_id)
        logger.info("[ingest_transcript] get_intake_status result=%s", status_res)
        if not status_res.get("success"):
            return {"step": "get_intake_status", **status_res, "intake_id": intake_id}

        finalize_res = await self.finalize_intake(intake_id)
        logger.info("[ingest_transcript] finalize_intake result=%s", finalize_res)
        return {
            "success": finalize_res.get("success", False),
            "step": "finalize_intake",
            "intake_id": intake_id,
            "init": init_res,
            "upload": upload_res,
            "status": status_res,
            "finalize": finalize_res,
        }


# if __name__ == "__main__":
#     # Simple local test runner with hardcoded values
#     import asyncio
#     import os
#     import logging

#     # Ensure logs are visible when running this file directly
#     logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

#     ORG_ID = "832697dd-a913-405d-907a-a0c177d0746f"
#     TENANT_ID = "3do64"
#     BASE_URL = "https://dev.pulse-api.getpulseinsights.ai"

#     # Use the provided transcript file directly for testing
#     TRANSCRIPT_PATH = r"c:\\Users\\91948\\Desktop\\scooby\\app\\transcripts\\Meeting_C.txt"

#     ti = TranscriptIngestion(org_id=ORG_ID, base_url=BASE_URL, timeout=30.0)

#     async def _run():
#         # Step-by-step tests commented out to test full pipeline instead
#         # print("-- init_intake --")
#         # init_res = await ti.init_intake()
#         # print(init_res)
#         # if not init_res.get("success"):
#         #     return
#         # data = init_res.get("data") or {}
#         # intake_id = data.get("intake_id") or data.get("id") or data.get("intakeId")
#         # print("intake_id:", intake_id)
#         # if not intake_id:
#         #     return
#         # if TRANSCRIPT_PATH and os.path.exists(TRANSCRIPT_PATH):
#         #     print("-- upload_file --", TRANSCRIPT_PATH)
#         #     up_res = await ti.upload_file(intake_id, TRANSCRIPT_PATH)
#         #     print(up_res)
#         # else:
#         #     print(f"Transcript file not found at: {TRANSCRIPT_PATH}; skipping upload_file")
#         # print("-- get_intake_status --")
#         # st_res = await ti.get_intake_status(intake_id)
#         # print(st_res)
#         # print("-- finalize_intake --")
#         # fin_res = await ti.finalize_intake(intake_id)
#         # print(fin_res)

#         # Full pipeline test
#         # print("-- ingest_transcript (pipeline) --")
#         # if not (TRANSCRIPT_PATH and os.path.exists(TRANSCRIPT_PATH)):
#         #     print(f"Transcript file not found at: {TRANSCRIPT_PATH}")
#         #     return
#         # pipeline_res = await ti.ingest_transcript(ORG_ID, TENANT_ID, TRANSCRIPT_PATH)
#         # print(pipeline_res)

#     # asyncio.run(_run())
