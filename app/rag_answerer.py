"""
Extractive QA Answer Layer for Personal Semantic Memory System.

This module implements a multi-stage extractive pipeline:
  Stage A: Retrieval (handled by search_service.py)
  Stage B: Per-chunk extractive answer proposal (GPT-powered)
  Stage C: Candidate selection with scoring
  Stage D: Optional compression for long spans

Design principles:
  - This is NOT a summarizer or chatbot
  - Prefer extracting verbatim text over generating new text
  - Prefer answering from imperfect evidence over refusing
  - Keep answers ≤1 sentence (max 2 if necessary)
  - Abstain only when ALL chunks return NONE
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

# LLM integration for intelligent extraction
from app.llm import extract_answer_from_chunk as llm_extract, compress_answer as llm_compress, is_available as llm_available

logger = logging.getLogger("rag")


# =============================================================================
# TEXT UTILITIES
# =============================================================================

def _sentences(text: str) -> Iterable[str]:
    """Split text into sentences."""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if sentence:
            yield sentence


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase words (3+ chars)."""
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) > 2}


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace and punctuation spacing."""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def fix_pdf_spacing(text: str) -> str:
    """Fix common PDF extraction artifacts."""
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    def _join_spaced_letters(match: re.Match[str]) -> str:
        return match.group(0).replace(" ", "")
    text = re.sub(r"\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b", _join_spaced_letters, text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class EvidenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class AnswerCandidate:
    """A candidate answer extracted from a single chunk."""
    answer: str
    confidence: float
    source: str
    filepath: str
    chunk_text: str


# =============================================================================
# STAGE B: PER-CHUNK EXTRACTIVE ANSWER PROPOSAL (GPT-POWERED)
# =============================================================================

def propose_answer_from_chunk(query: str, chunk: dict) -> AnswerCandidate | None:
    """
    Extract the smallest text span from this chunk that answers the query.
    
    Uses GPT-4o-mini for intelligent extraction:
    - Understands context and intent
    - Finds answers even with different phrasing
    - Returns minimal answer spans
    
    Returns None if the chunk does not contain a direct answer.
    """
    text = normalize_whitespace(fix_pdf_spacing(chunk.get("text", "")))
    if not text or len(text.split()) < 5:
        return None
    
    # Use LLM for extraction if available
    if llm_available():
        result = llm_extract(query, text)
        
        answer = result.get("answer", "NONE")
        confidence = result.get("confidence", 0.0)
        
        # If LLM says NONE, this chunk doesn't answer the question
        if answer == "NONE" or not answer or confidence < 0.1:
            return None
        
        return AnswerCandidate(
            answer=answer,
            confidence=confidence,
            source=chunk.get("filename", ""),
            filepath=chunk.get("filepath", ""),
            chunk_text=text,
        )
    
    # Fallback: regex-based extraction (if no API key)
    return _propose_answer_regex_fallback(query, chunk, text)


def _propose_answer_regex_fallback(query: str, chunk: dict, text: str) -> AnswerCandidate | None:
    """Fallback extraction using regex patterns (no LLM)."""
    query_terms = _tokenize(query)
    question_type = _infer_question_type(query)
    
    best_span = None
    best_score = 0.0
    
    for sentence in _sentences(text):
        sentence = normalize_whitespace(fix_pdf_spacing(sentence))
        if not sentence or _is_boilerplate(sentence):
            continue
        
        score = _score_sentence_for_extraction(sentence, query_terms, question_type)
        
        if score > best_score:
            best_score = score
            best_span = _extract_minimal_span(sentence, query_terms, question_type)
    
    if not best_span or best_score < 0.15:
        return None
    
    return AnswerCandidate(
        answer=best_span,
        confidence=min(best_score, 1.0),
        source=chunk.get("filename", ""),
        filepath=chunk.get("filepath", ""),
        chunk_text=text,
    )


# =============================================================================
# REGEX FALLBACK HELPERS
# =============================================================================

NUMBER_PATTERN = re.compile(r"\$\s*\d[\d,]*(?:\.\d{2})?|\d[\d,]+(?:\.\d{2})?")
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s*\d{4})\b",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
ORG_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Za-z&]*(?:\s+[A-Z][A-Za-z&]*)*"
    r"(?:\s+(?:Inc|LLC|Corp|Company|Co|Ltd|University|College|Hospital|Bank|Health))\.?)\b"
)
LOCATION_PATTERN = re.compile(r"\b(?:in|at|from|to)\s+([A-Z][a-z]+(?:,?\s+[A-Z][a-z]+)*)")

BOILERPLATE_TERMS = {
    "dear", "sincerely", "regards", "confidential", "page",
    "attached", "thank you", "congratulations", "hereby",
}


def _score_sentence_for_extraction(sentence: str, query_terms: set[str], question_type: str) -> float:
    """Score how well a sentence answers the query."""
    sentence_terms = _tokenize(sentence)
    
    if query_terms:
        overlap = len(query_terms & sentence_terms) / len(query_terms)
    else:
        overlap = 0.1
    
    type_bonus = 0.0
    if question_type in {"how_much", "how_many"} and NUMBER_PATTERN.search(sentence):
        type_bonus = 0.3
    elif question_type == "when" and DATE_PATTERN.search(sentence):
        type_bonus = 0.3
    elif question_type == "who" and (NAME_PATTERN.search(sentence) or ORG_PATTERN.search(sentence)):
        type_bonus = 0.25
    elif question_type == "where" and LOCATION_PATTERN.search(sentence):
        type_bonus = 0.25
    
    word_count = len(sentence.split())
    length_bonus = 0.15 if 4 <= word_count <= 20 else 0.05
    
    direct_bonus = 0.15 if re.search(r"\b(is|are|was|were|will be)\s+(a|an|the|\$|\d)", sentence, re.I) else 0.0
    
    return overlap * 0.5 + type_bonus + length_bonus + direct_bonus


def _extract_minimal_span(sentence: str, query_terms: set[str], question_type: str) -> str:
    """Extract the smallest text span that answers the question."""
    if question_type in {"how_much", "how_many"}:
        match = NUMBER_PATTERN.search(sentence)
        if match:
            return _window_around_match(sentence, match, 6)
    
    if question_type == "when":
        match = DATE_PATTERN.search(sentence)
        if match:
            return _window_around_match(sentence, match, 5)
    
    if question_type == "who":
        match = NAME_PATTERN.search(sentence) or ORG_PATTERN.search(sentence)
        if match:
            return _window_around_match(sentence, match, 5)
    
    if question_type == "where":
        match = LOCATION_PATTERN.search(sentence)
        if match:
            return _window_around_match(sentence, match, 5)
    
    if question_type == "what":
        copula = re.search(r"\b(is|are|was|means|refers to)\b", sentence, re.I)
        if copula:
            tail = sentence[copula.end():].strip()
            if tail:
                return _shorten(tail, 18)
    
    return sentence if len(sentence.split()) <= 25 else _extract_query_relevant_window(sentence, query_terms, 20)


def _window_around_match(sentence: str, match: re.Match, context_words: int) -> str:
    """Extract a window of words around a regex match."""
    words = sentence.split()
    if not words:
        return sentence
    
    start_char = match.start()
    prefix_word_count = len(sentence[:start_char].split())
    match_word_count = len(match.group().split())
    
    start_idx = max(0, prefix_word_count - context_words)
    end_idx = min(len(words), prefix_word_count + match_word_count + context_words)
    
    return " ".join(words[start_idx:end_idx]).strip()


def _extract_query_relevant_window(sentence: str, query_terms: set[str], window_size: int) -> str:
    """Extract the most query-relevant window."""
    words = sentence.split()
    if len(words) <= window_size:
        return sentence
    
    best_window = " ".join(words[:window_size])
    best_score = 0.0
    
    for i in range(len(words) - window_size + 1):
        window = " ".join(words[i:i + window_size])
        score = len(query_terms & _tokenize(window))
        if score > best_score:
            best_score = score
            best_window = window
    
    return best_window


def _shorten(text: str, max_words: int = 20) -> str:
    """Shorten text to max words."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip().rstrip(".,;:") + "."


