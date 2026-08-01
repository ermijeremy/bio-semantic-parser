"""
Layer 4 — NER Tagger

Converts spaCy Doc entities into the pipeline's standard entity dict format.
Applies a span quality filter to drop statistical notation, bracket fragments,
and numeric-only spans.
"""


SCISPACY_LABEL_MAP: dict[str, str] = {
    # bc5cdr
    "CHEMICAL":                  "SMALL_MOLECULE",
    "DISEASE":                   "DISEASE",
    # jnlpba
    "DNA":                       "GENE",
    "RNA":                       "NON_CODING_RNA",
    "PROTEIN":                   "PROTEIN",
    "CELL_TYPE":                 "CELL_TYPE",
    "CELL_LINE":                 "CELL_LINE",
    # bionlp13cg
    "AMINO_ACID":                "SMALL_MOLECULE",
    "ANATOMICAL_SYSTEM":         "ANATOMY",
    "CANCER":                    "CANCER",
    "CELL":                      "CELL_TYPE",
    "CELLULAR_COMPONENT":        "CELLULAR_COMPONENT",
    "DEVELOPING_ANATOMICAL_STRUCTURE": "ANATOMY",
    "GENE_OR_GENE_PRODUCT":      "GENE",
    "IMMATERIAL_ANATOMICAL_ENTITY":    "ANATOMY",
    "MULTI_TISSUE_STRUCTURE":    "ANATOMY",
    "ORGAN":                     "ANATOMY",
    "ORGANISM":                  "ORGANISM",
    "ORGANISM_SUBDIVISION":      "ANATOMY",
    "ORGANISM_SUBSTANCE":        "SMALL_MOLECULE",
    "PATHOLOGICAL_FORMATION":    "PATHOLOGICAL_PROCESS",
    "SIMPLE_CHEMICAL":           "SMALL_MOLECULE",
    "TISSUE":                    "TISSUE",
    # en_core_sci_lg
    "ENTITY":                    "OTHER",
}


class NERTagger:
    @staticmethod
    def _is_valid(text: str) -> bool:
        """At least 30% alphabetic characters; must not start with a bracket."""
        if len(text.strip()) < 2:
            return False
        if text[0] in ('[', '('):
            return False
        return sum(c.isalpha() for c in text) / len(text) >= 0.30

    @staticmethod
    def from_doc(doc) -> list:
        seen     = set()
        entities = []
        for ent in doc.ents:
            if not NERTagger._is_valid(ent.text):
                continue
            normalized = ent.text.lower().strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            entities.append({
                "text":       ent.text,
                "normalized": normalized,
                "label":      SCISPACY_LABEL_MAP.get(ent.label_, "OTHER"),
                "start":      ent.start_char,
                "end":        ent.end_char,
                "negated":    False,
                "assertion":  "PRESENT",
                "confidence": 1.0,
            })
        return entities
