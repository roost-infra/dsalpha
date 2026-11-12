"""Content Desk page-plugin helpers.

The desk's items live in the browser; this endpoint only gives its editor a
one-shot writing call through the same BYOK/OAuth-aware LLM service the rest of
the server uses. It is not a second agent or a second model setting.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.server.utils.api import CurrentUserId, handle_api_exceptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/content-desk", tags=["Content Desk"])


class GenerateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    kind: str = "note"
    platform: str = "小红书"
    style: str = ""


@router.post("/generate")
@handle_api_exceptions("generate content draft", logger)
async def generate(req: GenerateRequest, user_id: CurrentUserId):
    from src.server.app import setup
    from src.server.services.llm.service import LLMService

    style = f"\n写作风格要求：{req.style}" if req.style.strip() else ""
    svc = LLMService(agent_config=setup.agent_config, logger=logger)
    result = await svc.complete(
        user_id=user_id,
        system_prompt=(
            "你是 Roost 内容工作台的写作者。把用户给的选题写成可以直接编辑的中文初稿。"
            "只输出正文 Markdown，不要解释、不要复述任务、不要加 JSON。"
            "内容要具体，有观点，避免空泛套话。"
        ),
        user_prompt=(
            f"平台：{req.platform}\n类型：{req.kind}\n选题：{req.title}\n"
            f"原始灵感：{req.body or '（无）'}{style}"
        ),
        slot="primary",
    )
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(
            str(block.get("text", ""))
            for block in result
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        text = str(result)
    return {"text": text.strip(), "model": "LangAlpha"}
