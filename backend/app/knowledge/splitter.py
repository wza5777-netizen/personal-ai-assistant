"""Split text into overlapping chunks."""
from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_text(
    text: str, chunk_size: int = 800, chunk_overlap: int = 100
) -> list[str]:
    """Split text into trimmed, non-empty chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]
