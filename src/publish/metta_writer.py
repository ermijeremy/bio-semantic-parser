"""Layer 8 Output B — writes validated relations to MeTTa AtomSpace files."""
import os
import re
from collections import defaultdict
from pathlib import Path


_OUT_DIR = Path(os.getenv("METTA_OUTPUT_DIR", "data/output/metta"))


def _slug(text: str) -> str:
    """Lowercase underscore slug for filenames."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "other").lower()).strip("_")


def _metta_id(canonical_id: str) -> str:
    """
    Convert canonical ID to MeTTa-safe token.
    MESH:D020123 → MESH_D020123  |  2475 → 2475
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", str(canonical_id)).strip("_").upper()


def _metta_val(value: str) -> str:
    """Sanitise a property value for MeTTa."""
    if not value:
        return ""
    v = str(value).replace('"', "'").replace("\n", " ").strip()
    # Wrap in quotes if it contains spaces
    if " " in v or "(" in v or ")" in v:
        return f'"{v}"'
    return v.replace(" ", "_")


def write(records: list, run_dir: Path = None) -> dict:
    """Write all records to MeTTa node and edge files under run_dir/metta/."""
    out_dir = (run_dir / "metta") if run_dir else _OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes: dict = defaultdict(dict)

    for r in records:
        for name_key, type_key, id_key, src_key, review_key in [
            ("subject_name", "subject_type", "subject_id", "subject_id_source", "subject_needs_review"),
            ("object_name",  "object_type",  "object_id",  "object_id_source",  "object_needs_review"),
        ]:
            cid   = r.get(id_key, "") or ""
            name  = r.get(name_key, "") or ""
            etype = r.get(type_key, "OTHER") or "OTHER"
            slug  = _slug(etype)
            if cid and cid not in nodes[slug]:
                nodes[slug][cid] = {
                    "canonical_id": cid,
                    "name":         name,
                    "entity_type":  etype,
                    "id_source":    r.get(src_key, "") or "",
                    "slug":         slug,
                    "needs_review": r.get(review_key, False),
                }

    # ── Write nodes_{entity_type}.metta ──────────────────────────────────────
    node_files: list = []

    for slug, node_map in nodes.items():
        type_dir = out_dir / slug
        type_dir.mkdir(parents=True, exist_ok=True)
        path = type_dir / f"nodes_{slug}.metta"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"; bio-semantic-parser — nodes_{slug}.metta\n\n")
            for row in node_map.values():
                mid   = _metta_id(row["canonical_id"])
                etype = _slug(row["entity_type"])
                f.write(f"({etype} {mid})\n")
                if row["name"]:
                    f.write(f'(name ({etype} {mid}) {_metta_val(row["name"])})\n')
                if row["id_source"]:
                    f.write(f'(id_source ({etype} {mid}) {_metta_val(row["id_source"])})\n')
                needs_review = str(row.get("needs_review", False)).lower()
                f.write(f'(needs_review ({etype} {mid}) {needs_review})\n')
                f.write("\n")
        node_files.append(str(path))

    # ── Group edges by (source_type, relation, target_type) — same as Neo4j ──
    # Edge goes in the SOURCE entity type folder: source/edges_source_rel_target.metta
    edge_groups: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        s_slug = _slug(r.get("subject_type", "OTHER") or "OTHER")
        o_slug = _slug(r.get("object_type",  "OTHER") or "OTHER")
        rel    = _slug(r.get("relation", "related_to") or "related_to")
        edge_groups[s_slug][(rel, o_slug)].append(r)

    edge_files: list = []
    all_slugs = sorted(set(nodes.keys()) | set(edge_groups.keys()))

    for s_slug in all_slugs:
        type_dir = out_dir / s_slug
        type_dir.mkdir(parents=True, exist_ok=True)
        for (rel, o_slug), rows in sorted(edge_groups.get(s_slug, {}).items()):
            file_suffix = f"{s_slug}_{rel}_{o_slug}"
            path        = type_dir / f"edges_{file_suffix}.metta"

            with open(path, "w", encoding="utf-8") as f:
                f.write(f"; bio-semantic-parser — edges_{file_suffix}.metta\n\n")

                for r in rows:
                    s_id = r.get("subject_id", "") or ""
                    o_id = r.get("object_id",  "") or ""
                    if not s_id or not o_id:
                        continue

                    s_mid = _metta_id(s_id)
                    o_mid = _metta_id(o_id)

                    triple = f"({rel} ({s_slug} {s_mid}) ({o_slug} {o_mid}))"
                    f.write(f"{triple}\n")

                    f.write(f"(negated {triple} {str(r.get('negated', False))})\n")

                    doc_id = _metta_val(r.get("document_id", "") or "")
                    if doc_id:
                        f.write(f"(source {triple} {doc_id})\n")

                    paper_source = _metta_val(r.get("source_name", "") or "")
                    if paper_source:
                        f.write(f"(paper_source {triple} {paper_source})\n")

                    paper_url = _metta_val(r.get("source_url", "") or "")
                    if paper_url:
                        f.write(f"(paper_url {triple} {paper_url})\n")

                    section = _metta_val(r.get("section", "") or "")
                    if section:
                        f.write(f"(section {triple} {section})\n")

                    for prop in ["species", "tissue", "condition", "effect_size"]:
                        val = r.get(prop, "") or ""
                        if val:
                            f.write(f"({prop} {triple} {_metta_val(val)})\n")

                    reasoning = (r.get("reasoning", "") or "").strip()[:200]
                    if reasoning:
                        safe_r = reasoning.replace('"', "'").replace("\n", " ")
                        f.write(f'(reasoning {triple} "{safe_r}")\n')

                    f.write("\n")

            edge_files.append(str(path))

    return {
        "output_dir": str(out_dir),
        "node_files": node_files,
        "edge_files": edge_files,
        "node_types": list(nodes.keys()),
        "edge_types": sorted({rel for eg in edge_groups.values() for rel, _ in eg}),
        "node_count": sum(len(v) for v in nodes.values()),
        "edge_count": sum(
            len(rows) for eg in edge_groups.values() for rows in eg.values()
        ),
    }