def _is_boilerplate(sentence: str) -> bool:
    """Check if sentence is boilerplate."""
    return any(term in sentence.lower() for term in BOILERPLATE_TERMS)


def _infer_question_type(query: str) -> str:
    """Infer the type of question."""
    lowered = query.strip().lower()
    if lowered.startswith("who"):
        return "who"
    if lowered.startswith("where"):
        return "where"
    if lowered.startswith("when"):
        return "when"
    if lowered.startswith("how much"):
        return "how_much"
    if lowered.startswith("how many"):
        return "how_many"
    if lowered.startswith("what"):
        return "what"
    if any(w in lowered for w in ["salary", "pay", "cost", "price", "amount", "compensation"]):
        return "how_much"
    if any(w in lowered for w in ["date", "when", "start", "begin", "effective"]):
        return "when"
    return "other"


# =============================================================================
# STAGE C: CANDIDATE SELECTION
# =============================================================================

def select_best_answer(candidates: list[AnswerCandidate], query: str) -> AnswerCandidate | None:
    """Select the single best answer from candidates."""
    if not candidates:
        return None
    
    query_terms = _tokenize(query)
    scored: list[tuple[float, AnswerCandidate]] = []
    
    for candidate in candidates:
        score = candidate.confidence * 0.6
        
        answer_terms = _tokenize(candidate.answer)
        if query_terms:
            overlap = len(query_terms & answer_terms) / len(query_terms)
            score += overlap * 0.25
        
        word_count = len(candidate.answer.split())
        if 3 <= word_count <= 18:
            score += 0.1
        elif word_count > 30:
            score -= 0.1
        
        if _is_generic_answer(candidate.answer):
            score -= 0.15
        
        scored.append((score, candidate))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _is_generic_answer(answer: str) -> bool:
    """Check if answer is too generic."""
    generic = ["the document", "this document", "the text", "information about", "details about"]
    return any(p in answer.lower() for p in generic)


