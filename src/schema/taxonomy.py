"""
Component 1 — Relationship Taxonomy
────────────────────────────────────
Single source of truth for all biological relation types used in extraction.

Sources (5 schemas — all aligned to 100% coverage)
────────────────────────────────────────────────────
  • BioNLP Shared Tasks          — gene/protein event ontology (GE, EPI, BB tasks)
                                   https://sites.google.com/site/bionlpst/
                                   Paper: https://aclanthology.org/W11-1801
  • Hetionet v1.0                — network medicine metaedge types
                                   https://het.io/ | https://github.com/hetio/hetionet
                                   https://github.com/hetio/hetionet/blob/main/describe/definitions.json
  • OpenBioLink                  — large-scale KG benchmark edge types
                                   https://github.com/OpenBioLink/OpenBioLink
                                   Paper: https://doi.org/10.1093/bioinformatics/btaa274
  • BioCypher primer schema      — node types + regulatory/genomic/ontology edges
                                   https://biocypher.org/ | https://github.com/biocypher/biocypher
                                   Paper: https://doi.org/10.1038/s41587-023-01848-y
  • Biolink Model v4.4.2         — standard biological predicate ontology (100% mapped)
                                   https://biolink.github.io/biolink-model/
                                   https://github.com/biolink/biolink-model

When different schemas refer to the same biological concept using different
names, ONE canonical English verb is chosen here and all aliases are recorded
in SYNONYM_MAP below. This prevents the same relationship from being stored
under multiple labels in the knowledge graph.

File structure (8 sections)
────────────────────────────
  1. RelationType enum     — 87 approved types organised into 22 categories
  2. EntityType enum       — 39 node types (BioCypher + Biolink aligned)
  3. SectionLabel enum     — document section tags
  4. TAXONOMY dict         — definition + example + not_this for every type
  5. SYNONYM_MAP           — empty stub (moved to tools/build_taxonomy.py)
  6. CROSS_SCHEMA_MAP      — canonical → equivalent name in each source schema
  7. BIOLINK_MAPPING       — canonical → biolink predicate (used by Layer 7)
  8. OPPOSING_RELATIONS    — contradiction pairs (used by Layer 7)

Note on SYNONYM_MAP
───────────────────
The synonym map was an offline audit lookup used only by tools/build_taxonomy.py
to check coverage against external schemas. It is NOT used at runtime — the LLM
normalises predicates directly from the closed taxonomy in the extraction prompt.
Hardcoding synonyms in the runtime schema is the wrong approach for scale; the
correct approach is embedding-based semantic matching if ever needed at runtime.

Growth policy
─────────────
This is a static closed enum — updated offline, not at runtime.
When the extraction engine encounters a relation that fits no type here,
the chunk is routed to the human review queue. A new type is added only
after domain-expert approval and ≥ 3 independent paper occurrences.
"""
from enum import Enum
from typing import Dict


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Relation types and categories
# ══════════════════════════════════════════════════════════════════════════════

class RelationType(str, Enum):

    # ── Category 1: Gene / RNA Expression ─────────────────────────────────────
    # BioNLP: Gene_expression, Transcription, Translation
    # Hetionet: AeG (Anatomy-expresses-Gene)
    # OpenBioLink: GENE_ANATOMY expressed_in
    EXPRESSED_IN     = "expressed_in"       # gene/protein detected in tissue or cell type
    TRANSCRIBES_TO   = "transcribes_to"     # DNA/gene → RNA product
    TRANSLATES_TO    = "translates_to"      # mRNA → protein product

    # ── Category 2: Activity Regulation ───────────────────────────────────────
    # BioNLP: Positive_regulation, Negative_regulation, Regulation
    # Hetionet: upregulates (AuG,CuG,DuG), downregulates (AdG,CdG,DdG), GrG
    ACTIVATES        = "activates"          # increases activity/function of a molecule
    INHIBITS         = "inhibits"           # decreases activity/function of a molecule
    UPREGULATES      = "upregulates"        # increases mRNA or protein abundance
    DOWNREGULATES    = "downregulates"      # decreases mRNA or protein abundance
    REGULATES        = "regulates"          # direction unspecified or bidirectional

    # ── Category 3: Post-Translational Modifications (PTMs) ───────────────────
    # BioNLP EPI task: Phosphorylation, Dephosphorylation, Methylation,
    #   Acetylation, Deacetylation, Ubiquitination, Deubiquitination,
    #   Sumoylation, Desumoylation, Hydroxylation, Dehydroxylation,
    #   Glycosylation, Deglycosylation, Neddylation, Deneddylation
    PHOSPHORYLATES   = "phosphorylates"     # kinase adds phosphate group
    DEPHOSPHORYLATES = "dephosphorylates"   # phosphatase removes phosphate group
    METHYLATES       = "methylates"         # methyltransferase adds methyl group
    DEMETHYLATES     = "demethylates"       # demethylase removes methyl group (DNA or protein)
    ACETYLATES       = "acetylates"         # acetyltransferase adds acetyl group
    DEACETYLATES     = "deacetylates"       # deacetylase (sirtuin/HDAC) removes acetyl group
    UBIQUITINATES    = "ubiquitinates"      # E3 ligase adds ubiquitin tag
    DEUBIQUITINATES  = "deubiquitinates"    # deubiquitinase (DUB) removes ubiquitin tag
    SUMOYLATES       = "sumoylates"         # SUMO ligase adds SUMO modifier
    DESUMOYLATES     = "desumoylates"       # SUMO protease removes SUMO modifier
    HYDROXYLATES     = "hydroxylates"       # hydroxylase adds hydroxyl group
    DEHYDROXYLATES   = "dehydroxylates"     # removes hydroxyl group
    GLYCOSYLATES     = "glycosylates"       # adds sugar moiety (O-GlcNAc, N-glycan)
    DEGLYCOSYLATES   = "deglycosylates"     # removes glycan / sugar moiety
    NEDDYLATES       = "neddylates"         # NEDD8 E3 ligase adds NEDD8 modifier
    DENEDDYLATES     = "deneddylates"       # deneddylase removes NEDD8 modifier

    # ── Category 4: Molecular Interactions ────────────────────────────────────
    # BioNLP: Binding
    # Hetionet: CbG (Compound-binds-Gene), GiG (Gene-interacts-Gene)
    # OpenBioLink: GENE_GENE interacts, GENE_DRUG targeted_by
    BINDS_TO         = "binds_to"           # direct demonstrated molecular binding
    INTERACTS_WITH   = "interacts_with"     # functional/genetic interaction, binding not proven
    IS_TARGET_OF     = "is_target_of"       # gene/protein is validated pharmacological target of drug

    # ── Category 5: Localisation, Transport & Secretion ──────────────────────
    # BioNLP: Localization, Transport
    # Hetionet: DlA (Disease-localizes-Anatomy)
    LOCALIZES_TO     = "localizes_to"       # protein found in or translocates to compartment/location
    TRANSPORTS       = "transports"         # active shuttling of molecule between compartments
    SECRETES         = "secretes"           # cell/organelle releases molecule into extracellular space

    # ── Category 6: Metabolic, Structural & Process Membership ────────────────
    # BioNLP: Conversion, Protein_catabolism, Protein_processing
    # Hetionet: GpPW/GpBP/GpCC/GpMF, PCiC (Pharmacologic Class-includes-Compound)
    # OpenBioLink: GENE_CATALYSIS_GENE, DRUG_CATALYSIS_GENE, participates_in (GO), ANATOMY_ANATOMY part_of
    # Biolink: catalyzes (is_a: participates in)
    CONVERTS_TO      = "converts_to"        # enzymatic transformation of A into distinct product B
    CLEAVES          = "cleaves"            # proteolytic cleavage of B by protease A
    CATALYZES        = "catalyzes"          # enzyme A catalyzes biochemical reaction or process B
    DEGRADES         = "degrades"           # proteolysis / autophagy / catabolism of B
    PARTICIPATES_IN  = "participates_in"    # gene/protein/compound is member of pathway or process
    PART_OF          = "part_of"            # A is a structural physical subunit or component of B
    IS_MEMBER_OF     = "is_member_of"       # compound/entity belongs to class or pharmacological family

    # ── Category 7: Causal / Mechanistic ──────────────────────────────────────
    CAUSES           = "causes"             # A is direct sufficient cause of B (experimentally proven)
    PROMOTES         = "promotes"           # A facilitates / accelerates B without direct causation
    PREVENTS         = "prevents"           # A blocks / suppresses occurrence of B

    # ── Category 8: Clinical / Therapeutic ────────────────────────────────────
    # Hetionet: CtD (Compound-treats-Disease), CpD (Compound-palliates-Disease)
    # OpenBioLink: indicated_for, biomarker_for
    TREATS           = "treats"             # intervention resolves or reverses disease B
    PALLIATES        = "palliates"          # intervention reduces severity without curing B
    BIOMARKER_FOR    = "biomarker_for"      # A indicates presence/risk/stage of condition B

    # ── Category 9: Statistical / Epidemiological ─────────────────────────────
    # Hetionet: DaG (associates), GcG (covaries), DrD/CrC (resembles)
    # OpenBioLink: associated_with (DisGeNET/OMIM)
    # Biolink: coexpressed with (is_a: correlated with); is missense/frameshift/splice variant of
    ASSOCIATES_WITH  = "associates_with"    # co-occurrence / genetic link, no established causality
    CORRELATES_WITH  = "correlates_with"    # statistical co-variation across samples or conditions
    COEXPRESSED_WITH = "coexpressed_with"   # genes show correlated expression across tissues/conditions
    RESEMBLES        = "resembles"          # structural/functional/phenotypic similarity
    PREDICTS         = "predicts"           # A forecasts future outcome B (prognostic)
    IS_VARIANT_OF    = "is_variant_of"      # genomic variant A is a variant of gene/sequence B

    # ── Category 10: Disease / Phenotype ──────────────────────────────────────
    # Hetionet: DpS (Disease-presents-Symptom)
    # OpenBioLink: DISEASE_PHENOTYPE, GENE_PHENOTYPE
    HAS_SYMPTOM      = "has_symptom"        # disease clinically presents with symptom B
    HAS_PHENOTYPE    = "has_phenotype"      # gene/variant/intervention produces phenotype B

    # ── Category 11: Longevity-Specific (domain extension) ────────────────────
    # Not present in BioNLP / Hetionet / OpenBioLink — added for longevity domain.
    # Sources:
    #   - DrugAge: curated assays with lifespan change (%) and increasing/decreasing outcomes
    #     https://genomics.senescence.info/drugs/
    #   - WHO HALE / healthy ageing: healthy years and functional ability are distinct from lifespan
    #     https://www.who.int/data/gho/indicator-metadata-registry/imr-details/7752
    #     https://www.who.int/news-room/questions-and-answers/item/healthy-ageing-and-functional-ability
    #   - GO:0043697 cell dedifferentiation + partial reprogramming aging literature
    #     https://www.ebi.ac.uk/QuickGO/term/GO:0043697
    #     https://doi.org/10.1016/j.cell.2016.11.052
    EXTENDS_LIFESPAN    = "extends_lifespan"    # intervention/gene increases measured total lifespan
    REDUCES_LIFESPAN    = "reduces_lifespan"    # mutation/compound decreases measured total lifespan
    EXTENDS_HEALTHSPAN  = "extends_healthspan"  # prolongs healthy disease-free period without necessarily total lifespan
    REDUCES_HEALTHSPAN  = "reduces_healthspan"  # shortens healthy functional period, accelerating age-related decline
    REPROGRAMS          = "reprograms"          # resets epigenetic/developmental state to younger or pluripotent identity

    # ── Category 12: Infection / Microbiology ─────────────────────────────────
    # BioNLP ID 2011 task: Infection, Immune_response
    INFECTS          = "infects"            # pathogen A infects / colonises host B

    # ── Category 13: Homology (BioCypher orthology/paralogy associations) ──────
    # BioCypher: orthology_association (DIOPT score), paralogy_association
    ORTHOLOG_OF      = "ortholog_of"        # gene X is ortholog of gene Y (speciation event)
    PARALOG_OF       = "paralog_of"         # gene X is paralog of gene Y (duplication event)

    # ── Category 14: Ontology hierarchy (BioCypher subclass_of / part_of) ─────
    # BioCypher: do_subclass_of, cl_subclass_of, hpo_subclass_of, etc.
    SUBCLASS_OF      = "subclass_of"        # term X is a subtype/subclass of term Y
    HAS_PART         = "has_part"           # X has Y as a component part

    # ── Category 15: Regulatory genomics (BioCypher regulatory_association) ───
    # BioCypher: non-coding elements regulating gene expression
    REGULATES_EXPRESSION_OF = "regulates_expression_of"  # regulatory element controls gene expression
    TARGETS                 = "targets"                  # TF / regulatory factor targets gene/region
    OPEN_CHROMATIN_AT       = "open_chromatin_at"        # chromatin accessible at this genomic region

    # ── Category 16: Genomic overlap (BioCypher structural variant associations) ─
    # BioCypher: feature_overlaps_structural_variant, gene_overlaps_structural_variant, etc.
    OVERLAPS                = "overlaps"                 # genomic feature A overlaps feature B by chromosomal coordinate

    # ── Category 17: Capability (BioCypher cl_capable_of) ─────────────────────
    # BioCypher: cl_capable_of (cell type → biological process)
    CAPABLE_OF              = "capable_of"               # entity (cell type, organism) is capable of performing process

    # ── Category 18: GO/RO molecular function relations (Biolink) ──────────────
    # biolink:enables, biolink:acts_upstream_of, biolink:contributes_to, biolink:occurs_in
    ENABLES                       = "enables"                       # gene product enables a molecular function/activity (GO:enables)
    ACTS_UPSTREAM_OF              = "acts_upstream_of"              # gene product is causally upstream of a biological process (RO:0002263)
    CONTRIBUTES_TO                = "contributes_to"                # gene/variant partially contributes to disease or process onset
    OCCURS_IN                     = "occurs_in"                     # biological process/event occurs in anatomical entity or cell type

    # ── Category 19: Developmental lineage (Biolink) ───────────────────────────
    # biolink:develops_from, biolink:derives_from
    DEVELOPS_FROM                 = "develops_from"                 # cell type / tissue develops from a precursor entity (RO:0002202)
    DERIVES_FROM                  = "derives_from"                  # entity is derived/produced from another entity (metabolite, product)

    # ── Category 20: Substrate / co-localisation (Biolink) ─────────────────────
    # biolink:has_substrate, biolink:colocalizes_with
    HAS_SUBSTRATE                 = "has_substrate"                 # enzyme or reaction has this molecule as substrate
    COLOCALIZES_WITH              = "colocalizes_with"              # two entities found in the same cellular/tissue location

    # ── Category 21: Clinical / pharmacological (Biolink) ──────────────────────
    # biolink:diagnoses, biolink:contraindicated_in, biolink:in_clinical_trials_for
    DIAGNOSES                     = "diagnoses"                     # clinical test / biomarker diagnoses a disease or condition
    CONTRAINDICATED_IN            = "contraindicated_in"            # drug/treatment is contraindicated in a disease or patient group
    IN_CLINICAL_TRIALS_FOR        = "in_clinical_trials_for"        # drug/intervention is currently in clinical trials for a disease

    # ── Category 23: Clinical outcome / risk relations (Biolink v4) ────────────
    # biolink:predisposes (RO:0003302), biolink:manifestation_of (RO:0002452),
    # biolink:associated_with_likelihood_of
    PREDISPOSES                   = "predisposes"                   # A increases probability/risk of B without being sufficient cause (biolink:predisposes / RO:0003302)
    MANIFESTATION_OF              = "manifestation_of"              # phenotypic feature / clinical sign A is a manifestation of disease B (biolink:manifestation_of / RO:0002452)
    ASSOCIATED_WITH_LIKELIHOOD_OF = "associated_with_likelihood_of" # statistical/probabilistic evidence that entity A correlates with altered likelihood of condition B (biolink:associated_with_likelihood_of)

    # ── Category 22: Biolink completeness additions ─────────────────────────────
    # Inverse transcript/protein relations, complex membership, metabolite,
    # genetic/pharmacological interaction, temporal, amelioration, exacerbation, taxon
    TRANSCRIBED_FROM              = "transcribed_from"              # transcript is transcribed from gene (biolink:transcribed_from / RO:0002511)
    TRANSLATION_OF                = "translation_of"                # protein is the translation of transcript (biolink:translation_of)
    IN_COMPLEX_WITH               = "in_complex_with"               # two entities are subunits of the same molecular complex
    HAS_METABOLITE                = "has_metabolite"                # reaction / enzyme / pathway has this molecule as a metabolite product
    GENETICALLY_INTERACTS_WITH    = "genetically_interacts_with"    # genetic interaction — epistasis, synthetic lethality, suppression
    PHARMACOLOGICALLY_INTERACTS_WITH = "pharmacologically_interacts_with"  # drug–drug or drug–target pharmacological interaction
    PRECEDES                      = "precedes"                      # event / process A occurs before event / process B in time
    AMELIORATES                   = "ameliorates"                   # treatment / gene mitigates severity without curing (weaker than treats)
    EXACERBATES                   = "exacerbates"                   # gene / compound worsens or accelerates a disease or condition
    IN_TAXON                      = "in_taxon"                      # biological entity belongs to / is found in this organism taxon


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Entity types (mirror BioCypher schema node types)
# ══════════════════════════════════════════════════════════════════════════════

