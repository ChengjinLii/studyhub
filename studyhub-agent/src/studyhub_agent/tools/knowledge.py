from studyhub_agent.contracts.knowledge import ListInput, ReadInput, SearchInput
from studyhub_agent.contracts.tools import ToolSpec

KNOWLEDGE_TOOLS = (
    ToolSpec(
        name="search_knowledge",
        version="1.0",
        description="在当前知识范围内检索正文片段；返回原文、版本、行号及可引用的 chunk_id。",
        parameters=SearchInput.model_json_schema(),
    ),
    ToolSpec(
        name="read_document",
        version="1.0",
        description="按文档分页阅读，或以片段为中心扩展上下文；每个片段保留独立引用。",
        parameters=ReadInput.model_json_schema(),
    ),
    ToolSpec(
        name="list_documents",
        version="1.0",
        description="列出当前知识范围内的文档，可按标题查找；不代表已经读过正文。",
        parameters=ListInput.model_json_schema(),
    ),
)
