"""PPT_Extract API for Coze workflow HTTP node."""

from __future__ import annotations

import os
import json

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

# .pptx is a ZIP archive; magic bytes PK\x03\x04
_PPTX_ZIP_MAGIC = b"PK\x03\x04"
# Legacy .ppt (OLE compound document)
_PPT_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _failure(warnings: list[str]) -> dict:
    return {
        "success": False,
        "total_pages": 0,
        "pages": [],
        "warnings": warnings,
        "raw_char_count": 0,
        "split_method": "python-pptx",
    }


def _diagnose_download(data: bytes, source_url: str = "") -> list[str] | None:
    """Return warnings if bytes are not a valid .pptx; None if OK."""
    if not data:
        return ["downloaded file is empty"]

    if data[:4] == _PPTX_ZIP_MAGIC:
        return None

    hints: list[str] = ["downloaded content is not a .pptx file (missing ZIP signature)"]

    if data[:8] == _PPT_OLE_MAGIC:
        hints.append(
            "detected legacy .ppt format; please re-save/upload as .pptx in PowerPoint"
        )
    elif data[:3] == b"\xff\xd8\xff":
        hints.append(
            "detected JPEG image; Coze file URL may be a preview link, not the original .pptx"
        )
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        hints.append(
            "detected PNG image; Coze file URL may be a preview link, not the original .pptx"
        )
    elif data[:15].lower().startswith(b"<!doctype") or data[:5].lower() == b"<html":
        hints.append("detected HTML page instead of a presentation file")
    elif data[:1] in (b"{", b"["):
        hints.append("detected JSON/text response instead of a presentation file")

    if source_url:
        if ".pptx" not in source_url.lower() and ".ppt" in source_url.lower():
            hints.append(
                "URL filename looks like .ppt; python-pptx only supports .pptx"
            )
        if "image.image" in source_url or "tplv-" in source_url:
            hints.append(
                "URL looks like an image/CDN transform link; use the original file download URL"
            )

    hints.append(f"first_bytes={data[:16]!r}")
    return hints


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

    bad = _diagnose_download(data, file.filename or "")
    if bad:
        return _failure(bad)

    try:
        return extract_pptx_bytes(data)
    except Exception as e:
        msg = str(e)
        if "not a zip file" in msg.lower():
            return _failure(
                [
                    "file is not a valid .pptx zip archive",
                    "if using Coze: ensure start.file points to original .pptx, not preview image URL",
                ]
            )
        return _failure([msg])


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

        # Coze variable interpolation may include leading/trailing whitespace/newlines.
        if isinstance(url, str):
            url = url.strip().strip("\"'")
            # Some workflow nodes pass a JSON object as string, e.g. {"file_url":"https://..."}.
            if url.startswith("{") and url.endswith("}"):
                try:
                    payload = json.loads(url)
                    if isinstance(payload, dict):
                        url = payload.get("url") or payload.get("file_url") or payload.get("download_url") or ""
                except Exception:
                    pass
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return {
                "success": False,
                "total_pages": 0,
                "pages": [],
                "warnings": [f"invalid url: {repr(url)[:200]}"],
                "raw_char_count": 0,
                "split_method": "python-pptx",
            }

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

        bad = _diagnose_download(data, url)
        if bad:
            return _failure(bad)

        try:
            return extract_pptx_bytes(data)
        except Exception as e:
            msg = str(e)
            if "not a zip file" in msg.lower():
                return _failure(
                    [
                        "file is not a valid .pptx zip archive",
                        "Coze temporary URLs often return .ppt preview/images; upload .pptx or use raw download link",
                    ]
                )
            return _failure([msg])
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
