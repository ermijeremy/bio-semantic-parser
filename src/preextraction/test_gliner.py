from gliner import GLiNER

labels = ["gene", "drug", "disease", "cancer", "cell line", "cell type", "tissue", "organ", "organism", "transcript", "exon", "non-coding RNA such as miRNA lncRNA or circRNA", "genomic variant or SNP", "sequence variant or point mutation", "structural variant such as CNV deletion or translocation", "regulatory region", "enhancer element", "super-enhancer", "gene promoter", "transcription factor binding site", "epigenomic feature such as histone mark or methylation", "sequence motif or transcription factor motif", "topologically associating domain TAD", "small molecule drug or metabolite", "molecular interaction or protein-protein interaction", "macromolecular complex", "haplotype", "genotype", "phenotype", "clinical symptom", "biological pathway", "biochemical reaction", "biological process", "molecular function", "cellular component or organelle", "three D genome structure or chromatin loop"]                                                                                                                      
text = "Mutations in BRCA1 and BRCA2 genes are associated with an increased risk of breast and ovarian cancer. The protein p53 is a tumor suppressor."                                                                                                             

if __name__ == "__main__":
    model = GLiNER.from_pretrained("Ihor/gliner-biomed-large-v1.0")
    result = model.predict_entities(text, labels, threshold=0.3)
    print(result)