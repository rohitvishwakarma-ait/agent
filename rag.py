"""
rag.py — Vector store for RAG (Retrieval-Augmented Generation)
Equivalent of rag.ts

Handles: embed → store → search using cosine similarity
Uses nomic-embed-text via Ollama for local embeddings
"""

import json
import math
import os
import time
import random
import string
from dataclasses import dataclass, field, asdict
from typing import Literal
import requests


# ============================================================
# TYPES
# ============================================================

@dataclass
class VectorEntry:
    id: str
    text: str
    role: Literal["user", "assistant"]
    type: Literal["conversational", "system"]
    vector: list[float]          # 768-dim embedding from nomic-embed-text
    timestamp: str               # ISO string


# ============================================================
# RAG CLASS
# ============================================================

class RAG:
    def __init__(self, file_path: str = "rag.store.json"):
        self.file_path = file_path
        self.entries: list[VectorEntry] = []
        self.embed_url = "http://localhost:11434/api/embed"
        self.embed_model = "nomic-embed-text"

    # --------------------
    # LOAD — read vector store from disk
    # --------------------
    def load(self) -> None:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = [VectorEntry(**e) for e in data.get("entries", [])]
            print(f"🔍 RAG loaded {len(self.entries)} vectors ({self.file_path})")
        except FileNotFoundError:
            self.entries = []

    # --------------------
    # SAVE — write vector store to disk
    # --------------------
    def save(self) -> None:
        data = {
            "version": 1,
            "entries": [asdict(e) for e in self.entries],
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # --------------------
    # EMBED — convert text to a vector using nomic-embed-text
    # --------------------
    def embed(self, text: str) -> list[float]:
        res = requests.post(
            self.embed_url,
            json={"model": self.embed_model, "input": text},
            timeout=30,
        )
        res.raise_for_status()
        # Response: { "embeddings": [[...768 numbers...]] }
        return res.json()["embeddings"][0]

    # --------------------
    # ADD — embed a message and store it
    # Only stores conversational facts — never volatile system data
    # --------------------
    def add(
        self,
        text: str,
        role: Literal["user", "assistant"],
        type_: Literal["conversational", "system"],
    ) -> None:
        # Never store system query results — they go stale
        if type_ == "system":
            return

        # Deduplicate — skip if identical text already exists
        text_lower = text.strip().lower()
        for entry in self.entries:
            if entry.text.strip().lower() == text_lower:
                return  # already stored, skip

        # For user messages: only store factual statements, not questions
        # Questions like "do you know my name?" pollute search results
        # because they match future questions better than actual facts
        if role == "user":
            text_stripped = text.strip()
            # Skip if it's a question (ends with ? or starts with question words)
            is_question = (
                text_stripped.endswith("?") or
                text_stripped.lower().startswith(("what", "who", "where", "when",
                                                   "why", "how", "do you", "can you",
                                                   "did you", "is ", "are ", "tell me"))
            )
            if is_question:
                return  # don't store questions — only store facts

        vector = self.embed(text)
        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))

        self.entries.append(VectorEntry(
            id=f"{int(time.time() * 1000)}-{random_suffix}",
            text=text,
            role=role,
            type=type_,
            vector=vector,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        ))

    # --------------------
    # SEARCH — find the top-K most relevant past memories
    # Uses cosine similarity: measures angle between two vectors
    # Score of 1.0 = identical meaning, 0.0 = completely unrelated
    # --------------------
    def search(self, query: str, top_k: int = 5) -> list[VectorEntry]:
        if not self.entries:
            return []

        query_vector = self.embed(query)

        # Score every stored entry against the query
        scored = [
            (entry, cosine_similarity(query_vector, entry.vector))
            for entry in self.entries
        ]

        # Sort by score descending, take top K
        scored.sort(key=lambda x: x[1], reverse=True)
        results = scored[:top_k]

        # Log what was retrieved so you can see RAG working
        print(f"\n🔍 RAG retrieved {len(results)} relevant memories:")
        for i, (entry, score) in enumerate(results):
            preview = entry.text[:60]
            print(f"   {i + 1}. [score: {score:.3f}] \"{preview}...\"")

        return [entry for entry, _ in results]

    # --------------------
    # CLEAR — wipe everything
    # --------------------
    def clear(self) -> None:
        self.entries = []
        try:
            os.remove(self.file_path)
        except FileNotFoundError:
            pass
        print("🗑️  RAG store cleared.")

    def stats(self) -> dict:
        return {"total": len(self.entries), "file_path": self.file_path}


# ============================================================
# COSINE SIMILARITY
# Measures how similar two vectors are in direction (not magnitude)
# Returns a value between -1 and 1 (for text embeddings: 0 to 1)
#
# Formula:
#   similarity = (A · B) / (|A| × |B|)
#
# Python advantage: numpy makes this one line, but we keep it
# explicit here so the math is visible — same as the TS version
# ============================================================

def cosine_similarity(a: list[float], b: list[float]) -> float:  # This function calculates the cosine similarity between two vectors
    # Dot product: how much A and B point in the same direction
    dot = sum(x * y for x, y in zip(a, b))

    # Magnitudes: the "length" of each vector
    mag_a = math.sqrt(sum(x ** 2 for x in a))
    mag_b = math.sqrt(sum(x ** 2 for x in b))

    # Avoid division by zero
    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)
