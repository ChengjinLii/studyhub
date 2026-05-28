from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(name="find_study_materials", title="Find Study Materials")
    def find_study_materials(query: str) -> str:
        return f"请在 StudyHub 中搜索与“{query}”相关的资料、求购和集市信息，并优先引用 fetch 返回的详情。"

    @mcp.prompt(name="summarize_material", title="Summarize Material")
    def summarize_material(material_id: str) -> str:
        return f"请调用 fetch 获取 material:{material_id}，然后总结资料内容、适合人群和使用建议。"

    @mcp.prompt(name="compare_materials", title="Compare Materials")
    def compare_materials(query: str) -> str:
        return f"请搜索 StudyHub 中与“{query}”相关的多个资料，并从课程、标签、下载量和价格维度比较。"

    @mcp.prompt(name="draft_material_request", title="Draft Material Request")
    def draft_material_request(course: str) -> str:
        return f"请帮我草拟一个 StudyHub 求购需求，课程是“{course}”，包含预算、预览要求和交付标准。"

    @mcp.prompt(name="draft_market_listing", title="Draft Market Listing")
    def draft_market_listing(item: str) -> str:
        return f"请帮我为 StudyHub 校园集市草拟“{item}”的发布文案，包含标题、描述、分类、价格和联系方式提示。"

    @mcp.prompt(name="admin_review_report", title="Admin Review Report")
    def admin_review_report(target: str) -> str:
        return f"请作为 StudyHub 管理员，分析举报或审核对象“{target}”，列出风险、建议动作和需要补充的信息。"