class EntityType(str, Enum):
    # ── Coding / sequence elements ────────────────────────────────────────────
    GENE                        = "GENE"                        # Ensembl / NCBI Gene ID
    PROTEIN                     = "PROTEIN"                     # UniProt accession
    TRANSCRIPT                  = "TRANSCRIPT"                  # Ensembl transcript ID
    EXON                        = "EXON"                        # Exon within a transcript
    NON_CODING_RNA              = "NON_CODING_RNA"              # miRNA, lncRNA, circRNA, piRNA

    # ── Genomic variation ─────────────────────────────────────────────────────
    GENOMIC_VARIANT             = "GENOMIC_VARIANT"             # rsID / SNP / small sequence variant
    SEQUENCE_VARIANT            = "SEQUENCE_VARIANT"            # specific DNA sequence alteration (ClinVar)
    STRUCTURAL_VARIANT          = "STRUCTURAL_VARIANT"          # large-scale rearrangement: CNV, SV, indel >50bp

    # ── Regulatory & epigenomic elements ─────────────────────────────────────
    REGULATORY_REGION           = "REGULATORY_REGION"           # general regulatory region
    ENHANCER                    = "ENHANCER"                    # enhancer element
    SUPER_ENHANCER              = "SUPER_ENHANCER"              # cluster of enhancers with high TF occupancy
    PROMOTER                    = "PROMOTER"                    # promoter region
    TRANSCRIPTION_FACTOR_BINDING_SITE = "TRANSCRIPTION_FACTOR_BINDING_SITE"  # TFBS
    EPIGENOMIC_FEATURE          = "EPIGENOMIC_FEATURE"          # epigenetic modification region
    MOTIF                       = "MOTIF"                       # TF binding motif (PWM)
    TAD                         = "TAD"                         # Topologically Associating Domain (Hi-C)

    # ── Chemistry & molecules ─────────────────────────────────────────────────
    SMALL_MOLECULE              = "SMALL_MOLECULE"              # ChEBI (drugs, metabolites, compounds)
    MOLECULAR_INTERACTION       = "MOLECULAR_INTERACTION"       # documented molecular interaction complex (IntAct/BioGRID)
    MACROMOLECULAR_COMPLEX      = "MACROMOLECULAR_COMPLEX"      # stable protein/nucleic acid complex (e.g. PRC2, ribosome)

    # ── Genetic composition ───────────────────────────────────────────────────
    HAPLOTYPE                   = "HAPLOTYPE"                   # set of co-inherited alleles on one chromosome
    GENOTYPE                    = "GENOTYPE"                    # full genetic makeup of an individual or strain

    # ── Disease & phenotype ───────────────────────────────────────────────────
    DISEASE                     = "DISEASE"                     # MeSH:D… / OMIM / DOID
    CANCER                      = "CANCER"                      # cancer subtype (MeSH:D…)
    PHENOTYPE                   = "PHENOTYPE"                   # HPO term
    SYMPTOM                     = "SYMPTOM"                     # clinical symptom (HPO / MeSH)

    # ── Biological processes & functions ─────────────────────────────────────
    PATHWAY                     = "PATHWAY"                     # Reactome / KEGG pathway ID
    REACTION                    = "REACTION"                    # Reactome biochemical reaction
    BIOLOGICAL_PROCESS          = "BIOLOGICAL_PROCESS"          # GO:XXXXXXX (BP)
    MOLECULAR_FUNCTION          = "MOLECULAR_FUNCTION"          # GO:XXXXXXX (MF)
    CELLULAR_COMPONENT          = "CELLULAR_COMPONENT"          # GO:XXXXXXX (CC)

    # ── Anatomy & cell biology ────────────────────────────────────────────────
    ANATOMY                     = "ANATOMY"                     # UBERON anatomical entity
    TISSUE                      = "TISSUE"                      # BTO tissue term
    CELL_TYPE                   = "CELL_TYPE"                   # CL cell ontology term
    CELL_LINE                   = "CELL_LINE"                   # CLO cell line
    DEVELOPMENTAL_STAGE         = "DEVELOPMENTAL_STAGE"         # HsapDv / developmental life stage

    # ── Experimental context ──────────────────────────────────────────────────
    EXPERIMENTAL_FACTOR         = "EXPERIMENTAL_FACTOR"         # EFO-derived experimental condition / treatment variable
    THREE_D_GENOME_STRUCTURE    = "THREE_D_GENOME_STRUCTURE"    # 3D chromatin organisation feature (Hi-C compartment/loop)

    # ── Taxonomy ──────────────────────────────────────────────────────────────
    ORGANISM                    = "ORGANISM"                    # NCBI Taxonomy ID

    # ── Clinical entities (biolink:ClinicalEntity hierarchy) ──────────────────
    # Source: Biolink Model v4.4.2 — classes extracted directly from biolink-model.yaml
    CLINICAL_ENTITY             = "CLINICAL_ENTITY"             # biolink:ClinicalEntity — any entity in the clinical domain outside the biological realm
    CLINICAL_INTERVENTION       = "CLINICAL_INTERVENTION"       # biolink:ClinicalIntervention — medical procedure, treatment, or action taken to modify the course of a disease (e.g. home BP monitoring, surgery, therapy)
    CLINICAL_FINDING            = "CLINICAL_FINDING"            # biolink:ClinicalFinding — clinical observation, lab measurement, or biological feature observed in a patient
    PROCEDURE                   = "PROCEDURE"                   # biolink:Procedure — a series of actions conducted in a certain order or manner (medical or experimental)
    DEVICE                      = "DEVICE"                      # biolink:Device — a piece of mechanical or electronic equipment used for a specific purpose (e.g. monitoring device, implant)
    DIAGNOSTIC_AID              = "DIAGNOSTIC_AID"              # biolink:DiagnosticAid — a device or substance used to help diagnose disease or injury
    TREATMENT                   = "TREATMENT"                   # biolink:Treatment — a treatment targeted at a disease or phenotype, may involve drugs, procedures, or behavioral interventions
    DRUG                        = "DRUG"                        # biolink:Drug — a substance for diagnosis, cure, mitigation, treatment, or prevention of disease (broader than SMALL_MOLECULE; includes biologics)

    # ── Exposure & environment ────────────────────────────────────────────────
    EXPOSURE_EVENT              = "EXPOSURE_EVENT"              # biolink:ExposureEvent — incidence of an environmental feature that influences an organism (chemical, behavioral, geographic)
    CHEMICAL_EXPOSURE           = "CHEMICAL_EXPOSURE"           # biolink:ChemicalExposure — intake of a particular chemical entity
    BEHAVIORAL_EXPOSURE         = "BEHAVIORAL_EXPOSURE"         # biolink:BehavioralExposure — a factor relating to behavior impacting an individual
    ENVIRONMENTAL_EXPOSURE      = "ENVIRONMENTAL_EXPOSURE"      # biolink:EnvironmentalExposure — factor relating to abiotic processes in the environment
    ENVIRONMENTAL_FEATURE       = "ENVIRONMENTAL_FEATURE"       # biolink:EnvironmentalFeature — a system or entity in the natural environment (abiotic)
    FOOD                        = "FOOD"                        # biolink:Food — a substance consumed to provide nutritional support (e.g. low-sodium diet, processed food)

    # ── Behavior & activity ───────────────────────────────────────────────────
    ACTIVITY                    = "ACTIVITY"                    # biolink:Activity — something that occurs over a period of time and acts upon entities (includes study, trial, clinical activity)
    BEHAVIOR                    = "BEHAVIOR"                    # biolink:Behavior — the internally coordinated responses of organisms to internal or external stimuli (lifestyle, adherence)
    BEHAVIORAL_FEATURE          = "BEHAVIORAL_FEATURE"          # biolink:BehavioralFeature — a phenotypic feature which is behavioral in nature

    # ── Physiological & pathological processes ────────────────────────────────
    PHYSIOLOGICAL_PROCESS       = "PHYSIOLOGICAL_PROCESS"       # biolink:PhysiologicalProcess — a biological or chemical function within a living organism (e.g. blood pressure regulation)
    PATHOLOGICAL_PROCESS        = "PATHOLOGICAL_PROCESS"        # biolink:PathologicalProcess — a biologic function having an abnormal or deleterious effect at subcellular or organismal level

    # ── Population & study ───────────────────────────────────────────────────
    POPULATION                  = "POPULATION"                  # biolink:PopulationOfIndividualOrganisms — a collection of individuals from the same taxonomic class (e.g. patient cohort)
    COHORT                      = "COHORT"                      # biolink:Cohort — a group treated as a group who share common characteristics in a study
    STUDY                       = "STUDY"                       # biolink:Study — a detailed investigation and/or analysis
    CLINICAL_TRIAL              = "CLINICAL_TRIAL"              # biolink:ClinicalTrial — a research study that prospectively assigns participants to interventions

    # ── Organism ─────────────────────────────────────────────────────────────
    LIFE_STAGE                  = "LIFE_STAGE"                  # biolink:LifeStage — a stage of development or growth of an organism, including post-natal adult stages (e.g. elderly, adolescent)
    INDIVIDUAL_ORGANISM         = "INDIVIDUAL_ORGANISM"         # biolink:IndividualOrganism — a single instance of an organism (e.g. a patient, a model animal)

    # ── Clinical attributes & outcomes (biolink:Attribute subclasses) ────────
    CLINICAL_MEASUREMENT        = "CLINICAL_MEASUREMENT"        # biolink:ClinicalMeasurement — a lab or clinical observation result (e.g. blood pressure reading, BMI, HbA1c level)
    CLINICAL_ATTRIBUTE          = "CLINICAL_ATTRIBUTE"          # biolink:ClinicalAttribute — general attribute relating to a clinical manifestation
    ONSET                       = "ONSET"                       # biolink:Onset — the age group or time point at which disease symptoms first appear
    EPIDEMIOLOGICAL_OUTCOME     = "EPIDEMIOLOGICAL_OUTCOME"     # biolink:EpidemiologicalOutcome — a societal or population-level outcome such as disease burden, incidence rate, or mortality
    MORTALITY_OUTCOME           = "MORTALITY_OUTCOME"           # biolink:MortalityOutcome — an outcome of death resulting from an exposure event or disease
    BEHAVIORAL_OUTCOME          = "BEHAVIORAL_OUTCOME"          # biolink:BehavioralOutcome — an outcome resulting from an exposure event manifested as human behavior
    DISEASE_OUTCOME             = "DISEASE_OUTCOME"             # biolink:DiseaseOrPhenotypicFeatureOutcome — physiological outcome resulting from an exposure event

    # ── Clinical patient ──────────────────────────────────────────────────────
    CASE                        = "CASE"                        # biolink:Case — an individual human organism that has a patient role in a clinical context

    # ── Specific anatomical / genomic ─────────────────────────────────────────
    GROSS_ANATOMICAL_STRUCTURE  = "GROSS_ANATOMICAL_STRUCTURE"  # biolink:GrossAnatomicalStructure — an anatomical structure with more than one cell (e.g. organ, limb, gland)
    GENOME                      = "GENOME"                      # biolink:Genome — the sum of genetic material within a cell or virion
    GENETIC_INHERITANCE         = "GENETIC_INHERITANCE"         # biolink:GeneticInheritance — the pattern or mode in which a genetic trait or disorder is passed across generations
    VIRUS                       = "VIRUS"                       # biolink:Virus — a virus organism (for virology, infectious disease papers)
    MICRO_RNA                   = "MICRO_RNA"                   # biolink:MicroRNA — a small (~22 nt) endogenous RNA that regulates gene expression post-transcriptionally
    SI_RNA                      = "SI_RNA"                      # biolink:SiRNA — a small RNA produced from exogenous or endogenous dsRNA used in gene silencing

    # ── Population & study subtypes ───────────────────────────────────────────
    STUDY_POPULATION            = "STUDY_POPULATION"            # biolink:StudyPopulation — a group of people treated as participants in a research study
    ORGANISM_TAXON              = "ORGANISM_TAXON"              # biolink:OrganismTaxon — a taxonomic classification (e.g. NCBITaxon:9606 Homo sapiens)

    # ── Events & phenomena ────────────────────────────────────────────────────
    EVENT                       = "EVENT"                       # biolink:Event — something that happens at a given place and time (biological or clinical event)
    PHENOMENON                  = "PHENOMENON"                  # biolink:Phenomenon — an observed fact or situation whose cause may be under investigation
    ENVIRONMENTAL_PROCESS       = "ENVIRONMENTAL_PROCESS"       # biolink:EnvironmentalProcess — a process that occurs within or involves components of an environmental system

    # ── Catch-all ─────────────────────────────────────────────────────────────
    OTHER                       = "OTHER"                       # does not fit above — flag for review


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Section labels
# ══════════════════════════════════════════════════════════════════════════════

