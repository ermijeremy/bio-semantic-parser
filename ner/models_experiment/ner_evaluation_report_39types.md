# NER Model Evaluation Report
Corpus: 69 sentences

## Tier Classification
- **Tier 1:** 20 types — ANATOMY, BIOLOGICAL_PROCESS, CANCER, CELLULAR_COMPONENT, CELL_LINE, CELL_TYPE, DISEASE, GENE, GENOMIC_VARIANT, MACROMOLECULAR_COMPLEX, MOLECULAR_FUNCTION, NON_CODING_RNA, ORGANISM, PATHWAY, PHENOTYPE, PROTEIN, SEQUENCE_VARIANT, SMALL_MOLECULE, SYMPTOM, TISSUE
- **Tier 2:** 11 types — DEVELOPMENTAL_STAGE, ENHANCER, EPIGENOMIC_FEATURE, EXPERIMENTAL_FACTOR, HAPLOTYPE, MOLECULAR_INTERACTION, PROMOTER, REACTION, REGULATORY_REGION, TRANSCRIPT, TRANSCRIPTION_FACTOR_BINDING_SITE
- **Tier 3:** 8 types — EXON, GENOTYPE, MOTIF, OTHER, STRUCTURAL_VARIANT, SUPER_ENHANCER, TAD, THREE_D_GENOME_STRUCTURE

## Results

| Rank | Model | Partial F1 | Tier-1 F1 | Coverage | ms |
|---|---|---|---|---|---|
| 1 | GLiNER-BioMed-large | 0.875 | 0.936 | 94.7% | 109.8 |
| 2 | scispaCy Ensemble (baseline) | 0.688 | 0.809 | 28.9% | 34.3 |
| 3 | PubMedBERT-ProteinStructure | 0.284 | 0.347 | 5.3% | 12.7 |
| 4 | BENT-PubMedBERT-Gene | 0.264 | 0.324 | 2.6% | 17.6 |
| 5 | BENT-PubMedBERT-Disease | 0.098 | 0.123 | 2.6% | 39.5 |
| 6 | HunFlair2 | 0.398 | 0.482 | 10.5% | 1188.6 |
| 7 | GLiNER-BioMed-bi-large | 0 | 0 | 0.0% | 61.7 |

## Architecture
**Layer A:** GLiNER-BioMed-large
**Layer B:** BENT-PubMedBERT-Gene + HunFlair2 + PubMedBERT-ProteinStructure
**Layer C:** PubTator3 overlay (canonical IDs)