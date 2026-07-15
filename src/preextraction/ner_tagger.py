"""
Layer 4 — NER Tagger

Converts spaCy Doc entities into the pipeline's standard entity dict format.
Applies a span quality filter to drop statistical notation, bracket fragments,
and numeric-only spans.
"""


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

            key = (normalized, ent.start_char)
            if key in seen:
                continue
            seen.add(key)

            ner_confidence = ent._.score  if ent.has_extension("score")  else 1.0
            source         = ent._.source if ent.has_extension("source") else ""
            entities.append({
                "text":           ent.text,
                "normalized":     normalized,
                "label":          ent.label_,
                "start":          ent.start_char,
                "end":            ent.end_char,
                "negated":        False,
                "assertion":      "PRESENT",
                "ner_confidence": round(float(ner_confidence), 3),
                "source":         source,
                "confidence":     1.0,
            })
        return entities
