"""
Pydantic extraction schema — 13 typed fields for one biological relation.

Field order matches the intended LLM fill order: extraction_viable is resolved
first; if False, all biological fields stay at defaults. Validation rules:
  - relation must be a value from RelationType (closed taxonomy)
  - subject_type / object_type must be values from EntityType
  - confidence in [0.0, 1.0], reasoning ≥ 50 characters
  - extraction_viable=True requires non-empty subject_name, relation, object_name
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator

from .taxonomy import EntityType, RelationType


class BiologicalRelation(BaseModel):
    """Single extracted biological relation — 13 typed fields."""

    # Gate field — resolved first
    extraction_viable: bool = Field(
        description=(
            "Resolve this FIRST before filling any other field. "
            "True if the chunk contains at least one clear, specific biological "
            "relation between two named entities that maps to the closed taxonomy. "
            "False if the text is purely methodological, statistical, or too vague. "
            "When False — stop: leave all remaining fields at their defaults except reasoning, which must still explain why no relation was found."
        )
    )

    # Subject
    subject_name: str = Field(
        default="",
        description=(
            "Verbatim name of the biological entity on the left side of the relation "
            "as it appears in the source sentence."
        )
    )
    subject_type: EntityType = Field(
        default=EntityType.OTHER,
        description="Entity type of the subject — must match the Layer 4 entity type tag."
    )

    # Relation
    relation: Optional[RelationType] = Field(
        default=None,
        description=(
            "The relation type from the closed taxonomy. "
            "Check each taxonomy entry's definition, example, and not_this before deciding. "
            "If no type fits, set extraction_viable=False instead of guessing."
        )
    )

    # Object
    object_name: str = Field(
        default="",
        description="Verbatim name of the biological entity on the right side of the relation."
    )
    object_type: EntityType = Field(
        default=EntityType.OTHER,
        description="Entity type of the object — must match the Layer 4 entity type tag."
    )

    # Negation
    negated: bool = Field(
        default=False,
        description=(
            "Pass through the negation flag from Layer 4. "
            "True if Layer 4 marks either entity as NEGATED/ABSENT, or if the relation is explicitly negated in the source text "
            "(e.g. 'failed to demonstrate', 'no significant effect')."
        )
    )

    # Confidence
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Your degree of certainty that the extracted relation is correct, from 0.0 to 1.0. "
            "This is your input — the final confidence stored in the knowledge graph is "
            "computed from your value combined with objective signals (section, hedge words, "
            "direct evidence, quantitative measurement). "
            "Be honest: 0.9+ only if the relation is stated explicitly and unambiguously. "
            "0.5–0.7 for inferred, hedged, or background claims."
        )
    )

    # Reasoning trace (mandatory, min 50 chars)
    reasoning: str = Field(
        min_length=50,
        description=(
            "Mandatory reasoning trace of minimum 50 characters. Explain: "
            "(1) which relation type was chosen and why, "
            "(2) what alternatives were considered and rejected, "
            "(3) the verbatim text span that supports this extraction. "
            "Required even when extraction_viable=False — explain why no relation was found."
        )
    )

    # Biological context fields
    species: str = Field(
        default="",
        description=(
            "Organism in which the relation was observed. "
            "Use scientific name where possible — e.g. 'Homo sapiens', "
            "'Mus musculus', 'Caenorhabditis elegans'. Empty if not stated."
        )
    )
    tissue: str = Field(
        default="",
        description=(
            "Tissue, organ, or cell type context — e.g. 'liver', 'hippocampus', "
            "'skeletal muscle', 'HEK293 cells'. Empty if not stated."
        )
    )
    condition: str = Field(
        default="",
        description=(
            "Experimental or physiological condition — e.g. 'caloric restriction', "
            "'ageing', 'hypoxia', 'oxidative stress'. Empty if not stated."
        )
    )
    effect_size: str = Field(
        default="",
        description=(
            "Quantitative magnitude of the effect if reported — e.g. '40% reduction', "
            "'2.5-fold increase', 'hazard ratio 5.67'. Empty if not stated."
        )
    )

    @model_validator(mode="after")
    def require_core_fields_when_viable(self) -> "BiologicalRelation":
        if not self.extraction_viable:
            return self
        missing = []
        if not self.subject_name.strip():
            missing.append("subject_name")
        if self.relation is None:
            missing.append("relation")
        if not self.object_name.strip():
            missing.append("object_name")
        if missing:
            raise ValueError(
                f"extraction_viable=True but required fields are empty: {missing}. "
                f"Populate all three or set extraction_viable=False with a reasoning explanation."
            )
        return self


class ExtractionResult(BaseModel):
    """Full extraction output for one chunk — one BiologicalRelation per distinct triple."""

    relations: List[BiologicalRelation] = Field(
        description=(
            "All biological relations extracted from this chunk. "
            "One entry per distinct subject–relation–object triple. "
            "If no relation is extractable, produce one entry with extraction_viable=False."
        )
    )
    rejected: bool = Field(
        default=False,
        description="True if all 3 Instructor retries failed schema validation. Set by engine."
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Pydantic error from the final retry. Set by engine when rejected=True."
    )
