"""Layer 7 — post-extraction orchestrator; runs all 7 steps on Layer 6 output."""
import os
from src.schema.pydantic_model import BiologicalRelation, ExtractionResult
from src.postextraction import (
    entity_normalization,
    deduplication,
    contradiction_detection,
    cross_chunk_linking,
    two_pass_resolution,
    semantic_validation,
    atomspace_alignment,
)


from src.postextraction.confidence_scorer import score as _score_confidence

def _compute_confidence(relation, chunk: dict,
                        all_chunks = None) -> tuple:
    """
    Return (score, channels_dict).

    Low C5 = inferred from weak textual evidence, which is honest and correct.
    """
    from src.postextraction.confidence_scorer import explain as _explain

    result = _explain(
        subject_name   = relation.subject_name,
        object_name    = relation.object_name,
        negated        = relation.negated,
        llm_confidence = relation.confidence,
        section        = chunk.get("section", "unknown"),
        text           = chunk.get("text", ""),
        relation       = str(relation.relation),
        reasoning      = relation.reasoning or "",
    )
    return result["final_score"], result["channels"]


def _relation_to_record(
    relation: "BiologicalRelation",
    chunk: dict,
    all_chunks = None,
) -> dict:
    """Flatten a BiologicalRelation + chunk metadata into one flat record dict."""
    return {
        "subject_name":  relation.subject_name,
        "subject_type":  relation.subject_type,
        "relation":      relation.relation,
        "object_name":   relation.object_name,
        "object_type":   relation.object_type,
        "negated":       relation.negated,
        "confidence":    (_conf_score := _compute_confidence(relation, chunk, all_chunks))[0],
        "confidence_channels": _conf_score[1],                  # C1-C5 breakdown for display
        "llm_confidence": relation.confidence,                  # preserve LLM value for audit
        "reasoning":     relation.reasoning,
        "species":       relation.species,
        "tissue":        relation.tissue,
        "condition":     relation.condition,
        "effect_size":   relation.effect_size,
        "document_id":   chunk.get("document_id", ""),
        "source_name":   chunk.get("source_name", ""),
        "source_url":    chunk.get("source_url",  ""),
        "section":       chunk.get("section",     "unknown"),
        "chunk_index":   chunk.get("chunk_index", 0),
        # Multi-chunk papers share the same document_id, so text_by_doc[doc_id]
        # would be overwritten by the LAST chunk — causing all earlier relations
        # to be validated against the wrong text and rejected as hallucinations.
        "_chunk_text":   chunk.get("text", ""),
        "subject_id":          None,
        "subject_id_source":   None,
        "subject_needs_review":False,
        "object_id":           None,
        "object_id_source":    None,
        "object_needs_review": False,
        "is_duplicate":        False,
        "triple_id":           None,
        "is_contradiction":    False,
        "flagged_for_review":  False,
        "review_reason":       "",
        "is_semantically_valid": None,
        "validation_verdict":  "",
        "alignment_action":    "",
    }


