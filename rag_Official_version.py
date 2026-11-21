import streamlit as st
import os
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import Json
from openai import OpenAI
import tempfile
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import httpx
from supabase import create_client
from supabase.lib.client_options import ClientOptions
import uuid

# ================= 1. 基础配置 =================
st.set_page_config(page_title="AI助手", layout="wide")


# 读取 Secrets (本地测试如果用明文，这里可以自己替换)
os.environ["OPENAI_API_KEY"] = st.secrets["ZHIPU_API_KEY"]
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=ZHIPU_BASE_URL)
# 数据库配置（填入你本地的 secrets 或直接写死）
DB_HOST = st.secrets["DB_HOST"]
DB_USER = st.secrets["DB_USER"]
DB_PASS = st.secrets["DB_PASS"]
DB_PORT = "5432"

if 'information_search' not in st.session_state:
    st.session_state.information_search = "信息查询"

if 'characteristic' not in st.session_state:
    st.session_state.characteristic = "内敛且礼貌，不轻浮"

if 'current_session' not in st.session_state:
    st.session_state.current_session = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # 年 月 日 时 分 秒

if 'messages' not in st.session_state:
    st.session_state.messages = []  # streamlit的记忆，否则会导致记录丢失

if 'rag_messages' not in st.session_state:
    st.session_state.rag_messages = []
    
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database="postgres", 
        user=DB_USER, 
        password=DB_PASS, 
        port=DB_PORT
    )

def GEN_session_name():
        bj_time = datetime.now(timezone.utc) + timedelta(hours=8)
        return bj_time.strftime("%Y-%m-%d_%H-%M-%S") + "_" + str(uuid.uuid4())[:4]
    

def load_sessions(): # 去数据库查所有session_name展示历史记录
        try:
            conn = get_db_connection()
            cur = conn.cursor()
        # 注意：这里的表名如果是大写，要加双引号，比如 "Chat_History"
            cur.execute('SELECT DISTINCT session_name FROM chat_history ORDER BY session_name DESC;') # 使用 PostgreSQL 语法
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [row[0] for row in rows]
        except Exception as e:
            st.error(f"列表获取失败: {e}")
            return []

def load_session(session_name):  # 点击历史记录时把数据库的信息拉回并更新到 st.session_state
        try:
            conn = get_db_connection()
            cur = conn.cursor()  # %s 防止 SQL注入攻击
            cur.execute('SELECT characteristic, messages FROM chat_history WHERE session_name = %s;', (session_name,))
            row = cur.fetchone()
            cur.close()
            conn.close()
        
            if row:
                st.session_state.characteristic = row[0]
                st.session_state.messages = row[1] # 这里 psycopg2 会自动把 jsonb 转回 python 字典
                st.session_state.current_session = session_name
        except Exception as e:
            st.error(f"会话加载失败: {e}")

def save_session():
        if not st.session_state.current_session or len(st.session_state.messages) == 0:
            return
        if st.session_state.current_session:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
            # 使用 PostgreSQL 的 UPSERT 语法 (ON CONFLICT)
                cur.execute('''
                INSERT INTO chat_history (session_name, characteristic, messages)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_name) DO UPDATE 
                SET characteristic = EXCLUDED.characteristic, 
                    messages = EXCLUDED.messages;
            ''', (
                    st.session_state.current_session, 
                    st.session_state.characteristic, 
                    Json(st.session_state.messages) # 必须用 Json() 包装一下,数据库字段是Jsonb,列表不能存，要转
            ))
                conn.commit() # upload to database
                cur.close()
                conn.close()
            except Exception as e:
                st.error(f"保存会话失败: {e}")

def delete_session(session_name):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('DELETE FROM chat_history WHERE session_name = %s;', (session_name,))
            conn.commit()
            cur.close()
            conn.close()
        
            if session_name == st.session_state.current_session:
                st.session_state.messages = []
                st.session_state.current_session = ""
        except Exception as e:
            st.error(f"会话删除失败: {e}")

def handle_new_chat():  # 新建对话后的流程如下
        save_session()
        st.session_state.messages = []
        st.session_state.current_session = GEN_session_name()
        save_session()

