# 扣子工作流规划（python-pptx 版）

## 一、为什么要换

| 方案 | 问题 |
|------|------|
| Read + 正则分页 | 无真实 slide 边界；图表数字误切；71 vs 52 页 |
| 一次 LLM 吐 JSON | 长文档截断、解析失败 |
| **python-pptx API** | 一页一 shape 集合，`total_pages` = 真实幻灯片数 |

## 二、总体架构（3 个工作流不变）

```text
WF1 PPT_Extract     → 稳定 pages[]（本服务）
WF2 PPT_Enrich      → 中译 / 讲义 / 术语 / 习题（批处理 + String + 代码解析）
WF3 Agent 对话      → 调 WF1+WF2，按 page_index 讲解
```

## 三、WF1 新拓扑（精简）

```text
[开始]
  file: File
  course_name: String (可选)
    ↓
[HTTP 请求]  POST {你的域名}/extract
    ↓
[选择器]  body.success == true
    ├─ 是 → [批处理] 数组 = body.pages（可选，见下）
    │         └─ 批处理体：大模型 + 分析（仅当需要润色标题时）
    └─ 否 → [结束] 返回 warnings
    ↓
[结束]
  success, total_pages, pages, warnings, raw_char_count
```

### 重要说明

- **默认**：HTTP 返回的 `pages` 已可直接作为 WF1 输出，**可跳过批处理**。
- **批处理**：仅在需要 LLM 整理版式、补全空标题时，对 `pages[].original_text` 逐页处理。
- **删除节点**：read、分页、旧的大模型全文节点。

## 四、HTTP 节点配置（扣子）

### 方式 A：文件直传（推荐，若 HTTP 节点支持 File 类型）

| 项 | 值 |
|----|-----|
| 方法 | POST |
| URL | `https://你的域名/extract` |
| Body 类型 | form-data / multipart |
| 字段 file | 引用 `开始.file` |
| 超时 | 120s |

### 方式 B：URL 拉取（扣子常见）

开始节点上传后，file 常有临时 URL：

| 项 | 值 |
|----|-----|
| 方法 | POST |
| URL | `https://你的域名/extract/url` |
| Body JSON | `{"url": "{{开始.file.url}}"}`  （字段名以扣子实际为准） |

### 方式 C：代码节点中转（兜底）

若 HTTP 节点无法直接传文件，可用扣子代码节点把 file 转成 base64 再 POST（需服务端加 `/extract/base64` 端点，可按需扩展）。

## 五、结束节点映射

| 输出字段 | 引用 |
|----------|------|
| success | HTTP.body.success |
| total_pages | HTTP.body.total_pages |
| pages | HTTP.body.pages |
| warnings | HTTP.body.warnings |
| raw_char_count | HTTP.body.raw_char_count |

## 六、WF2 PPT_Enrich（下一步）

输入：`pages`（来自 WF1）

```text
批处理 item = pages[i]
  → LLM（String 输出，标签格式）
  → 代码解析
→ 代码合并 → 完整课件 JSON
```

每页 enrich 字段：`page_title_zh`, `translated_text`, `chinese_summary`, `lecture_notes`, `glossary`, `quiz`

## 七、Agent 提示词要点

1. 用户上传 PPT → 调 `PPT_Extract`
2. `success=false` → 说明 warnings，建议检查格式或重试
3. `success=true` → 调 `PPT_Enrich`（或懒加载：用户点到第 N 页再 enrich）
4. 讲解只引用 `pages[current].original_text` + 当前页 glossary
5. 「下一页」→ `page_index + 1`

## 八、成本与性能

| 指标 | 参考 |
|------|------|
| 52 页 pptx 解析 | 通常 < 3s（无 LLM） |
| WF1 无批处理 | 几乎只耗 HTTP + 存储 |
| WF2 全量 enrich | 52 次 LLM，并行 3～5 |

## 九、本地开发检查清单

- [ ] `curl /health` 返回 ok
- [ ] `curl -F file=@xxx.pptx /extract` → `total_pages` ≈ 52
- [ ] 公网 HTTPS 可在扣子访问
- [ ] WF1 试运行 Chapter3.2.pptx
- [ ] 再接 WF2 批处理 2 页试跑
