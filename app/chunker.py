import re
from typing import Iterable


def chunk(text: str, chunk_size: int = 240, overlap: int = 40) -> Iterable[str]:
    if not text:
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    sentence_lens = [len(sentence.split()) for sentence in sentences]

    for sentence, length in zip(sentences, sentence_lens):
        if current_len + length > chunk_size and current:
            chunks.append(" ".join(current).strip())
            current, current_len = _overlap_tail(current, overlap)

        current.append(sentence)
        current_len += length

    if current:
        chunks.append(" ".join(current).strip())

    return [c for c in chunks if c]


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [s for s in re.split(r"(?<=[.!?])\s+", cleaned) if s]


def _overlap_tail(sentences: list[str], overlap_words: int) -> tuple[list[str], int]:
    if overlap_words <= 0:
        return [], 0
    tail: list[str] = []
    count = 0
    for sentence in reversed(sentences):
        length = len(sentence.split())
        if count + length > overlap_words and tail:
            break
        tail.insert(0, sentence)
        count += length
    return tail, count