@st.cache_resource(show_spinner="正在解析文档并构建向量库...")
def process_pdf(file_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(file_bytes)
        tmp_file_path = tmp_file.name

    loader = PyPDFLoader(tmp_file_path)
    documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_documents(documents)

    embeddings = OpenAIEmbeddings(model="embedding-2", openai_api_base=ZHIPU_BASE_URL)
    vectorstore = Chroma.from_documents(documents=chunks, embedding=embeddings)
    
    os.remove(tmp_file_path)
    return vectorstore


with st.sidebar:
    st.header("⚙️ 模式选择")
    app_mode = st.radio("单击以选择:", ["💬 一起聊聊天吧 ", "📚 文档内容解疑 (RAG)"])
    
    st.divider()

if app_mode == "💬 一起聊聊天吧 ":
    st.title("💬 Dear DeepSeek")
    system_prompt = "你是DeepSeek,内敛礼貌，不轻浮，能与人共情却又带有一丝理性。"
    with st.sidebar:  # 网页面板设定
        st.button("新建对话",width = "stretch",on_click=handle_new_chat)
        st.text("会话历史")
        session_list = load_sessions()
        for session in session_list:
            col1,col2 = st.columns([4,1])
            with col1:
                def handle_load(s_name=session):
                    save_session()
                    load_session(s_name)
                st.button(session,width="stretch",key=f"load_{session}",on_click=handle_load)
            with col2:
                def handle_delete(s_name=session):
                    delete_session(s_name)
                    st.rerun()
                st.button("❌️",width="stretch",key=f"delete_{session}",on_click=handle_delete)
        st.divider()   
        st.text_input("信息查询",placeholder = "请输入查询信息")
        st.text_area("性格",placeholder = "请输入性格",key ="characteristic")

    st.title("")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
               
    if prompt := st.chat_input("今天有什么可以帮到您的？"):
        st.session_state.messages.append({"role":"user","content":prompt})
        with st.chat_message("user"):
            st.markdown(prompt) # 显示prompt
        with st.chat_message("assistant"):
            response = client.chat.completions.create(
                model="glm-4-flash",
                messages=[
                {"role": "system", "content": system_prompt},
                *st.session_state.messages
                ],
                stream=True   
            )    
            response_message = st.empty()
            full_response = ""

        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_response += content
                response_message.markdown(full_response + "▌")
        
# 循环结束后，去掉光标，显示最终内容
        response_message.markdown(full_response)

# 存入 session_state
        st.session_state.messages.append({"role": "assistant", "content": full_response})

# 存入数据库
        save_session()

elif app_mode == "📚 文档内容解疑 (RAG)":
        st.title("📚 文档助手")
        with st.sidebar:
            uploaded_file = st.file_uploader("上传 PDF 文件", type=["pdf"])
            if uploaded_file is not None:
                vectorstore = process_pdf(uploaded_file.getvalue())
                st.success("✅ 文档已就绪！")
        st.title("有什么需要我帮助的吗?")
        
        if uploaded_file is None:
            st.info(" 请先在左侧上传 PDF 文件 ")
        else:
            if "rag_messages" not in st.session_state:
                st.session_state.rag_messages = []
            
        # 渲染 RAG 的历史记录
        for message in st.session_state.rag_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("针对文档提问..."):
            st.session_state.rag_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("正在查阅文档..."):
                    docs = vectorstore.similarity_search(prompt, k=3)
                    context = "\\n\\n".join([d.page_content for d in docs])
                    rag_prompt = f"请严格根据以下参考信息回答问题。如果找不到，请说不知道。\\n\\n【参考信息】\\n{context}\\n\\n【问题】\\n{prompt}"

                    response = client.chat.completions.create(
                        model="glm-4-flash",
                        messages=[{"role": "user", "content": rag_prompt}],
                        stream=True,
                        temperature=0.3
                    )
                    response_message = st.empty()
                    full_response = ""
                    for chunk in response:
                        if chunk.choices[0].delta.content is not None:
                            full_response += chunk.choices[0].delta.content
                            response_message.markdown(full_response + "▌")
                response_message.markdown(full_response)
                st.session_state.rag_messages.append({"role": "assistant", "content": full_response})
                save_session()