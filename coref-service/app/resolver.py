"""Coreference resolver built on fastcoref (LingMess / FCoref).

The models return coreference clusters (groups of spans that refer to the same
entity). They do not return resolved text, so this module also rewrites pronouns
and anaphoric noun phrases to the entity name they refer to.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

PRONOUNS = {
    "i", "me", "my", "mine", "myself",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "we", "us", "our", "ours", "ourselves",
    "they", "them", "their", "theirs", "themselves",
    "this", "that", "these", "those",
    "who", "whom", "whose", "which",
}

POSSESSIVE_PRONOUNS = {
    "my", "your", "his", "her", "its", "our", "their",
    "mine", "yours", "hers", "ours", "theirs", "whose",
}

# Articles that introduce an anaphoric reference, e.g. "the compound", "this gene".
DEFINITE_LEADERS = ("the ", "this ", "that ", "these ", "those ")
ARTICLE_LEADERS = DEFINITE_LEADERS + ("a ", "an ")


class CorefResolver:
    def __init__(self, model_name: str = "lingmess", device: str = "cpu",
                 resolve_mode: str = "anaphora"):
        self.model_name = model_name.lower()
        self.device = device
        # "anaphora": rewrite pronouns and definite/demonstrative noun phrases.
        # "pronouns_only": rewrite pronouns only.
        self.resolve_mode = resolve_mode.lower()
        self._model = None

    def load(self):
        if self._model is not None:
            return
        logger.info("Loading %s on %s", self.model_name, self.device)
        if self.model_name == "fcoref":
            from fastcoref import FCoref
            self._model = FCoref(device=self.device)
        else:
            from fastcoref import LingMessCoref
            self._model = LingMessCoref(device=self.device)

    @property
    def ready(self) -> bool:
        return self._model is not None

    def resolve(self, text: str) -> str:
        if not text or not text.strip():
            return text
        self.load()
        preds = self._model.predict(texts=[text])
        clusters = preds[0].get_clusters(as_strings=False)
        return self._apply_clusters(text, clusters)

    def clusters(self, text: str) -> list:
        if not text or not text.strip():
            return []
        self.load()
        preds = self._model.predict(texts=[text])
        return [
            [{"start": s, "end": e, "text": text[s:e]} for (s, e) in cluster]
            for cluster in preds[0].get_clusters(as_strings=False)
        ]

    def _is_pronoun(self, mention: str) -> bool:
        return mention.strip().lower() in PRONOUNS

    def _is_anaphoric(self, mention: str) -> bool:
        m = mention.strip().lower()
        return m in PRONOUNS or m.startswith(DEFINITE_LEADERS)

    def _should_rewrite(self, mention: str) -> bool:
        if self.resolve_mode == "pronouns_only":
            return self._is_pronoun(mention)
        return self._is_anaphoric(mention)

    def _representative(self, text: str, cluster: List[Tuple[int, int]]) -> Tuple[int, int]:
        # Prefer a named entity (no article) over a definite noun phrase ("the gene"),
        # and a noun phrase over a pronoun. Break ties by longer span.
        def rank(span):
            word = text[span[0]:span[1]].strip().lower()
            return (
                word in PRONOUNS,
                word.startswith(ARTICLE_LEADERS),
                -(span[1] - span[0]),
            )
        return min(cluster, key=rank)

    def _apply_clusters(self, text: str, clusters) -> str:
        replacements = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            rep = self._representative(text, cluster)
            rep_text = text[rep[0]:rep[1]].strip()
            if self._is_pronoun(rep_text):
                continue
            for span in cluster:
                if span == rep:
                    continue
                mention = text[span[0]:span[1]]
                if not self._should_rewrite(mention):
                    continue
                new = rep_text
                if mention.strip().lower() in POSSESSIVE_PRONOUNS:
                    new = rep_text + "'s"
                if mention[:1].isupper():
                    new = new[:1].upper() + new[1:]
                replacements.append((span[0], span[1], new))

        # Apply from the end so earlier offsets stay valid.
        replacements.sort(key=lambda r: r[0], reverse=True)
        out = text
        for start, end, new in replacements:
            out = out[:start] + new + out[end:]
        return out
