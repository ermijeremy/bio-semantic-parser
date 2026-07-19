class MetadataAttacher:

    def attach(self, chunks: list, document_id: str, source_name: str,
               source_url: str = "", paper_url: str = "") -> list:
        enriched = []
        for i, chunk in enumerate(chunks):
            enriched.append({
                "text":         chunk["text"],
                "section":      chunk["section"],
                "chunk_index":  chunk["chunk_index"],
                "total_chunks": chunk["total_chunks"],
                "document_id":  document_id,
                "source_name":  source_name,
                "source_url":   paper_url or source_url,
                "position":     i,
            })
        return enriched