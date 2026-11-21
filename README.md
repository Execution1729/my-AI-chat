# AI助手 (My AI Chat)

这是一个基于大语言模型的全栈 AI 应用，包含两种核心模式：

## ✨ 功能亮点
1. **💬 基于 DeepSeek 模型，支持自定义人设，流式输出。聊天记录持久化存储至 Supabase（PostgreSQL）。
2. **📚 基于智谱 Embedding 模型和 ChromaDB。支持上传 PDF 并基于文档内容进行检索增强问答。

## 🛠️ 技术栈
- **前端**：Streamlit
- **大模型**：DeepSeek (对话) / 智谱 glm-4-flash (生成)
- **RAG 框架**：LangChain, ChromaDB
- **数据库**：Supabase (PostgreSQL + psycopg2 直连)
- **部署**：Streamlit Community Cloud

## 🚀 在线体验
[[点击这里访问我的应用](https://my-ai-chat-2917.streamlit.app/)]
