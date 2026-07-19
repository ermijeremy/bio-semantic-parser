"""Layer 8 Output A — writes validated relations to Neo4j-importable CSV + Cypher files."""
import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path


_OUT_DIR   = Path(os.getenv("NEO4J_OUTPUT_DIR", "data/output/neo4j"))
_DELIMITER = "|"


def _slug(text: str) -> str:
    """Convert to lowercase underscore slug for use in filenames."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "other").lower()).strip("_")


def write(records: list, run_dir: Path = None) -> dict:
    """Write all records to Neo4j CSV and Cypher files under run_dir/neo4j/."""
    out_dir = (run_dir / "neo4j") if run_dir else _OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Collect unique nodes ──────────────────────────────────────────────────
    # {entity_type_slug: {canonical_id: row_dict}}
    nodes: dict = defaultdict(dict)

    for r in records:
        for name_key, type_key, id_key, src_key, review_key in [
            ("subject_name", "subject_type", "subject_id",
             "subject_id_source", "subject_needs_review"),
            ("object_name",  "object_type",  "object_id",
             "object_id_source", "object_needs_review"),
        ]:
            cid   = r.get(id_key, "") or ""
            name  = r.get(name_key, "") or ""
            etype = r.get(type_key, "OTHER") or "OTHER"
            slug  = _slug(etype)

            if cid and cid not in nodes[slug]:
                nodes[slug][cid] = {
                    "id":           cid,
                    "name":         name,
                    "entity_type":  etype,
                    "id_source":    r.get(src_key, "") or "",
                    "needs_review": str(r.get(review_key, False)).lower(),
                }

    # ── Group edges by (source_type, relation, target_type) — NO duplication ────
    # Edge goes in the SOURCE entity type's folder with a descriptive filename.
    #   protein inhibits gene     → protein/edges_protein_inhibits_gene.csv
    #   gene    regulates protein → gene/edges_gene_regulates_protein.csv
    # {source_slug: {(relation_slug, target_slug): [record, ...]}}
    edge_groups: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        s_slug = _slug(r.get("subject_type", "OTHER") or "OTHER")
        o_slug = _slug(r.get("object_type",  "OTHER") or "OTHER")
        rel    = _slug(r.get("relation", "related_to") or "related_to")
        edge_groups[s_slug][(rel, o_slug)].append(r)

    # ── Write one folder per entity type ─────────────────────────────────────
    # neo4j/{entity_type}/
    #   nodes_{entity_type}.csv       ← all nodes of this type
    #   edges_{relation}.csv          ← edges where THIS type is the source
    node_fields = ["id", "name", "entity_type", "id_source", "needs_review"]
    edge_fields = [
        "source_id", "source_name", "source_type",
        "target_id", "target_name", "target_type",
        "relation",
        "confidence", "negated",
        "species", "tissue", "condition", "effect_size",
        "source_paper", "section",
        "paper_source", "paper_url",
        "validation_verdict", "alignment_action",
        "reasoning", "confidence_channels", "review_reason",
    ]

    node_files: list = []
    edge_files: list = []
    all_slugs = sorted(set(nodes.keys()) | set(edge_groups.keys()))

    for slug in all_slugs:
        type_dir = out_dir / slug
        type_dir.mkdir(parents=True, exist_ok=True)

        # Node file
        if slug in nodes:
            csv_path    = type_dir / f"nodes_{slug}.csv"
            cypher_path = type_dir / f"nodes_{slug}.cypher"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=node_fields,
                                   delimiter=_DELIMITER, extrasaction="ignore")
                w.writeheader()
                for row in nodes[slug].values():
                    w.writerow(row)
            _write_node_cypher(slug, csv_path, cypher_path, out_dir)
            node_files.append(str(csv_path))

        for (rel, o_slug), rows in sorted(edge_groups.get(slug, {}).items()):
            fname       = f"edges_{slug}_{rel}_{o_slug}"
            csv_path    = type_dir / f"{fname}.csv"
            cypher_path = type_dir / f"{fname}.cypher"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=edge_fields,
                                   delimiter=_DELIMITER, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    s_id = r.get("subject_id", "") or ""
                    o_id = r.get("object_id",  "") or ""
                    if not s_id or not o_id or \
                       s_id == "NEEDS_REVIEW" or o_id == "NEEDS_REVIEW":
                        continue
                    w.writerow({
                        "source_id":           s_id,
                        "source_name":         r.get("subject_name", ""),
                        "source_type":         r.get("subject_type", ""),
                        "target_id":           o_id,
                        "target_name":         r.get("object_name",  ""),
                        "target_type":         r.get("object_type",  ""),
                        "relation":            r.get("relation",     "") or rel,
                        "confidence":          r.get("confidence",   0.0),
                        "negated":             str(r.get("negated", False)).lower(),
                        "species":             r.get("species",      ""),
                        "tissue":              r.get("tissue",       ""),
                        "condition":           r.get("condition",    ""),
                        "effect_size":         r.get("effect_size",  ""),
                        "source_paper":        (r.get("document_id", "") or
                                               (json.loads(r.get("source_papers", "[]") or "[]") or [""])[0]),
                        "section":             r.get("section",      ""),
                        "paper_source":        r.get("source_name",  ""),
                        "paper_url":           r.get("source_url",   ""),
                        "validation_verdict":  r.get("validation_verdict", ""),
                        "alignment_action":    r.get("alignment_action",   ""),
                        "reasoning":           (r.get("reasoning", "") or "")[:300],
                        "confidence_channels": json.dumps(r.get("confidence_channels") or {}),
                        "review_reason":       (r.get("review_reason", "") or "")[:200],
                    })
            _write_edge_cypher(rel.upper(), slug, o_slug,
                               csv_path, cypher_path, out_dir)
            edge_files.append(str(csv_path))

    return {
        "output_dir":  str(out_dir),
        "node_files":  node_files,
        "edge_files":  edge_files,
        "node_types":  list(nodes.keys()),
        "edge_types":  sorted({rel for eg in edge_groups.values() for rel, _ in eg}),
        "node_count":  sum(len(v) for v in nodes.values()),
        "edge_count":  sum(
            1
            for eg in edge_groups.values()
            for rows in eg.values()
            for r in rows
            if (r.get("subject_id") and r.get("object_id")
                and r.get("subject_id") != "NEEDS_REVIEW"
                and r.get("object_id") != "NEEDS_REVIEW")
        ),
    }


def _write_node_cypher(label: str, csv_path: Path, cypher_path: Path, out_dir: Path) -> None:
    relative = csv_path.relative_to(out_dir).as_posix()
    query = f"""// nodes_{label}.cypher — generated by bio-semantic-parser Layer 8
CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE;

CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///{relative}' AS row FIELDTERMINATOR '{_DELIMITER}' RETURN row",
    "MERGE (n:{label} {{id: row.id}})
     SET n.name         = row.name,
         n.entity_type  = row.entity_type,
         n.id_source    = row.id_source,
         n.needs_review = row.needs_review",
    {{batchSize: 1000, parallel: true}}
)
YIELD batches, total
RETURN batches, total;
"""
    cypher_path.write_text(query, encoding="utf-8")


def _write_edge_cypher(
    relation: str, source_type: str, target_type: str,
    csv_path: Path, cypher_path: Path, out_dir: Path,
) -> None:
    relative = csv_path.relative_to(out_dir).as_posix()
    query = f"""// {source_type}/edges_{source_type}_{relation.lower()}_{target_type}.cypher

CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///{relative}' AS row FIELDTERMINATOR '{_DELIMITER}' RETURN row",
    "MATCH (source:{source_type} {{id: row.source_id}})
     MATCH (target:{target_type} {{id: row.target_id}})
     CREATE (source)-[r:{relation}]->(target)
     SET r.confidence         = toFloat(row.confidence),
         r.negated            = row.negated,
         r.species            = row.species,
         r.tissue             = row.tissue,
         r.condition          = row.condition,
         r.effect_size        = row.effect_size,
         r.source_paper       = row.source_paper,
         r.section            = row.section,
         r.paper_source       = row.paper_source,
         r.paper_url          = row.paper_url,
         r.validation_verdict = row.validation_verdict,
         r.reasoning          = row.reasoning",
    {{batchSize: 1000}}
)
YIELD batches, total
RETURN batches, total;
"""
    cypher_path.write_text(query, encoding="utf-8")
