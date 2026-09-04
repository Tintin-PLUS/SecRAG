# DeepSeek API Integration

本项目的 RAG 生成端已固定为 DeepSeek Chat Completions API。Embedding 仍在本机 Python Sidecar 中执行；只有用户主动在 RAG 页面提问时，问题和检索出的 Top-K Context 才会发送到 DeepSeek。

## 需要准备

1. DeepSeek 平台账号。
2. 一个可用的 DeepSeek API Key。
3. 账户具备可调用 API 的余额或额度。
4. 目标 PC 能通过 HTTPS 访问 `api.deepseek.com`。
5. 公司允许将所选文档片段发送到外部 DeepSeek API。

不要把 API Key 发给他人、写进源码、提交 Git 或填写到前端页面。项目从根目录 `.env` 读取 Key，`.env` 已被 `.gitignore` 排除。

## `.env` 配置

```dotenv
LOCAL_KB_LLM_BASE_URL=https://api.deepseek.com
LOCAL_KB_LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=替换为你的真实Key
LOCAL_KB_DEEPSEEK_THINKING=disabled
LOCAL_KB_DEEPSEEK_REASONING_EFFORT=high
LOCAL_KB_LLM_TIMEOUT_SECS=300
```

可选模型：

- `deepseek-v4-flash`：默认，适合优先验证延迟和成本的 RAG。
- `deepseek-v4-pro`：适合更重的推理需求，通常成本和延迟更高。

项目不再默认使用旧的 `deepseek-chat` 或 `deepseek-reasoner` 名称。模型清单可能随 DeepSeek 服务升级而变化，正式部署前应再次核对官方文档。

## Thinking 配置

知识库问答默认：

```dotenv
LOCAL_KB_DEEPSEEK_THINKING=disabled
```

这样延迟更低，且答案主要由检索 Context 约束。如果需要更强推理：

```dotenv
LOCAL_KB_DEEPSEEK_THINKING=enabled
LOCAL_KB_DEEPSEEK_REASONING_EFFORT=high
```

`reasoning_effort` 只允许 `low`、`high`、`max`。客户端在 thinking 模式下不会发送 `temperature`。

## 运行验证

修改 `.env` 后完全退出并重新启动应用：

```powershell
cd <仓库目录>\local-kb
npm.cmd run tauri dev
```

在设置页确认：

- Provider 为 `DeepSeek Chat Completions`；
- Base URL 为 `https://api.deepseek.com`；
- Model 正确；
- API Key 显示 `CONFIGURED`；
- Thinking 与预期一致。

随后先完成真实 Embedding 索引，再进入 RAG 页面：选择与索引相同的 Embedding 模型，输入一个可由样例资料回答的问题并发送。成功时回答区显示 DeepSeek 生成文本，下方保留本地检索来源。

## 常见错误

- `401`：API Key 无效、复制不完整或已撤销。
- `402/余额相关错误`：账户余额或可用额度不足。
- `404/model not found`：模型名已变化或拼写错误，核对官方模型列表。
- `429`：达到并发或频率限制，稍后重试。
- 请求超时：网络、排队或 thinking 响应时间较长；可提高 `LOCAL_KB_LLM_TIMEOUT_SECS`。
- `API Key NOT_CONFIGURED`：`.env` 不在项目根目录、变量名错误，或修改后未重启应用。

## 数据合规边界

DeepSeek 是外部 API。发送内容包括用户问题、检索到的 Chunk 文本、文件名和 Chunk 编号。原型没有脱敏、DLP、审批、域名白名单或租户权限。在完成公司数据分级、供应商评审和出域审批前，只能使用 `sample_docs` 等模拟资料验证。

官方参考：

- `https://api-docs.deepseek.com/guides/function_calling`
- `https://api-docs.deepseek.com/api/create-chat-completion/`
- `https://api-docs.deepseek.com/guides/thinking_mode/`