# =============================================================================
# STAGE D: OPTIONAL COMPRESSION (GPT-POWERED)
# =============================================================================

def compress_answer_if_needed(answer: str, max_words: int = 25) -> str:
    """Compress answer using LLM if too long."""
    if not answer:
        return answer
    
    answer = normalize_whitespace(fix_pdf_spacing(answer))
    
    if len(answer.split()) <= max_words:
        return answer
    
    # Use LLM for intelligent compression
    if llm_available():
        return llm_compress(answer)
    
    # Fallback: truncate
    words = answer.split()[:max_words]
    return " ".join(words).rstrip(".,;:") + "."


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def extract_best_answer(query: str, chunks: list[dict]) -> dict:
    """
    Main entry point for extractive QA.
    
    Pipeline:
    1. For each chunk, propose an answer using GPT (Stage B)
    2. Select the best candidate (Stage C)
    3. Compress if needed using GPT (Stage D)
    4. Return structured result
    """
    if not chunks:
        return _abstain_response("No documents found.")
    
    # Stage B: Per-chunk extraction
    candidates: list[AnswerCandidate] = []
    for chunk in chunks:
        candidate = propose_answer_from_chunk(query, chunk)
        if candidate:
            candidates.append(candidate)
            logger.debug(
                "Candidate from %s (conf=%.2f): %s",
                candidate.source,
                candidate.confidence,
                candidate.answer[:80],
            )
    
    # Stage C: Select best
    best = select_best_answer(candidates, query)
    
    if not best:
        logger.debug("No candidates for query: %s", query)
        return _abstain_response(
            "Answer not found in your documents.",
            source=chunks[0].get("filename", "") if chunks else "",
            filepath=chunks[0].get("filepath", "") if chunks else "",
        )
    
    # Stage D: Compress if needed
    final_answer = compress_answer_if_needed(best.answer)
    confidence_level = _confidence_level_from_score(best.confidence)
    
    logger.debug("Final answer (%s): %s", confidence_level.value, final_answer)
    
    return {
        "answer": final_answer,
        "confidence": best.confidence,
        "confidence_level": confidence_level,
        "source": best.source,
        "filepath": best.filepath,
        "answerable": True,
    }


def _confidence_level_from_score(score: float) -> EvidenceConfidence:
    """Map score to confidence level."""
    if score >= 0.7:
        return EvidenceConfidence.HIGH
    if score >= 0.5:
        return EvidenceConfidence.MEDIUM
    if score >= 0.3:
        return EvidenceConfidence.LOW
    return EvidenceConfidence.NONE


def _abstain_response(message: str, source: str = "", filepath: str = "") -> dict:
    """Generate abstention response."""
    return {
        "answer": message,
        "confidence": 0.0,
        "confidence_level": EvidenceConfidence.NONE,
        "source": source,
        "filepath": filepath,
        "answerable": False,
    }


# Legacy export
def is_answerable(chunks: list[dict], question_type: str) -> tuple[bool, str]:
    """Legacy function - always returns True."""
    return True, "extraction_will_determine"
