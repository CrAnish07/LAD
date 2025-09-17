import os
from dotenv import load_dotenv,find_dotenv
from langchain.vectorstores import Qdrant
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient

load_dotenv(find_dotenv())


def get_vectorstore(client: QdrantClient, collection_name):
    """
    Initialize Qdrant vector store for similarity search.
    Uses Google Gemini embeddings for encoding queries & documents.
    """
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    return Qdrant(
        client=client,
        collection_name=collection_name,
        embeddings=embeddings
    )