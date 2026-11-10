"""AlterLab LlamaIndex data reader."""

from llama_index.readers.alterlab.base import AlterLabReader
from llama_index.readers.alterlab.fallback import (
    FetchFallbackAdapter as AlterLabBlockedFetchFallback,
)
from llama_index.readers.alterlab.tools import AlterLabScrapeTool, AlterLabSearchTool

__all__ = [
    "AlterLabBlockedFetchFallback",
    "AlterLabReader",
    "AlterLabScrapeTool",
    "AlterLabSearchTool",
]
