# PptTutor — PPT 提取服务（python-pptx）

为扣子（Coze）工作流提供 **按 Slide 精确分页** 的 `.pptx` 解析 API，替代 Read + 正则分页。

## 快速启动

```bash
cd d:\PptTutor
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install httpx
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：http://127.0.0.1:8000/health

本地试解析：

```bash
curl -X POST http://127.0.0.1:8000/extract -F "file=@Chapter3.2.pptx"
```

## 部署到公网（供扣子 HTTP 节点调用）

任选其一：

| 方式 | 说明 |
|------|------|
| 火山引擎 / 阿里云 轻量服务器 | `uvicorn` + systemd，配 HTTPS（Caddy/Nginx） |
| Railway / Render / Fly.io | 连 GitHub 自动部署 |
| 内网穿透 | ngrok / cloudflared，仅开发调试 |

环境变量：

- `MAX_UPLOAD_MB`：默认 30

## 扣子工作流（WF1 新版）

```
开始(file, course_name)
    → HTTP 请求 POST /extract  (或 /extract/url)
    → 选择器 success == true ?
         是 → 批处理(pages[]) → 大模型(逐页 enrich 可选) → 总结 → 结束
         否 → 结束(错误信息)
```

**不再需要**：Read 节点、分页代码节点。

## API 响应格式

与 WF1 结束节点 schema 一致：

```json
{
  "success": true,
  "total_pages": 52,
  "pages": [
    {
      "page_index": 1,
      "page_title": "COMPUTER NETWORKS 2026 Spring",
      "original_text": "...",
      "slide_notes": "",
      "detected_language": "mixed"
    }
  ],
  "warnings": [],
  "raw_char_count": 12000,
  "split_method": "python-pptx"
}
```
