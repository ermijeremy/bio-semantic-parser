"""
test_ner_models_wordlevel.py — score the 4 current NER models against a flat
gold term list (term, entity_type), one term/phrase per row, no sentences.

Usage:
    pip install spacy gliner
    python -m spacy download en_ner_bc5cdr_md      # or scispaCy release URLs
    python -m spacy download en_ner_jnlpba_md
    python -m spacy download en_ner_bionlp13cg_md
    python test_ner_models_wordlevel.py gold_term_list.csv
"""

import sys
import csv
import spacy
import time
# from gliner import GLiNER

# ── Load models ────────────────────────────────────────────────────────────
print("Loading models...")
nlp_bc5 = spacy.load("en_ner_bc5cdr_md")       # DISEASE, CHEMICAL
nlp_jnl = spacy.load("en_ner_jnlpba_md")       # DNA, RNA, PROTEIN, CELL_TYPE, CELL_LINE
nlp_bio = spacy.load("en_ner_bionlp13cg_md")   # GENE_OR_GENE_PRODUCT, CANCER, ORGANISM, TISSUE
# gliner  = GLiNER.from_pretrained("Ihor/gliner-biomed-large-v1.0")
print("✓ 4 models loaded\n")

# ── Raw model label → canonical 39-type schema (approximate, best-effort) ───
BC5_MAP = {"DISEASE": "DISEASE", "CHEMICAL": "SMALL_MOLECULE"}
JNL_MAP = {"DNA": "GENE", "RNA": "NON_CODING_RNA", "PROTEIN": "PROTEIN",
           "CELL_TYPE": "CELL_TYPE", "CELL_LINE": "CELL_LINE"}
BIO_MAP = {"GENE_OR_GENE_PRODUCT": "GENE", "CANCER": "CANCER",
           "ORGANISM": "ORGANISM", "TISSUE": "TISSUE",
           "CELL": "CELL_TYPE", "ORGAN": "ANATOMY", "SIMPLE_CHEMICAL": "SMALL_MOLECULE"}

# GLiNER natural-language label → canonical type (covers all 39 schema types)
GLINER_MAP = {
    "gene": "GENE", "protein": "PROTEIN", "RNA transcript or mRNA isoform": "TRANSCRIPT",
    "exon": "EXON", "non-coding RNA such as miRNA lncRNA or circRNA": "NON_CODING_RNA",
    "genomic variant or SNP": "GENOMIC_VARIANT", "sequence variant or point mutation": "SEQUENCE_VARIANT",
    "structural variant such as CNV deletion or translocation": "STRUCTURAL_VARIANT",
    "regulatory region": "REGULATORY_REGION", "enhancer element": "ENHANCER",
    "super-enhancer": "SUPER_ENHANCER", "gene promoter": "PROMOTER",
    "transcription factor binding site": "TRANSCRIPTION_FACTOR_BINDING_SITE",
    "epigenomic feature such as histone mark or methylation": "EPIGENOMIC_FEATURE",
    "sequence motif or transcription factor motif": "MOTIF",
    "topologically associating domain TAD": "TAD",
    "small molecule drug or metabolite": "SMALL_MOLECULE",
    "molecular interaction or protein-protein interaction": "MOLECULAR_INTERACTION",
    "macromolecular complex": "MACROMOLECULAR_COMPLEX", "haplotype": "HAPLOTYPE",
    "genotype": "GENOTYPE", "disease": "DISEASE", "cancer or tumour type": "CANCER",
    "phenotype": "PHENOTYPE", "clinical symptom": "SYMPTOM", "biological pathway": "PATHWAY",
    "biochemical reaction": "REACTION", "biological process": "BIOLOGICAL_PROCESS",
    "molecular function": "MOLECULAR_FUNCTION", "cellular component or organelle": "CELLULAR_COMPONENT",
    "anatomical structure": "ANATOMY", "tissue type": "TISSUE", "cell type": "CELL_TYPE",
    "cell line": "CELL_LINE", "developmental stage or life stage": "DEVELOPMENTAL_STAGE",
    "experimental condition or treatment": "EXPERIMENTAL_FACTOR",
    "3D genome structure or chromatin loop": "THREE_D_GENOME_STRUCTURE",
    "organism or species": "ORGANISM",
}
GLINER_LABELS = list(GLINER_MAP.keys())


def main(csv_path: str):
    with open(csv_path) as f:
        gold = list(csv.DictReader(f))
    print(f"Loaded {len(gold)} gold terms from {csv_path}\n")
    
    results = {}
    time1 = time.time()
    count1 = loss = win = 0
    for row in gold:
        count1 += 1
        term, expected = row["term"], row["entity_type"]
        ents = nlp_bc5(term).ents
        result = BC5_MAP.get(ents[0].label_, ents[0].label_) if ents else None
        if expected == result:
            win += 1
        else:
            loss += 1
    print("\n win:  ", win, " loss: ", loss, "accuracy: ", win/count1)
    time1 = time.time() - time1 

    time2 = time.time()
    count2 = loss = win = 0
    for row in gold:
        count2 += 1
        term, expected = row["term"], row["entity_type"]
        ents = nlp_jnl(term).ents
        result = JNL_MAP.get(ents[0].label_, ents[0].label_) if ents else None
        if expected == result:
            win += 1
        else:
            loss += 1
    print("\n win:  ", win, " loss: ", loss, "accuracy: ", win/count2)
    time2 = time.time() - time2
    
    time3 = time.time()
    count3 = loss = win = 0
    for row in gold:
        count3 += 1
        term, expected = row["term"], row["entity_type"]
        ents = nlp_bio(term).ents
        result = BIO_MAP.get(ents[0].label_, ents[0].label_) if ents else None
        if expected == result:
            win += 1
        else:
            loss += 1

    print("\n win:  ", win, " loss: ", loss, "accuracy: ", win/count3)
    time3 = time.time() - time3
    
    # time4 = time.time()
    # count4 = win = loss = 0
    # for row in gold:
    #     count4 += 1
    #     term, expected = row["term"], row["entity_type"]
    #     ents = gliner.predict_entities(term, GLINER_LABELS, threshold=0.3)
    #     result = GLINER_MAP.get(ents[0]["label"], ents[0]["label"]) if ents else None
    #     if expected == result:
    #         win += 1
    #     else:
    #         loss += 1
    #     print("\n result:  ", result, " expected: ", expected, "  term:  ", term)
    
    #     print("\n win:  ", win, " loss: ", loss, "accuracy: ", win/count4)
    # time4 = time.time() - time4

    print("time for model1: ", time1, "count: ", count1)
    print("time for model2: ", time2, "count: ", count2)
    print("time for model3: ", time3, "count: ", count3)
    # print("time for model4: ", time4, "count: ", count4)

if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "gold_term_list.csv"
    main(csv_file)