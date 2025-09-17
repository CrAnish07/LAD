import textwrap

def chunk_text(text, chunk_size=500, overlap=50):
    """
    Break text into overlapping chunks for embedding.
    Useful when documents/logs are too long to embed as a whole.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

def build_context(results, k=3):
    """
    Format retrieved results into a readable context string that will be passed into the LLM.
    """
    ctx_parts = []
    for i, (doc, score) in enumerate(results, start=1):
        snippet = doc.page_content.strip().replace("\n", " ")
        ctx_parts.append(f"[{i}] (score {score:.4f}) {snippet[:500]}")
    return "\n".join(ctx_parts)
