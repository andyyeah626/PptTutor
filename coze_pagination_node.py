import re
import json


async def main(args):
    params = args.params
    raw = params.get("raw_text")

    text = ""
    if isinstance(raw, dict):
        text = raw.get("data") or raw.get("content") or ""
    elif isinstance(raw, str):
        s = raw.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                text = obj.get("data") or obj.get("content") or s
            except json.JSONDecodeError:
                text = s
        else:
            text = s
    else:
        text = str(raw or "")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()

    MAX_BLOCK = 2500
    MIN_BODY = 60  # 过短块视为误切，合并到上一页

    def split_long(body, page_index):
        if len(body) <= MAX_BLOCK:
            return [{"page_index": page_index, "raw_block": body}]
        out, start, sub = [], 0, 1
        while start < len(body):
            chunk = body[start : start + MAX_BLOCK]
            idx = page_index if sub == 1 else float(f"{page_index}.{sub}")
            out.append({"page_index": idx, "raw_block": chunk})
            start += MAX_BLOCK
            sub += 1
        return out

    def is_junk_body(body):
        s = body.strip()
        if len(s) < MIN_BODY:
            return True
        if re.fullmatch(r"[\d\s\W]+", s):
            return True
        if re.fullmatch(r"(?:Seq|Ack)\s*=\s*\d+", s, re.I):
            return True
        return False

    def strip_leading_footer(body):
        return re.sub(r"^\d{1,2}\s*\n{2,}", "", body.strip())

    # 华工课件：页脚页码前后通常有 >=3 个换行（比图表里的 \n\n0\n\n 更宽松但仍过滤大部分噪音）
    SLIDE_FOOTER_RE = re.compile(r"\n{3,}(\d{1,2})\n{3,}")

    blocks = []
    parts = SLIDE_FOOTER_RE.split(text)

    if len(parts) >= 3:
        first = strip_leading_footer(parts[0].strip())
        if first and not is_junk_body(first):
            blocks.append(first)

        for i in range(1, len(parts), 2):
            try:
                footer_num = int(parts[i])
            except ValueError:
                continue
            if footer_num < 2 or footer_num > 55:
                continue
            body = strip_leading_footer((parts[i + 1] if i + 1 < len(parts) else "").strip())
            if body and not is_junk_body(body):
                blocks.append(body)
        split_method = "slide_footer_strict"
    else:
        blocks = [text] if text else []
        split_method = "fallback_whole"

    # 合并误切的短块到上一页
    merged = []
    for b in blocks:
        if merged and (is_junk_body(b) or len(b) < MIN_BODY):
            merged[-1] = merged[-1] + "\n\n" + b
        elif not merged:
            if not is_junk_body(b):
                merged.append(b)
        else:
            merged.append(b)

    pages = []
    for i, body in enumerate(merged, 1):
        pages.extend(split_long(body, i))

    if not pages and text:
        pages = [{"page_index": 1, "raw_block": text[:MAX_BLOCK]}]
        split_method = "fallback_single"

    return {
        "pages_raw": pages,
        "page_count": len(pages),
        "char_count": len(text),
        "split_method": split_method,
        "expected_slides_hint": 52,
    }
