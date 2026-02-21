# Memory Module

The memory module implements persistent searchable storage for document
retrieval. All backends implement the `MemoryBackend` ABC with `store()`,
`retrieve()`, `delete()`, and `clear()` methods. The module also includes
a document ingestion pipeline (chunking, file reading) and context injection
for augmenting prompts with retrieved knowledge.

## Abstract Base Class

### MemoryBackend

::: openjarvis.memory._stubs.MemoryBackend
    options:
      show_source: true
      members_order: source

### RetrievalResult

::: openjarvis.memory._stubs.RetrievalResult
    options:
      show_source: true
      members_order: source

---

## Backend Implementations

### SQLiteMemory

::: openjarvis.memory.sqlite.SQLiteMemory
    options:
      show_source: true
      members_order: source

### FAISSMemory

::: openjarvis.memory.faiss_backend.FAISSMemory
    options:
      show_source: true
      members_order: source

### ColBERTMemory

::: openjarvis.memory.colbert_backend.ColBERTMemory
    options:
      show_source: true
      members_order: source

### BM25Memory

::: openjarvis.memory.bm25.BM25Memory
    options:
      show_source: true
      members_order: source

### HybridMemory

::: openjarvis.memory.hybrid.HybridMemory
    options:
      show_source: true
      members_order: source

### reciprocal_rank_fusion

::: openjarvis.memory.hybrid.reciprocal_rank_fusion
    options:
      show_source: true

---

## Document Chunking

Splits text into fixed-size chunks with configurable overlap, respecting
paragraph boundaries.

### ChunkConfig

::: openjarvis.memory.chunking.ChunkConfig
    options:
      show_source: true
      members_order: source

### Chunk

::: openjarvis.memory.chunking.Chunk
    options:
      show_source: true
      members_order: source

### chunk_text

::: openjarvis.memory.chunking.chunk_text
    options:
      show_source: true

---

## Document Ingestion

File reading, type detection, and directory walking for the ingestion
pipeline.

### DocumentMeta

::: openjarvis.memory.ingest.DocumentMeta
    options:
      show_source: true
      members_order: source

### detect_file_type

::: openjarvis.memory.ingest.detect_file_type
    options:
      show_source: true

### read_document

::: openjarvis.memory.ingest.read_document
    options:
      show_source: true

### ingest_path

::: openjarvis.memory.ingest.ingest_path
    options:
      show_source: true

---

## Context Injection

Retrieves relevant memory and injects it into prompts as system messages
with source attribution.

### ContextConfig

::: openjarvis.memory.context.ContextConfig
    options:
      show_source: true
      members_order: source

### inject_context

::: openjarvis.memory.context.inject_context
    options:
      show_source: true

### format_context

::: openjarvis.memory.context.format_context
    options:
      show_source: true

### build_context_message

::: openjarvis.memory.context.build_context_message
    options:
      show_source: true

---

## Embeddings

Abstraction layer for text embedding models used by dense retrieval backends.

### Embedder

::: openjarvis.memory.embeddings.Embedder
    options:
      show_source: true
      members_order: source

### SentenceTransformerEmbedder

::: openjarvis.memory.embeddings.SentenceTransformerEmbedder
    options:
      show_source: true
      members_order: source
