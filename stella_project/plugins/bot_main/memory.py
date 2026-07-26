import json
import os

import chromadb
from chromadb.utils import embedding_functions


class AIMemory:
    """通用的 AI 向量记忆与用户状态数据库管理类"""

    def __init__(self, base_dir: str):
        self.db_path = os.path.join(base_dir, "ai_db")
        self.favor_file = os.path.join(base_dir, "favorability.json")

        # 本地 embedding 模型路径
        model_local_path = os.path.join(base_dir, "model_all-MiniLM-L6-v2")

        self.client = chromadb.PersistentClient(path=self.db_path)
        self.emb_fn = (
            embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_local_path
            )
        )
        self.collection = self.client.get_or_create_collection(
            name="chat_history", embedding_function=self.emb_fn
        )
        self.favor_data = self.load_favor()

    def load_favor(self) -> dict:
        if os.path.exists(self.favor_file):
            with open(self.favor_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_favor(self):
        with open(self.favor_file, "w", encoding="utf-8") as f:
            json.dump(self.favor_data, f, ensure_ascii=False, indent=2)

    def get_user_status(self, user_id: str) -> dict:
        user_id = str(user_id)
        if user_id not in self.favor_data:
            # 初始化默认用户状态
            self.favor_data[user_id] = {"level": 0, "nickname": "用户"}
        return self.favor_data[user_id]

    def add_memory(self, user_id: str, user_msg: str, bot_reply: str):
        """仅对包含有价值信息的对话进行 RAG 向量存储"""
        if len(user_msg) > 5 and len(bot_reply) > 5:
            self.collection.add(
                documents=[f"用户说：{user_msg}\n回复：{bot_reply}"],
                ids=[f"{user_id}_{os.urandom(4).hex()}"],
                metadatas=[{"user_id": str(user_id)}],
            )

    def search_memory(self, user_id: str, query: str, n: int = 2) -> list:
        results = self.collection.query(
            query_texts=[query], n_results=n, where={"user_id": str(user_id)}
        )
        return results["documents"][0] if results["documents"] else []