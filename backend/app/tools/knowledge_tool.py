"""Knowledge tool: search_knowledge."""
import json
import time
from typing import Any, Dict, Optional

from app.database.session import AsyncSessionLocal
from app.knowledge.retriever import KnowledgeRetriever
from app.observability import logger
from app.observability import tracking
from app.tools.base import BaseTool
from app.tools.registry import registry


class SearchKnowledgeTool(BaseTool):
    name = "search_knowledge"
    description = (
        "在用户上传的知识库文档（PDF / TXT / Markdown）中检索与问题相关的片段。"
        "当用户询问已上传的文档、资料、简历、个人介绍、联系方式（手机号、邮箱、微信等）、"
        "工作经历、教育背景、公司制度、产品说明、手册等内容时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索问题或关键词，建议包含用户提到的姓名、关键信息",
            }
        },
        "required": ["query"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        query = str(arguments.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "query is required"}, ensure_ascii=False)
        limit = 5

        start = time.perf_counter()
        async with AsyncSessionLocal() as session:
            retriever = KnowledgeRetriever(session)
            chunks = await retriever.search(user_id=user_id, query=query, limit=limit)
        duration_ms = (time.perf_counter() - start) * 1000.0

        logger.info(
            "knowledge_retrieval",
            user_id=user_id,
            query=query,
            hits=len(chunks),
            duration_ms=round(duration_ms, 2),
        )
        await tracking.record_event(
            "knowledge_retrieval",
            details={"query": query, "hits": len(chunks), "duration_ms": round(duration_ms, 2)},
        )
        if not chunks:
            return json.dumps(
                {"chunks": [], "message": "知识库中未找到相关内容"}, ensure_ascii=False
            )
        return json.dumps(
            {
                "chunks": [
                    {"document_id": c.document_id, "content": c.content}
                    for c in chunks
                ]
            },
            ensure_ascii=False,
        )


registry.register(SearchKnowledgeTool())