class SectionLabel(str, Enum):
    ABSTRACT      = "abstract"
    INTRODUCTION  = "introduction"
    METHODS       = "methods"
    RESULTS       = "results"
    DISCUSSION    = "discussion"
    SUPPLEMENTARY = "supplementary"
    UNKNOWN       = "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Full definitions (given to LLM in the extraction prompt)
# Each entry: definition · example · not_this
# Sources: https://biolink.github.io/biolink-model/ · https://github.com/hetio/hetionet/blob/main/describe/definitions.json
# ══════════════════════════════════════════════════════════════════════════════

TAXONOMY: Dict[RelationType, dict] = {

    # ── Category 1: Expression ────────────────────────────────────────────────

    RelationType.EXPRESSED_IN: {
        "definition": "Gene or protein A is detected at measurable levels in tissue, organ, or cell type B. Captures baseline expression patterns.",
        "example": "FOXO3 is highly expressed in hippocampal neurons of long-lived centenarian subjects.",
        "not_this": "Use LOCALIZES_TO if the focus is on subcellular compartment. Use UPREGULATES/DOWNREGULATES if an expression change is the finding, not baseline presence. Use TRANSCRIBES_TO if the transcription event itself is described.",
    },
    RelationType.TRANSCRIBES_TO: {
        "definition": "Gene or DNA template A is transcribed by RNA polymerase to produce RNA product B (mRNA, miRNA, lncRNA, etc.).",
        "example": "The SIRT1 gene transcribes to produce SIRT1 mRNA at elevated rates under caloric restriction.",
        "not_this": "Use TRANSLATES_TO if the source is mRNA and the product is protein. Use EXPRESSED_IN if baseline tissue expression is the finding, not the transcription event.",
    },
    RelationType.TRANSLATES_TO: {
        "definition": "mRNA A is translated by the ribosome to produce protein B.",
        "example": "SIRT1 mRNA translates to SIRT1 protein, with translation efficiency increasing under nutrient deprivation.",
        "not_this": "Use TRANSCRIBES_TO if the source is DNA and the product is RNA. Use EXPRESSED_IN if protein abundance in tissue is the finding, not the translation event.",
    },

    # ── Category 2: Activity Regulation ──────────────────────────────────────

    RelationType.ACTIVATES: {
        "definition": "A increases or triggers the activity, function, or signalling of B. Effect is on molecular activity, not transcript abundance.",
        "example": "Caloric restriction activates AMPK in the hypothalamus of aged mice.",
        "not_this": "Use UPREGULATES if the effect is on mRNA or protein abundance. Use PROMOTES if A facilitates a broader biological process rather than a single molecule.",
    },
    RelationType.INHIBITS: {
        "definition": "A directly reduces or blocks the activity, function, or signalling of B. Effect is on molecular activity, not abundance.",
        "example": "Rapamycin inhibits mTOR complex 1 activity by 40% in aged cells.",
        "not_this": "Use DOWNREGULATES if the effect is on mRNA or protein abundance. Use PREVENTS if A stops a process or event from occurring.",
    },
    RelationType.UPREGULATES: {
        "definition": "A increases the expression level of B — specifically mRNA abundance or protein abundance as measured by sequencing, qPCR, or proteomics.",
        "example": "Fasting upregulates SIRT1 mRNA expression 2.5-fold in mouse liver.",
        "not_this": "Use ACTIVATES if the effect is on protein activity rather than abundance. Use TRANSCRIBES_TO if the transcription event itself is described.",
    },
    RelationType.DOWNREGULATES: {
        "definition": "A decreases the expression level of B — specifically mRNA or protein abundance as measured by molecular assays (sequencing, qPCR, proteomics). Strictly molecular: subject and object must be genes, proteins, or molecular entities.",
        "example": "Ageing downregulates FOXO3 protein levels in human skeletal muscle.",
        "not_this": "Use INHIBITS if the effect is on protein activity rather than abundance. Use PREVENTS if A blocks a process. Use REGULATES if the subject is a dietary factor, clinical intervention, or physiological condition affecting a non-molecular outcome (e.g. sodium intake and blood pressure — use REGULATES, not DOWNREGULATES).",
    },
    RelationType.REGULATES: {
        "definition": "A modulates B without a specified direction, or controls B in a context-dependent bidirectional manner. Applies at any level: molecular (gene/protein), physiological (e.g. dietary sodium regulates blood pressure), or clinical (e.g. treatment regulates glucose levels).",
        "example": "mTORC1 regulates autophagy depending on nutrient availability.",
        "not_this": "Prefer ACTIVATES/INHIBITS or UPREGULATES/DOWNREGULATES when the effect is specifically on mRNA or protein abundance. Use REGULATES for physiological, dietary, or clinical regulation where direction is unspecified or context-dependent. Do NOT use DOWNREGULATES for dietary or physiological effects on non-molecular outcomes — use REGULATES instead.",
    },

    # ── Category 3: PTMs ──────────────────────────────────────────────────────

    RelationType.PHOSPHORYLATES: {
        "definition": "A (a kinase) covalently adds a phosphate group to B at a specific residue, altering B's activity, stability, or localisation.",
        "example": "AKT1 phosphorylates FOXO3 at Ser253, triggering its nuclear exclusion.",
        "not_this": "Use ACTIVATES/INHIBITS to describe only the functional consequence if the phosphorylation mechanism is not the finding. Use DEPHOSPHORYLATES for the reverse reaction.",
    },
    RelationType.DEPHOSPHORYLATES: {
        "definition": "A (a phosphatase) removes a phosphate group from B, reversing a prior phosphorylation event and altering B's activity.",
        "example": "PP2A dephosphorylates AKT at Thr308, reducing insulin signalling in aged muscle tissue.",
        "not_this": "Use PHOSPHORYLATES for the addition reaction. Use INHIBITS if only the functional suppression is reported without the phosphatase mechanism.",
    },
    RelationType.METHYLATES: {
        "definition": "A (a methyltransferase) adds a methyl group to B, typically at a histone tail or DNA CpG site, altering gene expression or protein function.",
        "example": "DNMT3A methylates the CDKN2A promoter CpG islands, silencing expression in aged cells.",
        "not_this": "Use DOWNREGULATES if only the transcriptional consequence is reported. Use DEMETHYLATES for the reverse reaction.",
    },
    RelationType.DEMETHYLATES: {
        "definition": "A (a demethylase, e.g. TET enzyme, KDM family) removes a methyl group from B (DNA CpG site or histone residue), reversing methylation-mediated silencing.",
        "example": "TET2 demethylates the FOXO3 promoter, reactivating FOXO3 expression in aged hematopoietic stem cells.",
        "not_this": "Use METHYLATES for the addition reaction. Use UPREGULATES if only the transcriptional reactivation consequence is described.",
    },
    RelationType.ACETYLATES: {
        "definition": "A (an acetyltransferase) adds an acetyl group to B, typically modifying histone tails or protein stability.",
        "example": "p300 acetylates H3K27 at enhancers of senescence-associated secretory phenotype genes.",
        "not_this": "Use DEACETYLATES for the reverse reaction. Use METHYLATES or PHOSPHORYLATES for other modifications.",
    },
    RelationType.DEACETYLATES: {
        "definition": "A (a deacetylase, e.g. sirtuin or HDAC) removes an acetyl group from B, typically restoring chromatin compaction or altering protein stability.",
        "example": "SIRT1 deacetylates H3K56ac at senescence-associated gene promoters in aged cells.",
        "not_this": "Use ACETYLATES for the addition reaction. Use DOWNREGULATES if only the transcriptional silencing consequence is reported.",
    },
    RelationType.UBIQUITINATES: {
        "definition": "A (an E3 ubiquitin ligase) tags B with ubiquitin chains, typically targeting B for proteasomal degradation or altering its function.",
        "example": "MDM2 ubiquitinates TP53, targeting it for proteasomal degradation in proliferating cells.",
        "not_this": "Use DEGRADES if only the degradation outcome is described without the ubiquitination mechanism. Use SUMOYLATES for SUMO modification.",
    },
    RelationType.SUMOYLATES: {
        "definition": "A (a SUMO E3 ligase) adds a SUMO (Small Ubiquitin-like Modifier) tag to B, altering its nuclear localisation, stability, or protein interactions.",
        "example": "PIAS1 sumoylates FOXO4 at Lys188, promoting its transcriptional activity under stress.",
        "not_this": "Use UBIQUITINATES if ubiquitin (not SUMO) is the modifier. Use DESUMOYLATES for the reverse reaction.",
    },
    RelationType.DESUMOYLATES: {
        "definition": "A (a SUMO-specific protease, SENP family) removes a SUMO modifier from B, reversing sumoylation.",
        "example": "SENP1 desumoylates HIF-1α, stabilising its transcriptional activity under hypoxia.",
        "not_this": "Use SUMOYLATES for the addition reaction. Use DEUBIQUITINATES if ubiquitin (not SUMO) is removed.",
    },
    RelationType.DEUBIQUITINATES: {
        "definition": "A (a deubiquitinase, DUB enzyme) removes ubiquitin chains from B, reversing ubiquitination and rescuing B from proteasomal degradation.",
        "example": "USP7 deubiquitinates MDM2, stabilising MDM2 and promoting TP53 degradation.",
        "not_this": "Use UBIQUITINATES for the addition reaction. Use DESUMOYLATES if SUMO (not ubiquitin) is removed.",
    },
    RelationType.HYDROXYLATES: {
        "definition": "A (a hydroxylase enzyme, e.g. PHD1/2/3) adds a hydroxyl group to B, typically marking it for recognition or proteasomal degradation.",
        "example": "PHD2 hydroxylates HIF-1α at Pro564 under normoxia, targeting it for VHL-mediated degradation.",
        "not_this": "Use DEGRADES if the degradation outcome is the finding, not the hydroxylation mechanism. Use DEHYDROXYLATES for the reverse reaction.",
    },
    RelationType.DEHYDROXYLATES: {
        "definition": "A removes a hydroxyl group from B, reversing prior hydroxylation.",
        "example": "FIH dehydroxylates HIF-1α under specific conditions, reducing its transcriptional activation.",
        "not_this": "Use HYDROXYLATES for the addition reaction.",
    },
    RelationType.GLYCOSYLATES: {
        "definition": "A adds a sugar moiety (glycan) to B — includes O-GlcNAcylation on serine/threonine and N-glycosylation on asparagine.",
        "example": "OGT glycosylates histone H3 at Ser10, competing with phosphorylation at this residue in aged cells.",
        "not_this": "Use PHOSPHORYLATES if a phosphate rather than a sugar is added. Use DEGLYCOSYLATES for the reverse reaction.",
    },
    RelationType.DEGLYCOSYLATES: {
        "definition": "A (a glycosidase or deglycosylase) removes a glycan or sugar moiety from B.",
        "example": "OGA deglycosylates O-GlcNAc-modified proteins during mitosis, restoring normal signalling.",
        "not_this": "Use GLYCOSYLATES for the addition reaction.",
    },
    RelationType.NEDDYLATES: {
        "definition": "A (a NEDD8 E3 ligase) conjugates NEDD8 to B (typically a cullin), activating E3 ubiquitin ligase complexes.",
        "example": "UBC12 neddylates CUL1 at Lys720, activating SCF complex E3 ligase activity.",
        "not_this": "Use UBIQUITINATES if ubiquitin (not NEDD8) is added. Use DENEDDYLATES for the reverse reaction.",
    },
    RelationType.DENEDDYLATES: {
        "definition": "A (the COP9 signalosome or deneddylase) removes NEDD8 from B, inactivating the E3 ubiquitin ligase complex.",
        "example": "The COP9 signalosome deneddylates CUL1, downregulating SCF-mediated ubiquitination.",
        "not_this": "Use NEDDYLATES for the addition reaction.",
    },

    # ── Category 4: Molecular Interactions ───────────────────────────────────

    RelationType.BINDS_TO: {
        "definition": "A forms a direct, demonstrated physical molecular bond with B — receptor-ligand, protein-protein domain contact, or protein-DNA binding confirmed by biochemical assay.",
        "example": "Rapamycin binds to FKBP12, forming a ternary complex that allosterically inhibits mTOR.",
        "not_this": "Use INTERACTS_WITH for functional interactions where direct binding is not demonstrated. Use IS_TARGET_OF for validated pharmacological target relationships.",
    },
    RelationType.INTERACTS_WITH: {
        "definition": "A and B have a functional, genetic, or co-immunoprecipitation interaction where direct molecular binding is not explicitly demonstrated.",
        "example": "SIRT1 interacts with FOXO3 in a calorie-restriction-dependent nutrient-sensing complex.",
        "not_this": "Use BINDS_TO if direct molecular binding is confirmed by biochemical assay. Use IS_TARGET_OF if A is a validated drug target.",
    },
    RelationType.IS_TARGET_OF: {
        "definition": "Gene, protein, or molecular entity A is a validated pharmacological or experimental target of drug or compound B.",
        "example": "mTOR is a direct molecular target of rapamycin, mediating its lifespan-extending effects.",
        "not_this": "Use BINDS_TO if only physical binding is demonstrated without established target relationship. Use INHIBITS if the functional consequence rather than target status is the finding.",
    },

    # ── Category 5: Localisation & Transport ─────────────────────────────────

    RelationType.LOCALIZES_TO: {
        "definition": "Protein or molecule A is found in, or translocates to, subcellular compartment or anatomical location B.",
        "example": "FOXO3 localizes to the nucleus following AMPK activation under low nutrient conditions.",
        "not_this": "Use EXPRESSED_IN if the finding is tissue-level gene expression rather than subcellular location. Use TRANSPORTS if an active shuttling mechanism is described.",
    },
    RelationType.TRANSPORTS: {
        "definition": "A actively moves or shuttles molecule B between compartments or across membranes via a transport mechanism.",
        "example": "ABCA1 transports cholesterol from macrophages across the plasma membrane to nascent HDL particles.",
        "not_this": "Use LOCALIZES_TO if the result (new location) rather than the transport mechanism is the focus. Use SECRETES if A releases B into the extracellular space.",
    },
    RelationType.SECRETES: {
        "definition": "Cell type, organelle, or organism A releases molecule B into the extracellular space, bloodstream, or surrounding tissue — through exocytosis, vesicle release, or secretory pathway.",
        "example": "Senescent fibroblasts secrete IL-6, IL-8 and MMP-3 as core components of the senescence-associated secretory phenotype (SASP).",
        "not_this": "Use TRANSPORTS if A shuttles B across a membrane without release into extracellular space. Use CONVERTS_TO if A chemically transforms B. Use PROMOTES if A stimulates another cell to secrete B.",
    },

    # ── Category 6: Metabolic, Structural & Process Membership ───────────────

    RelationType.CONVERTS_TO: {
        "definition": "A is enzymatically or chemically transformed into B, changing its molecular identity in a metabolic reaction.",
        "example": "Glucose is converted to pyruvate via glycolysis in aged hepatocytes with impaired oxidative phosphorylation.",
        "not_this": "Use DEGRADES if the conversion destroys A without producing a distinct product B. Use PHOSPHORYLATES/METHYLATES if A is modified covalently but retains identity.",
    },
    RelationType.CATALYZES: {
        "definition": "Enzyme A directly catalyzes biochemical reaction or biological process B, providing the activation energy reduction for the reaction to proceed.",
        "example": "Telomerase catalyzes the addition of telomeric repeats to chromosome ends in stem cells.",
        "not_this": "Use CONVERTS_TO if the specific substrate-to-product transformation is the finding. Use REGULATES if A controls the rate of B without being the direct catalyst. Use PARTICIPATES_IN for general pathway membership.",
    },
    RelationType.CLEAVES: {
        "definition": "Protease or enzyme A performs proteolytic cleavage of B, cutting the peptide bond at a specific site and producing defined cleavage fragments.",
        "example": "Caspase-3 cleaves PARP-1 at Asp214, generating an 85 kDa fragment — a hallmark of apoptosis.",
        "not_this": "Use DEGRADES if B is completely destroyed rather than cleaved into defined fragments. Use CONVERTS_TO if cleavage produces a specific biochemically active product.",
    },
    RelationType.DEGRADES: {
        "definition": "A breaks down or destroys B through proteolysis, autophagy, lysosomal catabolism, or proteasomal degradation.",
        "example": "The 26S proteasome degrades ubiquitinated TP53 in normally proliferating cells.",
        "not_this": "Use UBIQUITINATES if the tagging mechanism is the finding. Use CLEAVES if A produces specific defined fragments from B.",
    },
    RelationType.PARTICIPATES_IN: {
        "definition": "Gene, protein, or compound A is a functional member of pathway or biological process B, contributing to its execution.",
        "example": "FOXO3 participates in the insulin/IGF-1 signalling pathway as a transcription factor target.",
        "not_this": "Use REGULATES if A controls the pathway rather than being a member. Use PART_OF if A is a structural physical component rather than a functional participant.",
    },
    RelationType.PART_OF: {
        "definition": "A is a structural physical subunit, component, or anatomical subdivision of B.",
        "example": "The hippocampus is part of the medial temporal lobe memory system, showing accelerated atrophy in Alzheimer's disease.",
        "not_this": "Use PARTICIPATES_IN if A functionally contributes to a biological process rather than being a structural component. Use LOCALIZES_TO if the focus is where A is found, not structural membership.",
    },
    RelationType.IS_MEMBER_OF: {
        "definition": "Compound or entity A belongs to pharmacological class, protein family, or functional category B.",
        "example": "Rapamycin is a member of the macrolide class of compounds with selective mTOR-inhibitory properties.",
        "not_this": "Use PART_OF if A is a physical structural component of B. Use PARTICIPATES_IN if A functionally contributes to a process rather than being classified in a category.",
    },

    # ── Category 7: Causal / Mechanistic ─────────────────────────────────────

    RelationType.CAUSES: {
        "definition": "A is a direct, sufficient causal factor that brings about condition, disease, or event B. Causality is experimentally or epidemiologically established.",
        "example": "Telomere shortening causes replicative senescence in primary human fibroblasts.",
        "not_this": "Use PROMOTES if A facilitates rather than directly causes B. Use ASSOCIATES_WITH if causality is not experimentally established.",
    },
    RelationType.PROMOTES: {
        "definition": "A facilitates, accelerates, or increases the likelihood of process or outcome B without being a direct sufficient cause.",
        "example": "Caloric restriction promotes autophagy in liver, muscle, and brain tissue of aged rodents.",
        "not_this": "Use CAUSES if A is the direct and sufficient experimental cause. Use ACTIVATES if A directly increases activity of a specific protein.",
    },
    RelationType.PREVENTS: {
        "definition": "A blocks, suppresses, or reduces the occurrence or onset of process, disease, or outcome B.",
        "example": "Regular aerobic exercise prevents age-related muscle atrophy in elderly human subjects.",
        "not_this": "Use INHIBITS if A directly blocks a specific molecular activity. Use TREATS if A is a therapeutic for an already established disease.",
    },

    # ── Category 8: Clinical / Therapeutic ───────────────────────────────────

    RelationType.TREATS: {
        "definition": "Intervention or drug A reduces, reverses, or resolves the symptoms or underlying pathology of disease B.",
        "example": "Metformin treats type 2 diabetes by reducing hepatic glucose production and improving insulin sensitivity.",
        "not_this": "Use PALLIATES if A reduces severity without curing the underlying condition. Use PREVENTS if A stops onset of B before it occurs.",
    },
    RelationType.PALLIATES: {
        "definition": "A reduces the severity, symptoms, or burden of disease B without curing or eliminating the underlying condition.",
        "example": "Low-dose aspirin palliates chronic systemic inflammation in elderly arthritis patients.",
        "not_this": "Use TREATS if A resolves the underlying condition. Use PREVENTS if A stops B from occurring.",
    },
    RelationType.BIOMARKER_FOR: {
        "definition": "Molecule or measurement A reliably indicates the presence, risk, stage, or progression of condition B in a clinically validated context.",
        "example": "Elevated p21 protein expression is a validated biomarker for cellular senescence in human tissue sections.",
        "not_this": "Use PREDICTS if A forecasts a future outcome rather than indicating current state. Use ASSOCIATES_WITH if co-occurrence is shown without biomarker validation.",
    },

    # ── Category 9: Statistical / Epidemiological ─────────────────────────────

    RelationType.ASSOCIATES_WITH: {
        "definition": "A and B co-occur or are statistically linked in epidemiological or genetic studies, without established directionality or mechanistic causality.",
        "example": "FOXO3 longevity variants associate with exceptional lifespan in multiple independent GWAS cohorts.",
        "not_this": "Use CAUSES if experimental causality is established. Use CORRELATES_WITH if the finding is a statistical co-variation between two continuous measurements.",
    },
    RelationType.CORRELATES_WITH: {
        "definition": "A and B show a statistical co-variation across conditions, samples, time points, or individuals, without a causal claim.",
        "example": "NAD+ levels positively correlate with mitochondrial respiratory capacity across age groups.",
        "not_this": "Use ASSOCIATES_WITH for genetic or epidemiological co-occurrence (GWAS alleles). Use CAUSES if experimental data establish causality.",
    },
    RelationType.COEXPRESSED_WITH: {
        "definition": "Gene or protein A shows correlated expression levels with B across multiple tissues, conditions, or single-cell profiles — both go up or down together.",
        "example": "SIRT1 is coexpressed with FOXO3 across 54 human tissues in GTEx, suggesting shared regulatory control.",
        "not_this": "Use CORRELATES_WITH for general statistical co-variation between non-expression measurements. Use ASSOCIATES_WITH for genetic co-occurrence (GWAS) rather than expression correlation. Use REGULATES if A directly controls B's expression level.",
    },
    RelationType.IS_VARIANT_OF: {
        "definition": "Genomic variant A (SNP, indel, structural variant) is a sequence variant of gene or genomic region B. Covers missense, nonsense, frameshift, splice-site, and synonymous variants.",
        "example": "The rs2802292 SNP is a variant of FOXO3 and is associated with human longevity in multiple populations.",
        "not_this": "Use ASSOCIATES_WITH if only the statistical co-occurrence with disease or phenotype is reported, not the variant-gene relationship. Use HAS_PHENOTYPE if the focus is on what phenotype the variant produces.",
    },
    RelationType.RESEMBLES: {
        "definition": "A and B share substantial structural, functional, or phenotypic similarity. Commonly used for disease-disease or compound-compound comparisons.",
        "example": "Hutchinson-Gilford Progeria syndrome resembles accelerated normal human ageing at the molecular level.",
        "not_this": "Use HAS_PHENOTYPE to describe a specific phenotypic feature rather than overall similarity.",
    },
    RelationType.PREDICTS: {
        "definition": "A (a measurement, signature, marker, or clinical test) reliably forecasts future outcome or event B in patients or experimental subjects.",
        "example": "The 76-gene expression signature predicts distant metastasis within 5 years in lymph-node-negative breast cancer.",
        "not_this": "Use BIOMARKER_FOR if A indicates current state rather than forecasting future outcome. Use CORRELATES_WITH if the relationship is statistical co-variation without demonstrated prognostic utility.",
    },

    # ── Category 10: Disease / Phenotype ─────────────────────────────────────

    RelationType.HAS_SYMPTOM: {
        "definition": "Disease or condition A clinically presents with observable symptom or clinical sign B in patients.",
        "example": "Werner syndrome presents with premature ageing symptoms including bilateral cataracts and atherosclerosis.",
        "not_this": "Use HAS_PHENOTYPE if B is a molecular or cellular phenotype rather than a clinical symptom. Use CAUSES if the mechanism by which A produces B is described.",
    },
    RelationType.HAS_PHENOTYPE: {
        "definition": "Gene, variant, or experimental intervention A produces a reproducible molecular, cellular, or organismal phenotype B.",
        "example": "SIRT1 knockout mice exhibit a phenotype of accelerated metabolic ageing and increased fat accumulation.",
        "not_this": "Use HAS_SYMPTOM if B is a clinical symptom in a patient context. Use CAUSES if the mechanism of phenotype production is described.",
    },

    # ── Category 11: Longevity-Specific ──────────────────────────────────────

    RelationType.EXTENDS_LIFESPAN: {
        "definition": "Intervention, gene variant, or compound A significantly increases the lifespan of organism B in controlled experimental or epidemiological studies.",
        "example": "Caloric restriction extends lifespan in C. elegans by approximately 30% compared to ad-libitum controls.",
        "not_this": "Use PROMOTES if A improves healthspan without a measured lifespan extension. Use TREATS if A addresses a specific disease rather than the ageing process itself.",
    },
    RelationType.REDUCES_LIFESPAN: {
        "definition": "Mutation, compound, or condition A significantly decreases the total lifespan of organism B in controlled studies.",
        "example": "Loss-of-function mutation in daf-16 reduces lifespan in C. elegans by 50% versus wild type.",
        "not_this": "Use CAUSES if A causes a specific disease that secondarily shortens lifespan. Use REDUCES_HEALTHSPAN if healthy function is impaired without total lifespan reduction. Use INHIBITS if A blocks a protective pathway without a direct lifespan measurement.",
    },
    RelationType.EXTENDS_HEALTHSPAN: {
        "definition": "Intervention, gene, or compound A significantly prolongs the healthy, disease-free, functionally capable period of organism B — improving physical or cognitive function without necessarily increasing maximum total lifespan.",
        "example": "Rapamycin extends healthspan in aged mice, improving memory retention and grip strength even when treatment begins at 20 months.",
        "not_this": "Use EXTENDS_LIFESPAN if total lifespan (not just healthy period) is explicitly measured and increased. Use TREATS if A addresses a specific disease rather than the ageing process. Use PREVENTS if A blocks onset of a specific condition.",
    },
    RelationType.REDUCES_HEALTHSPAN: {
        "definition": "Mutation, compound, or condition A shortens the healthy, functional period of organism B, accelerating age-related physical or cognitive decline without necessarily reducing total lifespan.",
        "example": "Telomerase deficiency reduces healthspan in mice, causing premature loss of tissue regenerative capacity and early onset of sarcopenia.",
        "not_this": "Use REDUCES_LIFESPAN if total lifespan is also shortened. Use CAUSES if A causes a specific named disease. Use INHIBITS if A blocks a protective pathway without a measured healthspan outcome.",
    },
    RelationType.REPROGRAMS: {
        "definition": "Factor, intervention, or treatment A resets or reverses the epigenetic state, gene expression landscape, or developmental identity of cell or tissue B toward a younger or more primitive state.",
        "example": "The Yamanaka factors (OSKM) reprogram aged somatic fibroblasts to induced pluripotent stem cells, resetting their epigenetic age clock to near-zero.",
        "not_this": "Use DEMETHYLATES or DEACETYLATES if a specific single-mark epigenetic modification is the finding. Use REGULATES if A modulates B's expression without resetting cellular identity. Use ACTIVATES if only one target pathway is turned on.",
    },

    # ── Category 12: Infection / Microbiology ─────────────────────────────────

    RelationType.INFECTS: {
        "definition": "Pathogen or microorganism A infects, colonises, or invades host organism or cell type B.",
        "example": "SARS-CoV-2 infects human lung epithelial cells via ACE2 receptor-mediated entry.",
        "not_this": "Use CAUSES if the focus is on the disease outcome rather than the infection event itself. Use BINDS_TO if the receptor binding rather than infection is the finding.",
    },

    # ── Category 13: Homology ──────────────────────────────────────────────────

    RelationType.ORTHOLOG_OF: {
        "definition": "Gene or protein A is the ortholog of gene/protein B in another species (diverged by speciation, not duplication); they share a common ancestor and typically retain the same function.",
        "example": "Human TP53 is ortholog_of mouse Trp53.",
        "not_this": "Use PARALOG_OF if the genes diverged within the same genome via duplication. Do not use for genes that merely share high sequence similarity without known evolutionary event.",
    },

    RelationType.PARALOG_OF: {
        "definition": "Gene or protein A is the paralog of gene/protein B in the same (or related) genome; they share a common ancestor but diverged by gene duplication.",
        "example": "Human BRCA1 is paralog_of BRCA2 (same genome, duplicated ancestor).",
        "not_this": "Use ORTHOLOG_OF if the genes are in different species and diverged by speciation. Do not use for genes with no documented duplication event.",
    },

    # ── Category 14: Ontology hierarchy ───────────────────────────────────────

    RelationType.SUBCLASS_OF: {
        "definition": "Entity A is a subclass/subtype of entity B (is-a relationship in an ontology hierarchy). Covers DO subclass_of, CL subclass_of, HPO subclass_of, GO is_a, etc.",
        "example": "Alzheimer's disease subclass_of neurodegenerative disease.",
        "not_this": "Use PART_OF if A is a physical component of B rather than a subtype. Do not use SUBCLASS_OF for functional or causal relationships.",
    },

    RelationType.HAS_PART: {
        "definition": "Entity A contains or comprises B as a physical or structural component (part-of inverse: A has_part B).",
        "example": "Nucleosome has_part histone H3.",
        "not_this": "Use PART_OF if the relation is expressed as 'B is part of A'. Use SUBCLASS_OF for type hierarchies. Use PARTICIPATES_IN for functional membership.",
    },

    # ── Category 15: Regulatory genomics ──────────────────────────────────────

    RelationType.REGULATES_EXPRESSION_OF: {
        "definition": "A non-coding regulatory element (enhancer, promoter, TFBS, miRNA, lncRNA) controls or modulates the transcriptional or post-transcriptional expression of gene B.",
        "example": "Enhancer element at chr17:7.5Mb regulates_expression_of TP53.",
        "not_this": "Use UPREGULATES or DOWNREGULATES when the direction is known and the mechanism is protein-mediated. Use TRANSCRIBES_TO for the DNA-to-RNA product relation. This type is for regulatory element → gene control specifically.",
    },

    RelationType.TARGETS: {
        "definition": "A transcription factor, regulatory protein, small RNA, or pharmacological compound targets a specific gene locus, promoter region, or molecular site for regulation or binding.",
        "example": "MYC targets E-box elements in the promoters of ribosome biogenesis genes.",
        "not_this": "Use BINDS_TO for physical binding without regulatory intent. Use INHIBITS/ACTIVATES when the downstream functional consequence is the finding. TARGETS implies a directed regulatory or therapeutic action.",
    },

    RelationType.OPEN_CHROMATIN_AT: {
        "definition": "A cell type, condition, or genomic element is characterised by open/accessible chromatin at a specific genomic region (ATAC-seq or DNase-seq accessibility).",
        "example": "T-helper cells show open_chromatin_at the IL2 promoter region upon activation.",
        "not_this": "Use EPIGENOMIC_FEATURE as an entity type for the chromatin feature itself. Use REGULATES_EXPRESSION_OF if the finding is about gene expression control, not chromatin accessibility. This type is for accessibility evidence specifically.",
    },

    # ── Category 16: Genomic overlap ──────────────────────────────────────────

    RelationType.OVERLAPS: {
        "definition": "Genomic feature A physically overlaps feature B by chromosomal coordinate (positional overlap, not causal). Covers gene/enhancer/promoter overlapping structural variants, TADs, or other features.",
        "example": "A 500 kb deletion overlaps the BRCA1 gene and an adjacent enhancer cluster.",
        "not_this": "Use LOCALIZES_TO for functional localization to a compartment. Use REGULATES_EXPRESSION_OF when the overlap has a regulatory consequence. OVERLAPS is purely coordinate-based with no implied function.",
    },

    # ── Category 17: Capability ────────────────────────────────────────────────

    RelationType.CAPABLE_OF: {
        "definition": "Entity A (cell type, organism, tissue) possesses the inherent ability or functional capacity to perform biological process B — not a single observed event but an established capability.",
        "example": "Macrophages are capable_of phagocytosis.",
        "not_this": "Use PARTICIPATES_IN if the entity is observed executing the process in a specific experiment. Use ACTIVATES/PROMOTES if A causes B to occur. CAPABLE_OF describes potential, not execution.",
    },

    # ── Category 18: GO/RO molecular function relations ───────────────────────

    RelationType.ENABLES: {
        "definition": "A gene product (protein/RNA) enables a specific molecular function or activity — the gene product is the executor of that function (GO:enables / RO:0002327).",
        "example": "ATM protein enables double-strand break repair activity.",
        "not_this": "Use PARTICIPATES_IN for broader process membership. Use ACTIVATES if A switches on B. ENABLES is specifically a GO molecular function annotation: gene product X enables MF Y.",
    },

    RelationType.ACTS_UPSTREAM_OF: {
        "definition": "Gene product A is causally upstream of biological process B — A's activity is required for or influences B, but A is not a direct participant in B (RO:0002263).",
        "example": "BRCA1 acts_upstream_of homologous recombination repair.",
        "not_this": "Use PARTICIPATES_IN if A directly takes part in process B. Use REGULATES if A modulates B's rate or extent. ACTS_UPSTREAM_OF is specifically a GO causal annotation where the gene product acts before the process begins.",
    },

    RelationType.CONTRIBUTES_TO: {
        "definition": "Gene, variant, or entity A partially contributes to disease or biological process B — A is a predisposing or partial causal factor, not the sole cause.",
        "example": "APOE ε4 variant contributes_to late-onset Alzheimer's disease risk.",
        "not_this": "Use CAUSES if A is the direct and sufficient cause of B. Use ASSOCIATES_WITH if the link is purely statistical with no established mechanism. CONTRIBUTES_TO implies partial/predisposing causality.",
    },

    RelationType.OCCURS_IN: {
        "definition": "A biological process, reaction, or event A occurs in anatomical entity or cell type B — specifies the spatial context where the process takes place.",
        "example": "Oxidative phosphorylation occurs_in the mitochondrial inner membrane.",
        "not_this": "Use LOCALIZES_TO for an entity (protein, molecule) being located in a compartment. Use EXPRESSED_IN for gene/protein expression context. OCCURS_IN is for processes/events, not entities.",
    },

    # ── Category 19: Developmental lineage ────────────────────────────────────

    RelationType.DEVELOPS_FROM: {
        "definition": "Cell type, tissue, or organism A develops from precursor entity B through a developmental process (RO:0002202 / Uberon developmental lineage).",
        "example": "Cardiomyocytes develop_from cardiac progenitor cells.",
        "not_this": "Use DERIVES_FROM if the relation is metabolic or product-based rather than developmental. Use SUBCLASS_OF for type hierarchy. DEVELOPS_FROM requires an actual developmental/differentiation event.",
    },

    RelationType.DERIVES_FROM: {
        "definition": "Entity A (metabolite, product, signal) is derived or produced from entity B through a chemical, metabolic, or processing event.",
        "example": "Cortisol derives_from cholesterol via the steroidogenic pathway.",
        "not_this": "Use DEVELOPS_FROM for cell/tissue developmental lineage. Use CONVERTS_TO for the forward direction (B converts to A). DERIVES_FROM is the inverse: A is the downstream product of B.",
    },

    # ── Category 20: Substrate / co-localisation ───────────────────────────────

    RelationType.HAS_SUBSTRATE: {
        "definition": "Enzyme, reaction, or molecular machine A has molecule B as its substrate — B is the molecule that A acts upon.",
        "example": "Hexokinase has_substrate glucose.",
        "not_this": "Use CATALYZES for the reaction event itself. Use BINDS_TO if the focus is physical binding without catalytic transformation. HAS_SUBSTRATE specifically identifies the substrate molecule.",
    },

    RelationType.COLOCALIZES_WITH: {
        "definition": "Two entities A and B are found in the same cellular compartment, tissue, or anatomical location — spatial co-occurrence without implying direct interaction.",
        "example": "RAD51 colocalizes_with BRCA2 in nuclear foci after DNA damage.",
        "not_this": "Use INTERACTS_WITH or BINDS_TO if direct molecular contact is established. Use LOCALIZES_TO if the focus is where one entity resides. COLOCALIZES_WITH is purely spatial co-occurrence of two entities.",
    },

    # ── Category 21: Clinical / pharmacological ────────────────────────────────

    RelationType.DIAGNOSES: {
        "definition": "Clinical test, biomarker, or procedure A diagnoses or is used to detect disease or condition B.",
        "example": "Elevated PSA level diagnoses prostate cancer.",
        "not_this": "Use BIOMARKER_FOR if A is a molecular marker associated with B without implying a diagnostic test. Use ASSOCIATES_WITH for statistical associations. DIAGNOSES implies clinical utility for disease detection.",
    },

    RelationType.CONTRAINDICATED_IN: {
        "definition": "Drug, treatment, or intervention A is contraindicated in disease, condition, or patient group B — A should not be used in the presence of B.",
        "example": "Metformin is contraindicated_in severe renal impairment.",
        "not_this": "Use TREATS for positive therapeutic use. Use CAUSES for adverse effects. CONTRAINDICATED_IN specifically means the drug is clinically unsafe or inappropriate in that condition.",
    },

    RelationType.IN_CLINICAL_TRIALS_FOR: {
        "definition": "Drug, intervention, or therapy A is currently under clinical investigation (Phase I–IV trials) for disease or condition B.",
        "example": "Senolytics are in_clinical_trials_for age-related frailty.",
        "not_this": "Use TREATS if clinical efficacy is already established. Use PREVENTS if the trial is prophylactic. IN_CLINICAL_TRIALS_FOR implies ongoing evaluation — not yet approved.",
    },

    # ── Category 22: Biolink completeness additions ───────────────────────────

    RelationType.TRANSCRIBED_FROM: {
        "definition": "Transcript A is produced by transcription from gene/DNA locus B (inverse of transcribes_to; biolink:transcribed_from / RO:0002511).",
        "example": "BRCA1 mRNA is transcribed_from the BRCA1 gene locus on chromosome 17.",
        "not_this": "Use TRANSCRIBES_TO if the subject is the gene/DNA and object is the transcript. TRANSCRIBED_FROM is the same fact written from the transcript's perspective.",
    },

    RelationType.TRANSLATION_OF: {
        "definition": "Protein A is the translation product of transcript B (inverse of translates_to; biolink:translation_of).",
        "example": "p53 protein is the translation_of TP53 mRNA.",
        "not_this": "Use TRANSLATES_TO if the subject is the mRNA/transcript and object is the protein. TRANSLATION_OF is the same fact from the protein's perspective.",
    },

    RelationType.IN_COMPLEX_WITH: {
        "definition": "Entity A and entity B are co-members of the same stable molecular complex — both are structural subunits of the same assembly.",
        "example": "EZH2 is in_complex_with SUZ12 and EED within the PRC2 complex.",
        "not_this": "Use INTERACTS_WITH for transient physical interactions. Use BINDS_TO for direct binding events. IN_COMPLEX_WITH requires stable co-complex membership, not just a transient encounter.",
    },

    RelationType.HAS_METABOLITE: {
        "definition": "Enzyme, reaction, or metabolic pathway A produces or has molecule B as a metabolite product or intermediate.",
        "example": "Glycolysis has_metabolite pyruvate.",
        "not_this": "Use HAS_SUBSTRATE for the input molecule. Use CATALYZES for the reaction event. HAS_METABOLITE identifies the output metabolite of a process.",
    },

    RelationType.GENETICALLY_INTERACTS_WITH: {
        "definition": "Gene A genetically interacts with gene B — double mutants show a phenotype that differs from what is expected from single mutants (epistasis, synthetic lethality, suppression).",
        "example": "BRCA1 genetically_interacts_with PARP1 — synthetic lethality exploited by PARP inhibitors.",
        "not_this": "Use INTERACTS_WITH for protein-level physical interaction. Use ASSOCIATES_WITH for statistical co-occurrence. GENETICALLY_INTERACTS_WITH requires evidence of a genetic interaction at the phenotypic level.",
    },

    RelationType.PHARMACOLOGICALLY_INTERACTS_WITH: {
        "definition": "Drug A pharmacologically interacts with drug B or molecular target B — altering absorption, distribution, metabolism, or pharmacodynamic effect.",
        "example": "Warfarin pharmacologically_interacts_with aspirin (increased bleeding risk).",
        "not_this": "Use BINDS_TO for the molecular binding event. Use TREATS for therapeutic use. PHARMACOLOGICALLY_INTERACTS_WITH covers drug–drug and drug–target pharmacokinetic/pharmacodynamic interactions.",
    },

    RelationType.PRECEDES: {
        "definition": "Event or process A temporally precedes event or process B — A occurs before B in a defined biological sequence or cascade.",
        "example": "DNA damage response precedes apoptosis induction.",
        "not_this": "Use CAUSES if A is the direct causal driver of B. Use ACTS_UPSTREAM_OF for causal upstream relationships. PRECEDES is purely temporal — it does not imply causation.",
    },

    RelationType.AMELIORATES: {
        "definition": "Gene, treatment, or intervention A ameliorates (mitigates or reduces severity of) disease or condition B without necessarily curing it — weaker than TREATS.",
        "example": "Metformin ameliorates insulin resistance in type 2 diabetes.",
        "not_this": "Use TREATS if the intervention provides established therapeutic benefit or cure. Use PREVENTS if A stops B from occurring. AMELIORATES implies partial improvement in existing condition.",
    },

    RelationType.EXACERBATES: {
        "definition": "Gene, compound, or condition A exacerbates (worsens or accelerates) disease or condition B.",
        "example": "High dietary fat intake exacerbates non-alcoholic fatty liver disease.",
        "not_this": "Use CAUSES if A is the initial cause of B. Use PROMOTES for broader positive regulatory effects. EXACERBATES specifically means A makes an already-existing condition B worse.",
    },

    RelationType.IN_TAXON: {
        "definition": "Biological entity A (gene, protein, cell type, process) is found in or belongs to organism taxon B.",
        "example": "FOXO3 gene is in_taxon Homo sapiens.",
        "not_this": "Use ORGANISM as an EntityType when the taxon is itself a node in the graph. IN_TAXON as a relation links a biological entity to its species context — useful for cross-species papers.",
    },

    # ── Category 23: Clinical outcome / risk (Biolink v4 formal definitions) ───

    RelationType.PREDISPOSES: {
        "definition": "A is a predisposing factor for B if A (e.g. a genetic variant, environmental exposure, physiological condition, or behavioral factor) increases the probability or risk of B occurring in an organism or population, without being a sufficient cause of B. Formally: biolink:predisposes / RO:0003302.",
        "example": "Obesity predisposes individuals to type 2 diabetes.",
        "not_this": "Use CAUSES if A is a direct and sufficient cause of B. Use CONTRIBUTES_TO if A is a partial causal factor with a mechanistic link. Use ASSOCIATES_WITH if the link is purely statistical with no established mechanistic or risk pathway.",
    },

    RelationType.MANIFESTATION_OF: {
        "definition": "Phenotypic feature, symptom, or clinical sign A is a manifestation of underlying disease or disorder B — A is characteristically expressed in the context of B. Formally: biolink:manifestation_of / RO:0002452 (inverse of has_manifestation).",
        "example": "Memory impairment is a manifestation_of Alzheimer's disease.",
        "not_this": "Use HAS_SYMPTOM / HAS_PHENOTYPE if the subject is the disease and the object is the clinical feature. MANIFESTATION_OF is written from the feature's perspective: feature manifestation_of disease.",
    },

    RelationType.ASSOCIATED_WITH_LIKELIHOOD_OF: {
        "definition": "There is statistical or probabilistic evidence that entity A is associated with an altered likelihood (increased or decreased probability) of condition or phenotype B occurring. More specific than ASSOCIATES_WITH — explicitly quantifies a probabilistic link rather than a generic co-occurrence. Formally: biolink:associated_with_likelihood_of.",
        "example": "BRCA1 pathogenic variant is associated_with_likelihood_of breast cancer.",
        "not_this": "Use PREDISPOSES if there is a known mechanistic or risk pathway. Use ASSOCIATES_WITH for generic statistical co-occurrence without a probabilistic framing. Use CAUSES for direct causal relationships.",
    },
}


