"""PPT_Extract API for Coze workflow HTTP node."""

from __future__ import annotations

import os

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.extractor import extract_pptx_bytes

app = FastAPI(title="PptTutor Extract", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "30")) * 1024 * 1024


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(400, "Only .pptx files are supported")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_BYTES // 1024 // 1024} MB)")

    try:
        result = extract_pptx_bytes(data)
        return result
    except Exception as e:
        return {
            "success": False,
            "total_pages": 0,
            "pages": [],
            "warnings": [str(e)],
            "raw_char_count": 0,
            "split_method": "python-pptx",
        }


@app.post("/extract/url")
async def extract_from_url(request: Request):
    """
    Optional: Coze passes a temporary file URL from start.file.
    Supported inputs:
    - query: /extract/url?url=https://...
    - json body: {"url": "https://..."}
    - form body: url=https://...
    """
    import httpx

    try:
        # 1) Prefer query string to avoid workflow body-template issues.
        url = request.query_params.get("url")

        # 2) Fallback to JSON body.
        if not url:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    url = body.get("url")
            except Exception:
                pass

        # 3) Fallback to form body.
        if not url:
            try:
                form = await request.form()
                url = form.get("url")
            except Exception:
                pass

        if not url:
            raise HTTPException(400, "Missing url")

        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.content
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response is not None else "unknown"
            snippet = e.response.text[:200] if e.response is not None else ""
            return {
                "success": False,
                "total_pages": 0,
                "pages": [],
                "warnings": [f"download failed: HTTP {status_code}; {snippet}"],
                "raw_char_count": 0,
                "split_method": "python-pptx",
            }
        except httpx.HTTPError as e:
            return {
                "success": False,
                "total_pages": 0,
                "pages": [],
                "warnings": [f"download failed: {str(e)}"],
                "raw_char_count": 0,
                "split_method": "python-pptx",
            }

        if len(data) > MAX_BYTES:
            raise HTTPException(413, "File too large")

        return extract_pptx_bytes(data)
    except HTTPException:
        raise
    except Exception as e:
        return {
            "success": False,
            "total_pages": 0,
            "pages": [],
            "warnings": [str(e)],
            "raw_char_count": 0,
            "split_method": "python-pptx",
        }
