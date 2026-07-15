"""Layer 7 step 4 — link relations from the same paper that share a canonical entity ID."""
from collections import defaultdict


def link_within_paper(records: list) -> list:
    """Group records from the same paper and mark shared-entity links."""
    by_doc: dict = defaultdict(list)
    for r in records:
        by_doc[r.get("document_id", "")].append(r)

    result = []
    for doc_id, doc_records in by_doc.items():

        # The same triple can appear in two different chunks due to chunk overlap
        # (the last sentence of chunk N is repeated at the start of chunk N+1).
        # Key = (subject_id, relation, object_id, negated) — if two triples match
        # this key they are the same fact. Keep only the one with higher confidence.
        seen: dict = {}
        deduped = []
        for r in doc_records:
            key = (r.get("subject_id",""), r.get("relation",""), r.get("object_id",""),
                   r.get("negated", False))
            if key in seen:
                existing_idx = seen[key]
                if r.get("confidence", 0) > deduped[existing_idx].get("confidence", 0):
                    deduped[existing_idx] = r
            else:
                seen[key] = len(deduped)
                deduped.append(r)

        entity_to_records: dict = defaultdict(list)
        for idx, r in enumerate(deduped):
            s_id = r.get("subject_id", "")
            o_id = r.get("object_id",  "")
            if s_id and s_id != "NEEDS_REVIEW":
                entity_to_records[s_id].append(idx)
            if o_id and o_id != "NEEDS_REVIEW":
                entity_to_records[o_id].append(idx)

        for idx, r in enumerate(deduped):
            s_id = r.get("subject_id", "")
            o_id = r.get("object_id",  "")
            linked = set()
            for entity in [s_id, o_id]:
                if entity and entity != "NEEDS_REVIEW":
                    for linked_idx in entity_to_records[entity]:
                        if linked_idx != idx:
                            linked.add(linked_idx)
            deduped[idx] = {
                **r,
                "linked_indices_in_paper": sorted(linked),
                "paper_relation_count":    len(deduped),
            }

        result.extend(deduped)

    return result
