"""Task enumeration for fine-tuning recipes."""

from enum import Enum


class TaskEnum(str, Enum):
    """Valid tasks for fine-tuning recipes."""

    RAG = "rag"
    NER = "ner"
    TEXT2SQL = "text2sql"
    TEXT2JSONEVENT = "text2JsonEvent"
    TEXT2LIST = "Text2List"
    TEXT2JSON = "Text2Json"

    @classmethod
    def values(cls) -> list[str]:
        """Return list of all task values."""
        return [task.value for task in cls]
