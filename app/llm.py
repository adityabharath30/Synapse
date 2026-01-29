"""
LLM Client for Extractive QA.

Uses OpenAI GPT-4o-mini for fast, cheap extraction.
This module handles all LLM interactions for the answer layer.
"""
from __future__ import annotations

import json
import os
import logging
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger("rag")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Get or create OpenAI client (singleton)."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in .env")
        # Strip whitespace in case of formatting issues
        api_key = api_key.strip()
        _client = OpenAI(api_key=api_key)
    return _client


def extract_answer_from_chunk(query: str, chunk_text: str) -> dict:
    """
    Use GPT to extract the smallest answer span from a chunk.
    
    This is the core extractive QA call. The model is instructed to:
    - Copy the smallest span that answers the question
    - Never invent facts not in the text
    - Return "NONE" if no answer is present
    
    Returns:
        {"answer": str or "NONE", "confidence": float 0-1}
    """
    client = get_client()
    
    system_prompt = """You are an extraction engine for a personal factual recall system.
You ONLY extract short answers that are explicitly stated in the given text.
You NEVER invent or infer facts not literally present.
You respond ONLY in valid JSON format."""

    user_prompt = f"""Question: {query}

Text:
{chunk_text}

Instructions:
- If the text contains a direct answer, copy the smallest possible span that answers the question.
- Prefer a short phrase or a single simple sentence (≤20 words).
- Do NOT summarize the whole document.
- Do NOT add explanations or context not in the text.
- If the answer is not clearly present, return EXACTLY "NONE" as the answer.

Respond in JSON ONLY with this exact format:
{{"answer": "<copied span or NONE>", "confidence": <number between 0.0 and 1.0>}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=150,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Handle markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            content = content.strip()
        
        # Parse JSON response
        result = json.loads(content)
        
        answer = result.get("answer", "NONE")
        confidence = float(result.get("confidence", 0.0))
        
        # Validate
        if not answer or answer.upper() == "NONE":
            return {"answer": "NONE", "confidence": 0.0}
        
        return {"answer": answer, "confidence": min(max(confidence, 0.0), 1.0)}
        
    except json.JSONDecodeError as e:
        logger.warning("LLM returned invalid JSON: %s", e)
        return {"answer": "NONE", "confidence": 0.0}
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return {"answer": "NONE", "confidence": 0.0}


def compress_answer(answer: str) -> str:
    """
    Use GPT to compress a long answer into ≤1 sentence.
    
    Rules:
    - Maximum 25 words
    - Do NOT add new facts
    - Keep all numbers, dates, and names unchanged
    """
    if not answer or len(answer.split()) <= 25:
        return answer
    
    client = get_client()
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You compress factual text into shorter form without changing meaning or adding facts.",
                },
                {
                    "role": "user",
                    "content": f"""Original text:
{answer}

Instructions:
- Rewrite into a single, direct sentence.
- Maximum 25 words.
- Do NOT add any new facts or assumptions.
- Keep all numbers, dates, and names EXACTLY unchanged.

Respond with ONLY the compressed sentence, nothing else.""",
                },
            ],
            temperature=0.0,
            max_tokens=60,
        )
        
        compressed = response.choices[0].message.content.strip()
        
        # Validate it's not longer than original
        if len(compressed.split()) > len(answer.split()):
            return answer
        
        return compressed
        
    except Exception as e:
        logger.warning("LLM compression failed: %s", e)
        # Fallback: truncate
        words = answer.split()[:25]
        return " ".join(words).rstrip(".,;:") + "."


def is_available() -> bool:
    """Check if LLM is available (API key exists)."""
    api_key = os.getenv("OPENAI_API_KEY")
    return bool(api_key and api_key.strip())
