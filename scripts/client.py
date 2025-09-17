import os
from dotenv import load_dotenv, find_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from langchain_google_genai import GoogleGenerativeAIEmbeddings

load_dotenv(find_dotenv())

def qdrant_client():
    """Initialize and return a Qdrant client"""
    return QdrantClient(
        os.getenv("QDRANT_HOST"),
        api_key=os.getenv("QDRANT_API_KEY"),
        prefer_grpc=True
    )

def create_collection(client, collecion_name=None):
    """
    Create a Qdrant collection if it does not exist already.
    Collection dimensions are set based on embedding size.
    """
    if not collecion_name:
        collection_name = os.getenv("QDRANT_COLLECTION_NAME")

    # check if collection exists
    collections = client.get_collections().collections
    existing = [c.name for c in collections]

    if collection_name in existing:
        print(f"Collection '{collection_name}' already exists. Skipping creation.")
        return collection_name

    # only create if not exists
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    dims = len(embeddings.embed_query("test"))

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=dims,
            distance=models.Distance.COSINE
        ),
    )
    print(f"Created collection: {collection_name}")
    return collection_name
