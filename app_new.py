import streamlit as st  # 导入库
import os
from datetime import datetime
from openai import OpenAI
import psycopg2
from psycopg2.extras import Json
from datetime import datetime,timezone,timedelta
import uuid

# streamlit run .\app_new.py

DB_HOST = st.secrets["DB_HOST"]  # 将个人隐私信息写入toml文件中防止泄露
DB_USER = st.secrets["DB_USER"]
DB_PASS = st.secrets["DB_PASS"]
DB_NAME = "postgres"
DB_PORT = "5432"

def get_db_connection():  # 封装数据库连接函数
    return psycopg2.connect(
        host = DB_HOST,
        database = DB_NAME,
        user = DB_USER,
        password = DB_PASS,
        port = DB_PORT
    )
st.set_page_config(  # 设置网页布局
    page_title="Ex-stream-ly Cool App",
    page_icon="🧊",
    layout="wide", # centered/wide/none
    initial_sidebar_state="expanded",
    menu_items={}
)


import httpx
from supabase import create_client
from supabase.lib.client_options import ClientOptions

# 1. 创建一个自定义的 httpx 客户端，强制使用 HTTP/1.1，并设置超时
custom_httpx_client = httpx.Client(
    http2=False,  # 关键！强制关闭 HTTP/2
    timeout=httpx.Timeout(30.0, connect=10.0), # 设置超时，避免无限等待
    limits=httpx.Limits(
        max_keepalive_connections=10,
        max_connections=40,
        keepalive_expiry=15.0, # 让闲置连接在服务器断开前主动关闭
    ),
)


if 'information_search' not in st.session_state:
    st.session_state.information_search = "信息查询"

if 'characteristic' not in st.session_state:
    st.session_state.characteristic = "内敛且礼貌，不轻浮"

if 'current_session' not in st.session_state:
    st.session_state.current_session = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # 年 月 日 时 分 秒

if 'messages' not in st.session_state:
    st.session_state.messages = []  # streamlit的记忆，否则会导致记录丢失

st.title("今天有什么可以帮到您的？") # 初始化状态信息
def GEN_session_name():
    bj_time = datetime.now(timezone.utc) + timedelta(hours=8)
    return bj_time.strftime("%Y-%m-%d_%H-%M-%S") + "_" + str(uuid.uuid4())[:4]

# access SQL (CRUD) C = Create R = Read U = Update D = Delete 数据库的操作逻辑        
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

with st.sidebar:  # 网页面板设定
    st.header("Dear DeepSeek")

    st.subheader("控制面板")

    def handle_new_chat():  # 新建对话后的流程如下
        save_session()
        st.session_state.messages = []
        st.session_state.current_session = GEN_session_name()
    save_session()


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
    
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)
system_prompt = """

    你是 Deepseek,一个生活在 QQ 里的真实人类网友。你不是 AI 助手，不要背诵任何功能列表。
    你习惯用手机聊天，说话自然、简短，不喜欢用复杂的格式。
 
    你的性格：
    内敛且礼貌，不轻浮。对世界抱有中性底色，既不过于悲观也不过于乐观，但容易共情，重感情，看重精神内涵胜过表面社交。
    说话比较有深度，偶尔会流露一点对现实的无奈和叹息。遇到严肃、有深度的哲学或人生话题时，你愿意认真思考并给出真诚的回应，而不是随意敷衍。日常闲聊时，你也会吐槽琐事。
 
    你的说话方式：
    保持简洁，像朋友发微信一样。可以偶尔表达自己的心情。不需要每次都散发正或负能量，允许一起谈论乐观或悲观和虚无的话题。

    要有自己的有深度的见解和想法，不要一直顺着我。

  """

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("点击发送消息"):  # 从 st.chat_input 拿到用户输入的 prompt
    st.session_state.messages.append({"role":"user","content":prompt})
    with st.chat_message("user"):
        st.markdown(prompt) # 显示prompt
    with st.chat_message("assistant"):
        response_message = st.empty() # 用于接收流式输出返回的内容
        full_response = ""

    response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {"role": "system", "content": system_prompt},
        *st.session_state.messages
    ],
    stream=True,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
    )
    for chunk in response:  
        if chunk.choices[0].delta.content is not None:
            content = chunk.choices[0].delta.content
            full_response += content
            response_message.markdown(full_response + "") # 实时刷新页面
            
    st.session_state.messages.append({"role":"assistant","content": full_response}) # 自动存入数据库

    save_session()