def process(
    extraction_pairs: list,
    verbose: bool = False,
    step_cb=None,      # optional callable(step: int, label: str, detail: str)
    batch_cb=None,     # optional callable(batch_done: int, batch_total: int, n_valid: int)
) -> list:
    """Run all 7 Layer 7 steps on the output of Layer 6."""
    def log(msg: str):
        if verbose:
            print(f"  [Layer 7] {msg}")

    def detail(msg: str):
        """Show per-entity / per-record detail — indented under the step."""
        if verbose:
            print(f"  [Layer 7]   {msg}")

    # ── Flatten extraction results into flat records ───────────────
    raw_records = []
    text_by_doc = {}   # {document_id: chunk_text} — used by two-pass resolver

    # Collect all chunks for cross-chunk sentence search in confidence scoring
    all_chunks = [chunk for _, chunk in extraction_pairs]

    # Build (document_id, chunk_index) → chunk lookup to avoid O(N²) scan in Step 1
    _chunk_map: dict = {}
    for result, chunk in extraction_pairs:
        doc_id = chunk.get("document_id", "")
        if doc_id:
            text_by_doc[doc_id] = chunk.get("text", "")
            _chunk_map[(doc_id, chunk.get("chunk_index", 0))] = chunk

        for relation in result.relations:
            if relation.extraction_viable:
                raw_records.append(_relation_to_record(relation, chunk, all_chunks))

    log(f"{len(raw_records)} viable relations to process")

    if not raw_records:
        return []

    # ── Step 1: Entity Normalization ──────────────────────────────
    if step_cb: step_cb(1, "Entity Normalization", f"{len(raw_records)} relations")
    log("Step 1 — Entity Normalization")
    records = []
    _n_total = len(raw_records)
    for _i, record in enumerate(raw_records, 1):
        chunk_for_record = _chunk_map.get(
            (record["document_id"], record.get("chunk_index", 0)), {}
        )
        norm = entity_normalization.normalize_record(record, chunk_for_record)
        records.append(norm)
        if _i % 5 == 0 or _i == _n_total:
            if step_cb: step_cb(1, "Entity Normalization",
                                f"{_i}/{_n_total} normalized")
            log(f"  Entity normalization: {_i}/{_n_total} records")

        # Show what happened to each entity
        s_id  = norm.get("subject_id", "?")
        s_src = norm.get("subject_id_source", "?")
        o_id  = norm.get("object_id", "?")
        o_src = norm.get("object_id_source", "?")
        s_flag = " ⚠ NEEDS REVIEW" if norm.get("subject_needs_review") else ""
        o_flag = " ⚠ NEEDS REVIEW" if norm.get("object_needs_review") else ""
        detail(f"Subject : [{norm['subject_name']}] ({norm['subject_type']})"
               f" → {s_id}  [via {s_src}]{s_flag}")
        detail(f"Object  : [{norm['object_name']}] ({norm['object_type']})"
               f" → {o_id}  [via {o_src}]{o_flag}")
        detail(f"Relation: {norm['relation']}")
        detail("")

    n_resolved = sum(1 for r in records if not (r.get("subject_needs_review") or r.get("object_needs_review")))
    n_review   = sum(1 for r in records if r.get('subject_needs_review') or r.get('object_needs_review'))
    log(f"  → {n_resolved} fully resolved | {n_review} need review")

    # ── Entity ontology gate — flag non-biomedical triples ────────────────────
    # A triple is considered non-biomedical if BOTH subject and object fail to
    # resolve to any recognized ontology (both get TEXT: slugs or NEEDS_REVIEW).
    # This catches app-analytics relations like:
    #   "number of downloads → associates_with → rating score"
    # while keeping valid triples where at least one entity has an ontology ID.
    _ONTOLOGY_PREFIXES = (
        "ENSEMBL:", "NCBI_GENE:", "NCBI_Gene:", "NCBI:", "NCBITaxon:",
        "UniProtKB:", "RxNorm:", "RXCUI:", "WD:",
        "MESH:", "GO:", "ChEBI:", "CHEBI:", "HMDB:", "PUBCHEM:",
        "DOID:", "HP:", "MONDO:", "CL:", "UBERON:", "PR:",
        "EFO:", "RO:", "OMIM:", "KEGG:", "REACTOME:",
    )

    def _has_ontology_id(entity_id: str) -> bool:
        return bool(entity_id) and any(entity_id.startswith(p) for p in _ONTOLOGY_PREFIXES)

    n_flagged_non_bio = 0
    for r in records:
        if r.get("flagged_for_review"):
            continue   # already flagged — don't double-flag
        s_id = r.get("subject_id", "")
        o_id = r.get("object_id",  "")
        s_ok = _has_ontology_id(s_id)
        o_ok = _has_ontology_id(o_id)
        if not s_ok and not o_ok:
            r["flagged_for_review"] = True
            r["review_reason"] = (
                f"Neither entity resolved to a recognized biomedical ontology ID "
                f"(subject_id={s_id!r}, object_id={o_id!r}). "
                f"Triple may involve non-biomedical entities (e.g. app metrics, "
                f"social features, download counts)."
            )
            n_flagged_non_bio += 1
            log(f"  ⚠ Non-biomedical entities — flagged for review: "
                f"[{r.get('subject_name','')}] → [{r.get('object_name','')}]")

    if n_flagged_non_bio:
        log(f"  → {n_flagged_non_bio} triple(s) flagged: both entities lack ontology IDs")

    # ── Step 2: Deduplication ─────────────────────────────────────
    if step_cb: step_cb(2, "Deduplication", "")
    log("Step 2 — Deduplication")
    deduped = []
    for r in records:
        result = deduplication.deduplicate(r)
        deduped.append(result)
        status = "DUPLICATE — confidence updated" if result.get("is_duplicate") else "NEW — inserted"
        detail(f"[{r['subject_name']}] -{r['relation']}→ [{r['object_name']}]  →  {status}"
               f"  (confidence={r.get('confidence',0):.2f})")
    records = deduped
    new_count  = sum(1 for r in records if not r.get("is_duplicate"))
    dupl_count = sum(1 for r in records if r.get("is_duplicate"))
    log(f"  → {new_count} new triples | {dupl_count} duplicates (confidence updated)")

    # ── Step 3: Contradiction Detection ──────────────────────────
    if step_cb: step_cb(3, "Contradiction Detection", "")
    log("Step 3 — Contradiction Detection")
    checked = []
    for r in records:
        result = contradiction_detection.check_contradiction(r)
        checked.append(result)
        if result.get("is_contradiction"):
            detail(f"CONTRADICTION: [{r['subject_name']}] -{r['relation']}→ [{r['object_name']}]")
            detail(f"  reason: {result.get('review_reason','')[:100]}")
        else:
            from src.schema.taxonomy import OPPOSING_RELATIONS, RelationType
            try:
                rel_enum = RelationType(r.get("relation",""))
                opposite = OPPOSING_RELATIONS.get(rel_enum)
                opp_str  = f"'{opposite.value}'" if opposite else "none defined"
            except ValueError:
                opp_str = "?"
            detail(f"[{r['subject_name']}] -{r['relation']}→ [{r['object_name']}]"
                   f"  — opposite={opp_str}  ✓ no conflict found")
    records = checked
    contra_count = sum(1 for r in records if r.get("is_contradiction"))
    log(f"  → {contra_count} contradictions flagged for human review")

    # ── Step 4: Cross-Chunk Linking ───────────────────────────────
    if step_cb: step_cb(4, "Cross-Chunk Linking", "")
    log("Step 4 — Cross-Chunk Linking")
    records = cross_chunk_linking.link_within_paper(records)
    for r in records:
        linked = r.get("linked_indices_in_paper", [])
        total  = r.get("paper_relation_count", 1)
        if linked:
            detail(f"[{r['subject_name']}] -{r['relation']}→ [{r['object_name']}]"
                   f"  — linked to {len(linked)} other relation(s) in same paper"
                   f"  ({total} total in paper)")
        else:
            detail(f"[{r['subject_name']}] -{r['relation']}→ [{r['object_name']}]"
                   f"  — no shared entities with other relations in this paper")
    log(f"  → {len(records)} records after within-paper dedup and linking")

    # ── Step 5: Two-Pass Resolution ───────────────────────────────
    unresolved = sum(1 for r in records
                     if r.get("subject_id") == "NEEDS_REVIEW"
                     or r.get("object_id")  == "NEEDS_REVIEW")
    if unresolved:
        log(f"Step 5 — Two-Pass Resolution ({unresolved} unresolved)")
        for r in records:
            if r.get("subject_id") == "NEEDS_REVIEW":
                detail(f"Unresolved SUBJECT: [{r['subject_name']}] ({r['subject_type']})"
                       f" — sending to LLM for resolution")
            if r.get("object_id") == "NEEDS_REVIEW":
                detail(f"Unresolved OBJECT : [{r['object_name']}] ({r['object_type']})"
                       f" — sending to LLM for resolution")
        records = two_pass_resolution.resolve(records, text_by_doc)
        for r in records:
            if r.get("subject_id") not in ("NEEDS_REVIEW", None):
                detail(f"  [{r['subject_name']}] → now resolved to: {r['subject_id']}")
            if r.get("object_id") not in ("NEEDS_REVIEW", None):
                detail(f"  [{r['object_name']}] → now resolved to: {r['object_id']}")
        still_unresolved = sum(1 for r in records
                               if r.get("subject_id") == "NEEDS_REVIEW"
                               or r.get("object_id")  == "NEEDS_REVIEW")
        log(f"  → {unresolved - still_unresolved} resolved | {still_unresolved} still unresolved")
    else:
        log("Step 5 — Two-Pass Resolution (skipped — all entities resolved)")

    # ── Step 6: Semantic Validation (batched + parallel) ─────────────────────
    log("Step 6 — Semantic Validation")
    from src.postextraction.semantic_validation import _BATCH_SIZE, _BATCH_WORKERS, validate_batch as _vbatch
    log(f"  Batch size: {_BATCH_SIZE} relations/call  ·  Workers: {_BATCH_WORKERS} parallel calls")
    log("  Each batch checks 5 dimensions: subject · object · relation · negation · support")

    # Pair records with their chunk-specific source texts
    active = [r for r in records if not r.get("is_contradiction")]
    skipped_contra = [r for r in records if r.get("is_contradiction")]

    # Group by chunk text so each batch shares ONE full source text (no truncation)
    from collections import defaultdict
    by_chunk: dict = defaultdict(list)
    for r in active:
        chunk_text = r.get("_chunk_text") or text_by_doc.get(r.get("document_id", ""), "")
        by_chunk[chunk_text].append((r, chunk_text))

    # Build batches: split each chunk group by _BATCH_SIZE
    batches = []
    for chunk_text, chunk_pairs in by_chunk.items():
        for i in range(0, len(chunk_pairs), _BATCH_SIZE):
            batches.append(chunk_pairs[i:i+_BATCH_SIZE])

    # Now that active + batches are defined, fire the step callback
    if step_cb: step_cb(6, "Semantic Validation (LLM)",
                        f"{len(active)} relations → {len(batches)} batch(es)")

    pairs = [(r, t) for b in batches for r, t in b]  # flattened for reassembly
    log(f"  {len(active)} relations → {len(batches)} batch(es) grouped by chunk (full text, no truncation)")

    import concurrent.futures
    validated_map: dict = {}

    def _run_batch(idx_batch):
        idx, batch = idx_batch
        results = _vbatch(batch)
        return idx, batch, results

    done_batches = [0]   # mutable counter for thread-safe updates
    with concurrent.futures.ThreadPoolExecutor(max_workers=_BATCH_WORKERS) as pool:
        futures = [pool.submit(_run_batch, (i, b)) for i, b in enumerate(batches)]
        for future in concurrent.futures.as_completed(futures):
            idx, batch, results = future.result()
            for (record, _), result in zip(batch, results):
                key = id(record)
                validated_map[key] = result
            done_batches[0] += 1
            n_valid_batch = sum(1 for r in results if r.get('validation_verdict') == 'VALID')
            if batch_cb:
                batch_cb(done_batches[0], len(batches), n_valid_batch)
            log(f"  Batch {idx+1}/{len(batches)} complete — "
                f"{n_valid_batch} VALID · "
                f"{sum(1 for r in results if r.get('validation_verdict')=='REJECT')} REJECT")

    # Reassemble in original order, adding back skipped contradiction records
    validated = []
    for record in records:
        if record.get("is_contradiction"):
            validated.append({**record, "validation_verdict": "SKIPPED",
                              "validation_reasoning": "already contradiction-flagged"})
        else:
            validated.append(validated_map.get(id(record), {
                **record, "validation_verdict": "SKIPPED",
                "validation_reasoning": "not processed"
            }))

    for result in validated:
        verdict  = result.get("validation_verdict", "SKIPPED")
        name     = f"[{result.get('subject_name','')}] -{result.get('relation','')}→ [{result.get('object_name','')}]"
        issues_by_dim = {}
        for iss in result.get("validation_issues", []):
            if ": " in iss:
                dim_name, desc = iss.split(": ", 1)
                issues_by_dim[dim_name.lower()] = desc
        detail(name)
        dim_map = [
            ("val_subject_correct",  "subject  "),
            ("val_object_correct",   "object   "),
            ("val_relation_correct", "relation "),
            ("val_negation_correct", "negation "),
            ("val_support_strong",   "support  "),
        ]
        for key, label in dim_map:
            ok     = result.get(key, True)
            sym    = "✓" if ok else "✗"
            issue  = issues_by_dim.get(label.strip(), "")
            status = issue[:70] if issue else ("OK" if ok else "FAILED")
            detail(f"  {sym} {label}: {status}")
        reason = result.get("validation_reasoning", "")[:120]
        detail(f"  → verdict: {verdict}  —  {reason}")
        if result.get("suggested_correction"):
            detail(f"  → suggested: {result['suggested_correction'][:80]}")
        detail("")

    # ── REJECT retry: send rejection reason back to LLM, re-validate ────
    # Mirrors extractor.py retry loop — REJECT is final fallback, not first stop.
    _MAX_FIX_RETRIES = 2
    rejects = [(i, r) for i, r in enumerate(validated)
               if r.get("validation_verdict") == "REJECT"
               and r.get("suggested_correction")]

    if rejects:
        log(f"  Attempting LLM correction on {len(rejects)} REJECT(s) "
            f"(max {_MAX_FIX_RETRIES} retries each)…")
        from src.extraction.extractor import _get_system_prompt, _parse_json, _client, _RELATION_VALUES, _ENTITY_VALUES
        from src.schema.pydantic_model import BiologicalRelation as _BR

        for list_idx, rec in rejects:
            chunk_text = rec.get("_chunk_text", "")
            if not chunk_text:
                continue

            current = rec
            for attempt in range(1, _MAX_FIX_RETRIES + 1):
                reason     = current.get("validation_reasoning", "")[:300]
                correction = current.get("suggested_correction", "")[:300]
                fix_user = (
                    f"SECTION: {rec.get('section','unknown')}\n\n"
                    f"TEXT:\n{chunk_text}\n\n"
                    f"PREVIOUS EXTRACTION WAS REJECTED:\n"
                    f"  Subject : {rec.get('subject_name','')}\n"
                    f"  Relation: {rec.get('relation','')}\n"
                    f"  Object  : {rec.get('object_name','')}\n\n"
                    f"REJECTION REASON: {reason}\n"
                    f"SUGGESTED CORRECTION: {correction}\n\n"
                    f"Please provide the corrected extraction as JSON. "
                    f"Use ONLY valid relation values: {_RELATION_VALUES[:300]}…\n"
                    f"Return JSON only — same 13-field format as before."
                )
                try:
                    from src.llm_client import call_llm as _call_llm_post
                    raw  = _call_llm_post(
                        messages=[
                            {"role": "system", "content": _get_system_prompt()},
                            {"role": "user",   "content": fix_user},
                        ],
                        model=os.getenv("LLM_MODEL", "gemma4"),
                        temperature=0.0,
                        max_tokens=int(os.getenv("LLM_OUTPUT_TOKENS", "2048")),
                    )
                    data = _parse_json(raw)
                    rels = data.get("relations", [data])
                    fixed_rel = next(
                        (_BR(**r) for r in rels if r.get("extraction_viable", True)), None
                    )
                    if not fixed_rel:
                        break
                    # Re-validate the corrected extraction
                    fixed_record = dict(rec)
                    fixed_record["subject_name"] = fixed_rel.subject_name
                    fixed_record["subject_type"] = fixed_rel.subject_type
                    fixed_record["relation"]     = fixed_rel.relation
                    fixed_record["object_name"]  = fixed_rel.object_name
                    fixed_record["object_type"]  = fixed_rel.object_type
                    fixed_record["negated"]      = fixed_rel.negated
                    fixed_record["reasoning"]    = fixed_rel.reasoning
                    re_validated = semantic_validation.validate(fixed_record, chunk_text)
                    new_verdict  = re_validated.get("validation_verdict", "REJECT")
                    log(f"    Fix attempt {attempt}/{_MAX_FIX_RETRIES} for "
                        f"[{rec.get('subject_name','')}→{rec.get('relation','')}→"
                        f"{rec.get('object_name','')}]: {new_verdict}")
                    if new_verdict in ("VALID", "REVIEW"):
                        re_validated["_fix_attempts"] = attempt
                        validated[list_idx] = re_validated
                        break
                    current = re_validated   # carry forward new rejection reason for next retry
                except Exception as exc:
                    log(f"    Fix attempt {attempt} failed: {exc}")
                    break

    records = validated
    valid_count  = sum(1 for r in records if r.get("validation_verdict") == "VALID")
    review_count = sum(1 for r in records if r.get("validation_verdict") == "REVIEW")
    reject_count = sum(1 for r in records if r.get("validation_verdict") == "REJECT")
    skip_count   = sum(1 for r in records if r.get("validation_verdict") == "SKIPPED")
    log(f"  → VALID={valid_count} | REVIEW={review_count} | REJECT={reject_count} | SKIPPED={skip_count}")

    # ── Step 7: Atomspace Alignment ───────────────────────────────
    if step_cb: step_cb(7, "Atomspace Alignment", "")
    log("Step 7 — Atomspace Alignment")
    records = atomspace_alignment.align(records)
    for r in records:
        action   = r.get("alignment_action", "?")
        s_exists = r.get("subject_node_exists", False)
        o_exists = r.get("object_node_exists",  False)
        s_mark   = "EXISTS" if s_exists else "NEW"
        o_mark   = "EXISTS" if o_exists else "NEW"
        detail(f"[{r.get('subject_name','')}] ({r.get('subject_id','')})  →  {s_mark}")
        detail(f"[{r.get('object_name', '')}] ({r.get('object_id', '')})  →  {o_mark}")
        detail(f"  action: {action}")
        detail("")
    new_nodes = sum(1 for r in records if r.get("alignment_action") == "both_new")
    connect   = sum(1 for r in records if r.get("alignment_action") == "connect_existing")
    partial   = sum(1 for r in records if r.get("alignment_action") == "create_one_new")
    log(f"  → {connect} connect existing | {partial} one new node | {new_nodes} both new")

    log(f"Layer 7 complete — {len(records)} records ready for Layer 8")

    # Verdicts are assigned after dedup; backfill flagged_for_review so Layer 8 skips REJECT/REVIEW triples.
    import os as _os_sync, sqlite3 as _sq_sync
    _staging_path = _os_sync.getenv("TRIPLE_STORE_PATH", "")
    if _staging_path:
        try:
            with _sq_sync.connect(_staging_path) as _sc:
                for r in records:
                    tid = r.get("triple_id")
                    if not tid:
                        continue
                    verdict = r.get("validation_verdict", "")
                    if verdict in ("REJECT", "REVIEW") or r.get("is_contradiction"):
                        flagged = 1
                    else:
                        flagged = 1 if r.get("flagged_for_review") else 0
                    reason = r.get("review_reason") or (r.get("validation_reasoning") or "")[:500]
                    _sc.execute(
                        "UPDATE triples SET flagged_for_review=?, review_reason=? WHERE id=?",
                        (flagged, reason, tid)
                    )
        except Exception as exc:
            log(f"Failed to sync review flags to staging DB at {_staging_path}: {exc}")

    for r in records:
        doc_id = r.get("document_id", "")
        r["_source_text"] = text_by_doc.get(doc_id, "")
    return records


def process_batch(
    results: list,
    annotated_chunks: list,
    verbose: bool = False,
    step_cb=None,
    batch_cb=None,
) -> list:
    """Convenience wrapper: pair ExtractionResult list with annotated chunk list."""
    pairs = list(zip(results, annotated_chunks))
    return process(pairs, verbose=verbose, step_cb=step_cb, batch_cb=batch_cb)
