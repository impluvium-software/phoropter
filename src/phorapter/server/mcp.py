"""The FastMCP surface: LLM-facing tools over the same :class:`ServiceCore`.

Two tools are always registered:

- ``phorapter_query`` — retrieve right-sized context under a token budget;
- ``phorapter_list_corpora`` — list the available corpora.

Two write tools — ``phorapter_add_document`` and ``phorapter_delete_document`` —
are registered only when ``settings.mcp.enable_document_tools`` is true.

Tool descriptions are written for LLM consumers. The query tool's structured
output mirrors the REST response; its text rendering heads each block with
``[document_id @ start..end, size]`` and deliberately omits raw cosine scores,
which are ordinal within one size and meaningless to a reader across sizes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from phorapter.server import mappers

if TYPE_CHECKING:
    from phorapter.service.core import ServiceCore

__all__ = ["build_mcp"]


def _render_results_text(response: dict[str, Any]) -> str:
    """A compact, reader-facing rendering of a query response (no raw scores)."""
    results = response.get("results", [])
    if not results:
        return "No context slices fit the budget."
    lines: list[str] = []
    for r in results:
        c = r["coords"]
        start = c["codepoint_offset"]
        end = c["codepoint_end"]
        header = f"[{c['document_id']} @ {start}..{end}, size {c['size']}]"
        text = r.get("text") or ""
        lines.append(f"{header}\n{text}")
    budget = response.get("budget", {})
    footer = f"\n({len(results)} slice(s), {budget.get('used', 0)} tokens used)"
    if response.get("partial"):
        footer += " [partial: some sizes were unavailable]"
    return "\n\n".join(lines) + footer


def build_mcp(core: ServiceCore) -> FastMCP[Any]:
    """Build the FastMCP server bound to ``core``.

    Mount its ASGI app at ``/mcp`` with :meth:`FastMCP.http_app`, or run it over
    stdio with :meth:`FastMCP.run`.
    """
    mcp: FastMCP[Any] = FastMCP(name="phorapter")
    settings = core.settings

    @mcp.tool(
        name="phorapter_query",
        description=(
            "Retrieve right-sized context from a phorapter corpus for a natural-language "
            "query. The server searches the corpus at several slice sizes, removes duplicate "
            "nested passages, and — within the given token budget — trades small matching "
            "passages up to their enclosing parent passages so the returned context is as "
            "complete as the budget allows. Set 'token_budget' to the number of context "
            "tokens you can spend; omit it to get only de-duplicated matches. Returns the "
            "selected passages with their document ids and character ranges."
        ),
    )
    async def phorapter_query(
        corpus: str,
        query: str,
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        budget = token_budget if token_budget is not None else settings.mcp.default_token_budget
        outcome = await core.query.run(
            corpus,
            query,
            token_budget=budget,
            include_text=True,
            include_trace=False,
        )
        response = mappers.query_outcome_to_dto(outcome).model_dump(mode="json")
        response["text"] = _render_results_text(response)
        return response

    @mcp.tool(
        name="phorapter_list_corpora",
        description="List the names of the corpora available on this phorapter server.",
    )
    async def phorapter_list_corpora() -> dict[str, Any]:
        return {"corpora": list(await core.corpora.list_names())}

    if settings.mcp.enable_document_tools:

        @mcp.tool(
            name="phorapter_add_document",
            description=(
                "Add or replace a document in a phorapter corpus. The full text is "
                "re-sliced and indexed; providing the same document id again replaces "
                "the previous version. Returns the resulting document record."
            ),
        )
        async def phorapter_add_document(
            corpus: str, document_id: str, text: str
        ) -> dict[str, Any]:
            record = await core.documents.put(corpus, document_id, text)
            return mappers.document_record_to_dto(record).model_dump(mode="json")

        @mcp.tool(
            name="phorapter_delete_document",
            description="Delete a document and all of its indexed passages from a corpus.",
        )
        async def phorapter_delete_document(corpus: str, document_id: str) -> dict[str, Any]:
            await core.documents.delete(corpus, document_id)
            return {"deleted": document_id}

    return mcp
