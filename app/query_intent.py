from __future__ import annotations

from enum import Enum
import re


class QueryIntent(str, Enum):
    FACT_LOOKUP = "fact_lookup"      # salary, date, who, where, when
    KEY_PHRASE_LOOKUP = "key_phrase_lookup"  # exact terms, names
    SUMMARY = "summary"              # summarize, overview
    FULLTEXT = "fulltext"            # exploratory search, show me, find, list


# Terms that indicate factual personal questions requiring explicit evidence
FACT_TERMS = {
    "salary",
    "compensation",
    "base",
    "annual",
    "amount",
    "total",
    "date",
    "start",
    "effective",
    "email",
    "phone",
    "address",
    "title",
    "role",
    "position",
    "name",
    "who",
    "where",
    "when",
    "how much",
    "how many",
}

SUMMARY_TERMS = {
    "summarize",
    "summary",
    "overview",
    "describe",
    "explain",
}

# Terms that indicate exploratory/keyword search — skip answer generation
FULLTEXT_TERMS = {
    "find",
    "search",
    "show",
    "list",
    "all",
    "documents",
    "files",
    "related",
}


def classify_query(query: str) -> QueryIntent:
    """
    Classify query intent to determine behavior:
    - FACT_LOOKUP: requires explicit evidence, else show documents
    - FULLTEXT: skip answer generation, show documents
    - SUMMARY: attempt summarization
    - KEY_PHRASE_LOOKUP: exact term search
    """
    text = query.strip()
    if not text:
        return QueryIntent.FULLTEXT

    lowered = text.lower()
    tokens = set(re.findall(r"\w+", lowered))

    # Check for summary intent
    if any(term in tokens for term in SUMMARY_TERMS):
        return QueryIntent.SUMMARY

    # Check for exploratory/fulltext intent
    if any(term in tokens for term in FULLTEXT_TERMS):
        return QueryIntent.FULLTEXT

    # Check for factual question patterns
    if lowered.startswith(("who ", "where ", "when ", "what ", "how much", "how many")):
        return QueryIntent.FACT_LOOKUP

    if any(term in tokens for term in FACT_TERMS):
        return QueryIntent.FACT_LOOKUP

    # Quoted phrases or short queries → key phrase lookup
    if '"' in text or "'" in text:
        return QueryIntent.KEY_PHRASE_LOOKUP

    # Very short queries (1-2 words) → keyword search
    if len(tokens) <= 2:
        return QueryIntent.KEY_PHRASE_LOOKUP

    # Default to fulltext for exploratory queries
    return QueryIntent.FULLTEXT