# ── SECTION 5 — SYNONYM_MAP ───────────────────────────────────────────────────
# Moved to tools/build_taxonomy.py — used only by the offline schema audit tool.
# Not needed at runtime: the LLM normalises predicates directly from the
# closed taxonomy in the system prompt.
SYNONYM_MAP: Dict[str, RelationType] = {}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Cross-schema verification map (canonical → source schemas)
# None = that schema does not define this concept.
# ══════════════════════════════════════════════════════════════════════════════

CROSS_SCHEMA_MAP: Dict[RelationType, dict] = {
    RelationType.EXPRESSED_IN:     {"bionlp": "Gene_expression",           "hetionet": "AeG (Anatomy-expresses-Gene)",      "openbiolink": "GENE_ANATOMY expressed_in (GTEx)"},
    RelationType.TRANSCRIBES_TO:   {"bionlp": "Transcription",             "hetionet": None,                                "openbiolink": None},
    RelationType.TRANSLATES_TO:    {"bionlp": "Translation",               "hetionet": None,                                "openbiolink": None},
    RelationType.ACTIVATES:        {"bionlp": "Positive_regulation",       "hetionet": None,                                "openbiolink": None},
    RelationType.INHIBITS:         {"bionlp": "Negative_regulation",       "hetionet": None,                                "openbiolink": None},
    RelationType.UPREGULATES:      {"bionlp": "Positive_regulation",       "hetionet": "upregulates (AuG, CuG, DuG)",       "openbiolink": None},
    RelationType.DOWNREGULATES:    {"bionlp": "Negative_regulation",       "hetionet": "downregulates (AdG, CdG, DdG)",     "openbiolink": None},
    RelationType.REGULATES:        {"bionlp": "Regulation",                "hetionet": "GrG (Gene-regulates-Gene)",         "openbiolink": None},
    RelationType.PHOSPHORYLATES:   {"bionlp": "Phosphorylation (EPI)",     "hetionet": None,                                "openbiolink": None},
    RelationType.DEPHOSPHORYLATES: {"bionlp": "Dephosphorylation (EPI)",   "hetionet": None,                                "openbiolink": None},
    RelationType.METHYLATES:       {"bionlp": "Methylation / DNA_methylation (EPI)", "hetionet": None,                      "openbiolink": None},
    RelationType.ACETYLATES:       {"bionlp": "Acetylation (EPI)",         "hetionet": None,                                "openbiolink": None},
    RelationType.DEACETYLATES:     {"bionlp": "Deacetylation (EPI)",       "hetionet": None,                                "openbiolink": None},
    RelationType.UBIQUITINATES:    {"bionlp": "Ubiquitination (EPI)",      "hetionet": None,                                "openbiolink": None},
    RelationType.DEUBIQUITINATES:  {"bionlp": "Deubiquitination (EPI)",    "hetionet": None,                                "openbiolink": None},
    RelationType.SUMOYLATES:       {"bionlp": "Sumoylation (EPI)",         "hetionet": None,                                "openbiolink": None},
    RelationType.DESUMOYLATES:     {"bionlp": "Desumoylation (EPI)",       "hetionet": None,                                "openbiolink": None},
    RelationType.DEMETHYLATES:     {"bionlp": "DNA_demethylation / Demethylation (EPI)", "hetionet": None,                  "openbiolink": None},
    RelationType.HYDROXYLATES:     {"bionlp": "Hydroxylation (EPI)",       "hetionet": None,                                "openbiolink": None},
    RelationType.DEHYDROXYLATES:   {"bionlp": "Dehydroxylation (EPI)",     "hetionet": None,                                "openbiolink": None},
    RelationType.GLYCOSYLATES:     {"bionlp": "Glycosylation (EPI)",       "hetionet": None,                                "openbiolink": None},
    RelationType.DEGLYCOSYLATES:   {"bionlp": "Deglycosylation (EPI)",     "hetionet": None,                                "openbiolink": None},
    RelationType.NEDDYLATES:       {"bionlp": "Neddylation (EPI)",         "hetionet": None,                                "openbiolink": None},
    RelationType.DENEDDYLATES:     {"bionlp": "Deneddylation (EPI)",       "hetionet": None,                                "openbiolink": None},
    RelationType.BINDS_TO:         {"bionlp": "Binding",                   "hetionet": "CbG (Compound-binds-Gene)",         "openbiolink": None},
    RelationType.INTERACTS_WITH:   {"bionlp": None,                        "hetionet": "GiG (Gene-interacts-Gene)",         "openbiolink": "GENE_GENE interacts (StringDB/BioGRID)"},
    RelationType.IS_TARGET_OF:     {"bionlp": None,                        "hetionet": None,                                "openbiolink": "GENE_DRUG targeted_by"},
    RelationType.LOCALIZES_TO:     {"bionlp": "Localization",              "hetionet": "DlA (Disease-localizes-Anatomy)",   "openbiolink": None},
    RelationType.TRANSPORTS:       {"bionlp": "Transport",                 "hetionet": None,                                "openbiolink": None},
    RelationType.CONVERTS_TO:      {"bionlp": "Conversion",                "hetionet": None,                                "openbiolink": None},
    RelationType.CLEAVES:          {"bionlp": "Protein_processing (EPI)",  "hetionet": None,                                "openbiolink": None},
    RelationType.CATALYZES:        {"bionlp": None,                        "hetionet": None,                                "openbiolink": "GENE_CATALYSIS_GENE / DRUG_CATALYSIS_GENE"},
    RelationType.DEGRADES:         {"bionlp": "Protein_catabolism",        "hetionet": None,                                "openbiolink": None},
    RelationType.PARTICIPATES_IN:  {"bionlp": None,                        "hetionet": "GpPW / GpBP / GpCC / GpMF",        "openbiolink": "participates_in (GO annotations)"},
    RelationType.PART_OF:          {"bionlp": None,                        "hetionet": None,                                "openbiolink": "ANATOMY_ANATOMY part_of"},
    RelationType.IS_MEMBER_OF:     {"bionlp": None,                        "hetionet": "PCiC (Pharmacologic Class-includes-Compound)", "openbiolink": None},
    RelationType.CAUSES:           {"bionlp": None,                        "hetionet": "CcSE (Compound-causes-SideEffect)", "openbiolink": "causes"},
    RelationType.PROMOTES:         {"bionlp": "Positive_regulation",       "hetionet": None,                                "openbiolink": None},
    RelationType.PREVENTS:         {"bionlp": "Negative_regulation",       "hetionet": None,                                "openbiolink": None},
    RelationType.TREATS:           {"bionlp": None,                        "hetionet": "CtD (Compound-treats-Disease)",     "openbiolink": "indicated_for"},
    RelationType.PALLIATES:        {"bionlp": None,                        "hetionet": "CpD (Compound-palliates-Disease)",  "openbiolink": None},
    RelationType.BIOMARKER_FOR:    {"bionlp": None,                        "hetionet": None,                                "openbiolink": "biomarker_for"},
    RelationType.ASSOCIATES_WITH:  {"bionlp": None,                        "hetionet": "DaG (Disease-associates-Gene)",     "openbiolink": "associated_with (DisGeNET/OMIM)"},
    RelationType.CORRELATES_WITH:  {"bionlp": None,                        "hetionet": "GcG (Gene-covaries-Gene)",          "openbiolink": None},
    RelationType.COEXPRESSED_WITH: {"bionlp": None,                        "hetionet": "GcG (Gene-covaries-Gene, partial)", "openbiolink": "coexpressed with (Bgee/GTEx)"},
    RelationType.IS_VARIANT_OF:    {"bionlp": None,                        "hetionet": None,                                "openbiolink": "is sequence variant of (ClinVar/OMIM)"},
    RelationType.RESEMBLES:        {"bionlp": None,                        "hetionet": "DrD / CrC (resembles)",             "openbiolink": None},
    RelationType.PREDICTS:         {"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.HAS_SYMPTOM:      {"bionlp": None,                        "hetionet": "DpS (Disease-presents-Symptom)",    "openbiolink": "DISEASE_PHENOTYPE presents_with"},
    RelationType.HAS_PHENOTYPE:    {"bionlp": None,                        "hetionet": None,                                "openbiolink": "GENE_PHENOTYPE phenotypically_associated_with (HPO)"},
    RelationType.SECRETES:          {"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.EXTENDS_LIFESPAN:  {"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.REDUCES_LIFESPAN:  {"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.EXTENDS_HEALTHSPAN:{"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.REDUCES_HEALTHSPAN:{"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.REPROGRAMS:        {"bionlp": None,                        "hetionet": None,                                "openbiolink": None},
    RelationType.INFECTS:           {"bionlp": "Infection (ID task)",        "hetionet": None,                                "openbiolink": None},
    # BioCypher-specific additions
    RelationType.ORTHOLOG_OF:               {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "orthology_association (DIOPT)"},
    RelationType.PARALOG_OF:                {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "paralogy_association"},
    RelationType.SUBCLASS_OF:               {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "do_subclass_of / cl_subclass_of / hpo_subclass_of / go_is_a"},
    RelationType.HAS_PART:                  {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "has_part (GO/OBO)"},
    RelationType.REGULATES_EXPRESSION_OF:   {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "regulatory_association (ENCODE/FANTOM)"},
    RelationType.TARGETS:                   {"bionlp": None, "hetionet": "CbG (partial)", "openbiolink": None, "biocypher": "tf_binding_association (ENCODE ChIP-seq)"},
    RelationType.OPEN_CHROMATIN_AT:         {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "open_chromatin_region_association (ATAC-seq/DNase-seq)"},
    RelationType.OVERLAPS:                  {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "feature_overlaps_structural_variant / gene_overlaps_structural_variant"},
    RelationType.CAPABLE_OF:               {"bionlp": None, "hetionet": None, "openbiolink": None, "biocypher": "cl_capable_of (CL ontology)"},
    # Biolink model additions (Categories 18–21)
    RelationType.ENABLES:                  {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:enables (RO:0002327)"},
    RelationType.ACTS_UPSTREAM_OF:         {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:acts_upstream_of (RO:0002263)"},
    RelationType.CONTRIBUTES_TO:           {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:contributes_to"},
    RelationType.OCCURS_IN:                {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:occurs_in (RO:0001025)"},
    RelationType.DEVELOPS_FROM:            {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:develops_from (RO:0002202)"},
    RelationType.DERIVES_FROM:             {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:derives_from"},
    RelationType.HAS_SUBSTRATE:            {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:has_substrate"},
    RelationType.COLOCALIZES_WITH:         {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:colocalizes_with"},
    RelationType.DIAGNOSES:                {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:diagnoses"},
    RelationType.CONTRAINDICATED_IN:       {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:contraindicated_in"},
    RelationType.IN_CLINICAL_TRIALS_FOR:   {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:in_clinical_trials_for"},
    # Category 22: Biolink completeness
    RelationType.TRANSCRIBED_FROM:                {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:transcribed_from (RO:0002511)", "biocypher": "transcribed from"},
    RelationType.TRANSLATION_OF:                  {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:translation_of", "biocypher": "translation of"},
    RelationType.IN_COMPLEX_WITH:                 {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:in_complex_with"},
    RelationType.HAS_METABOLITE:                  {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:has_metabolite"},
    RelationType.GENETICALLY_INTERACTS_WITH:      {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:genetically_interacts_with"},
    RelationType.PHARMACOLOGICALLY_INTERACTS_WITH:{"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:pharmacologically_interacts_with"},
    RelationType.PRECEDES:                        {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:precedes (RO:0002566)"},
    RelationType.AMELIORATES:                     {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:ameliorates_condition"},
    RelationType.EXACERBATES:                     {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:exacerbates_condition"},
    RelationType.IN_TAXON:                        {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:in_taxon (RO:0002162)"},
    # Category 23: Clinical outcome / risk (Biolink v4)
    RelationType.PREDISPOSES:                     {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:predisposes (RO:0003302)"},
    RelationType.MANIFESTATION_OF:                {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:manifestation_of (RO:0002452)"},
    RelationType.ASSOCIATED_WITH_LIKELIHOOD_OF:   {"bionlp": None, "hetionet": None, "openbiolink": None, "biolink": "biolink:associated_with_likelihood_of"},
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — BioCypher / biolink predicate mapping (used by Layer 7)
# ══════════════════════════════════════════════════════════════════════════════

BIOLINK_MAPPING: Dict[RelationType, str] = {
    RelationType.EXPRESSED_IN:     "biolink:expressed_in",
    RelationType.TRANSCRIBES_TO:   "biolink:transcribed_to",
    RelationType.TRANSLATES_TO:    "biolink:translates_to",
    RelationType.ACTIVATES:        "biolink:positively_regulates",
    RelationType.INHIBITS:         "biolink:negatively_regulates",
    RelationType.UPREGULATES:      "biolink:positively_regulates",
    RelationType.DOWNREGULATES:    "biolink:negatively_regulates",
    RelationType.REGULATES:        "biolink:regulates",
    RelationType.PHOSPHORYLATES:   "biolink:affects",
    RelationType.DEPHOSPHORYLATES: "biolink:affects",
    RelationType.METHYLATES:       "biolink:affects",
    RelationType.ACETYLATES:       "biolink:affects",
    RelationType.DEACETYLATES:     "biolink:affects",
    RelationType.UBIQUITINATES:    "biolink:affects",
    RelationType.DEUBIQUITINATES:  "biolink:affects",
    RelationType.SUMOYLATES:       "biolink:affects",
    RelationType.DESUMOYLATES:     "biolink:affects",
    RelationType.DEMETHYLATES:     "biolink:affects",
    RelationType.HYDROXYLATES:     "biolink:affects",
    RelationType.DEHYDROXYLATES:   "biolink:affects",
    RelationType.GLYCOSYLATES:     "biolink:affects",
    RelationType.DEGLYCOSYLATES:   "biolink:affects",
    RelationType.NEDDYLATES:       "biolink:affects",
    RelationType.DENEDDYLATES:     "biolink:affects",
    RelationType.CLEAVES:          "biolink:affects",
    RelationType.CATALYZES:        "biolink:catalyzes",
    RelationType.COEXPRESSED_WITH: "biolink:coexpressed_with",
    RelationType.IS_VARIANT_OF:    "biolink:is_sequence_variant_of",
    RelationType.BINDS_TO:         "biolink:interacts_with",
    RelationType.INTERACTS_WITH:   "biolink:interacts_with",
    RelationType.IS_TARGET_OF:     "biolink:is_target_of",
    RelationType.LOCALIZES_TO:     "biolink:located_in",
    RelationType.TRANSPORTS:       "biolink:affects",
    RelationType.CONVERTS_TO:      "biolink:produces",
    RelationType.DEGRADES:         "biolink:affects",
    RelationType.PARTICIPATES_IN:  "biolink:participates_in",
    RelationType.PART_OF:          "biolink:part_of",
    RelationType.IS_MEMBER_OF:     "biolink:member_of",
    RelationType.CAUSES:           "biolink:causes",
    RelationType.PROMOTES:         "biolink:positively_regulates",
    RelationType.PREVENTS:         "biolink:negatively_regulates",
    RelationType.TREATS:           "biolink:treats",
    RelationType.PALLIATES:        "biolink:treats",
    RelationType.BIOMARKER_FOR:    "biolink:biomarker_for",
    RelationType.ASSOCIATES_WITH:  "biolink:associated_with",
    RelationType.CORRELATES_WITH:  "biolink:correlated_with",
    RelationType.RESEMBLES:        "biolink:similar_to",
    RelationType.PREDICTS:         "biolink:associated_with",
    RelationType.HAS_SYMPTOM:      "biolink:has_phenotype",
    RelationType.HAS_PHENOTYPE:    "biolink:has_phenotype",
    RelationType.SECRETES:          "biolink:produces",
    RelationType.EXTENDS_LIFESPAN:  "biolink:related_to",
    RelationType.REDUCES_LIFESPAN:  "biolink:related_to",
    RelationType.EXTENDS_HEALTHSPAN:"biolink:related_to",
    RelationType.REDUCES_HEALTHSPAN:"biolink:related_to",
    RelationType.REPROGRAMS:        "biolink:affects",
    RelationType.INFECTS:                 "biolink:causes",
    # BioCypher-specific additions
    RelationType.ORTHOLOG_OF:             "biolink:orthologous_to",
    RelationType.PARALOG_OF:              "biolink:paralogous_to",
    RelationType.SUBCLASS_OF:             "biolink:subclass_of",
    RelationType.HAS_PART:                "biolink:has_part",
    RelationType.REGULATES_EXPRESSION_OF: "biolink:regulates_expression_of",
    RelationType.TARGETS:                 "biolink:affects",
    RelationType.OPEN_CHROMATIN_AT:       "biolink:related_to",
    RelationType.OVERLAPS:                "biolink:overlaps",
    RelationType.CAPABLE_OF:             "biolink:capable_of",
    # Biolink model additions (Categories 18–21)
    RelationType.ENABLES:                "biolink:enables",
    RelationType.ACTS_UPSTREAM_OF:       "biolink:acts_upstream_of",
    RelationType.CONTRIBUTES_TO:         "biolink:contributes_to",
    RelationType.OCCURS_IN:              "biolink:occurs_in",
    RelationType.DEVELOPS_FROM:          "biolink:develops_from",
    RelationType.DERIVES_FROM:           "biolink:derives_from",
    RelationType.HAS_SUBSTRATE:          "biolink:has_substrate",
    RelationType.COLOCALIZES_WITH:       "biolink:colocalizes_with",
    RelationType.DIAGNOSES:              "biolink:diagnoses",
    RelationType.CONTRAINDICATED_IN:     "biolink:contraindicated_in",
    RelationType.IN_CLINICAL_TRIALS_FOR:            "biolink:in_clinical_trials_for",
    # Category 22
    RelationType.TRANSCRIBED_FROM:                  "biolink:transcribed_from",
    RelationType.TRANSLATION_OF:                    "biolink:translation_of",
    RelationType.IN_COMPLEX_WITH:                   "biolink:in_complex_with",
    RelationType.HAS_METABOLITE:                    "biolink:has_metabolite",
    RelationType.GENETICALLY_INTERACTS_WITH:        "biolink:genetically_interacts_with",
    RelationType.PHARMACOLOGICALLY_INTERACTS_WITH:  "biolink:pharmacologically_interacts_with",
    RelationType.PRECEDES:                          "biolink:precedes",
    RelationType.AMELIORATES:                       "biolink:ameliorates_condition",
    RelationType.EXACERBATES:                       "biolink:exacerbates_condition",
    RelationType.IN_TAXON:                          "biolink:in_taxon",
    RelationType.PREDISPOSES:                       "biolink:predisposes",
    RelationType.MANIFESTATION_OF:                  "biolink:manifestation_of",
    RelationType.ASSOCIATED_WITH_LIKELIHOOD_OF:     "biolink:associated_with_likelihood_of",
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Contradiction pairs (used by Layer 7 detection)
# If paper A says X inhibits Y and paper B says X activates Y,
# both are flagged for human review — neither is silently dropped.
# ══════════════════════════════════════════════════════════════════════════════

OPPOSING_RELATIONS: Dict[RelationType, RelationType] = {
    RelationType.ACTIVATES:        RelationType.INHIBITS,
    RelationType.INHIBITS:         RelationType.ACTIVATES,
    RelationType.UPREGULATES:      RelationType.DOWNREGULATES,
    RelationType.DOWNREGULATES:    RelationType.UPREGULATES,
    RelationType.PROMOTES:         RelationType.PREVENTS,
    RelationType.PREVENTS:         RelationType.PROMOTES,
    RelationType.PHOSPHORYLATES:   RelationType.DEPHOSPHORYLATES,
    RelationType.DEPHOSPHORYLATES: RelationType.PHOSPHORYLATES,
    RelationType.METHYLATES:       RelationType.DEMETHYLATES,
    RelationType.DEMETHYLATES:     RelationType.METHYLATES,
    RelationType.ACETYLATES:       RelationType.DEACETYLATES,
    RelationType.DEACETYLATES:     RelationType.ACETYLATES,
    RelationType.UBIQUITINATES:    RelationType.DEUBIQUITINATES,
    RelationType.DEUBIQUITINATES:  RelationType.UBIQUITINATES,
    RelationType.SUMOYLATES:       RelationType.DESUMOYLATES,
    RelationType.DESUMOYLATES:     RelationType.SUMOYLATES,
    RelationType.HYDROXYLATES:     RelationType.DEHYDROXYLATES,
    RelationType.DEHYDROXYLATES:   RelationType.HYDROXYLATES,
    RelationType.GLYCOSYLATES:     RelationType.DEGLYCOSYLATES,
    RelationType.DEGLYCOSYLATES:   RelationType.GLYCOSYLATES,
    RelationType.NEDDYLATES:       RelationType.DENEDDYLATES,
    RelationType.DENEDDYLATES:     RelationType.NEDDYLATES,
    RelationType.EXTENDS_LIFESPAN:  RelationType.REDUCES_LIFESPAN,
    RelationType.REDUCES_LIFESPAN:  RelationType.EXTENDS_LIFESPAN,
    RelationType.EXTENDS_HEALTHSPAN:RelationType.REDUCES_HEALTHSPAN,
    RelationType.REDUCES_HEALTHSPAN:RelationType.EXTENDS_HEALTHSPAN,
    RelationType.TREATS:           RelationType.CAUSES,
    RelationType.CAUSES:           RelationType.TREATS,
}
