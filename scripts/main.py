import os
import glob
import time
from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import build_context
from rag_chain import get_rag_chain


if __name__ == "__main__":

    # Connect to Qdrant
    client = qdrant_client()

    # Create collection if not exists
    collection_name = create_collection(client)
    print(f"Collection created: {collection_name}")

    # Load vector store
    vector_store = get_vectorstore(client, collection_name)

    # Load retrieval-augmented chain
    chain = get_rag_chain()

    # Auto-detect Fluentd buffer file 
    buffer_dir = "../daemon/logs/data.log"
    buffer_files = glob.glob(os.path.join(buffer_dir, "buffer.*.log"))
    if not buffer_files:
        raise FileNotFoundError("No Fluentd buffer log files found.")
    

    buffer_file = max(buffer_files, key=os.path.getmtime)
    print(f"Reading logs from: {buffer_file}")


    try:
        # Stream logs
        with open(buffer_file, "r+") as fobj:

            while True:
                # tail logs from /logs/data.logs/buffer.log
                query = fobj.readline()
                if not query:
                    time.sleep(0.5)  # wait for new logs to arrive
                    continue
                
                query = query.strip()
                if not query:
                    continue

                # retrieve
                results = vector_store.similarity_search_with_score(query, k=3)
                context = build_context(results)

                response = chain.invoke({"query": query, "context": context})
                print("\n=== Response ===")
                print(response.content)
    
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected, clearing buffer file...")
        with open(buffer_file, "w") as f:  # truncate file
            f.truncate(0)
        print("Buffer file cleared. Exiting.")
