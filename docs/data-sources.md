# Data Sources Reference

Complete documentation of all ETL data sources for the Drug-AE Knowledge Graph.

## Goal

Build a pharmacovigilance knowledge graph that traces mechanistic pathways:

```
Drug -> Gene/Protein -> Pathway -> Disease -> Adverse Event
```

This enables evidence-based reasoning about why a drug might cause an adverse event, backed by curated biological data rather than statistical correlation alone.

## Dependency Chain

```
Tier 1: Foundational (no dependencies)
  hgnc         Gene nomenclature - canonical symbols and IDs
  drugcentral  Drug structures and targets - establishes Drug and Gene nodes

Tier 2: Extensions (depend on Tier 1)
  opentargets  Gene-disease associations
  reactome     Biological pathways
  gtop         Pharmacological targets with affinity data

Tier 3: Associations (depend on Tier 1-2)
  sider        Drug-ADR pairs from labels
  openfda      Drug labels with safety sections
  ctd          Chemical-gene-disease from toxicogenomics
  string       Protein-protein interactions
  clingen      Curated gene-disease validity
  hpo          Phenotype-disease associations

Tier 4: Advanced (depend on Tier 1-3)
  chembl       Bioactivity data with binding affinities
  faers        Adverse event signal detection from reports
```

## Normalization Strategy

| Entity | Canonical ID | Fallback IDs |
|--------|--------------|--------------|
| Gene | HGNC ID | Ensembl, UniProt, NCBI Gene, Symbol |
| Drug | Internal key | DrugCentral ID, PubChem CID, ChEMBL ID, InChIKey |
| Disease | MONDO ID | DOID, EFO, OMIM, MESH |
| Pathway | Reactome ID | WikiPathways ID |
| Adverse Event | Internal key | MedDRA PT, UMLS CUI |

Cross-references stored in `xrefs_json` columns for each entity.

## Database Setup

```bash
# Create database (SQL Server 2025)
sqlcmd -S localhost -U sa -P "password1$" -Q "CREATE DATABASE kg_ae"

# Deploy schema
uv run python -m kg_ae.cli init-db
```

## Running ETL

```bash
# Interactive dashboard (recommended)
uv run python -m kg_ae.cli etl

# Batch mode
uv run python -m kg_ae.cli etl --batch

# Specific dataset with dependencies
uv run python -m kg_ae.cli etl --dataset sider

# Specific tier
uv run python -m kg_ae.cli etl --tier 1
```

---

## 1. HGNC (HUGO Gene Nomenclature Committee)

### Purpose

Establishes canonical gene identifiers. All other gene-referencing datasets resolve to HGNC symbols/IDs for consistent joins.

### Source

| Field | Value |
|-------|-------|
| URL | `https://storage.googleapis.com/public-download-files/hgnc/json/json/hgnc_complete_set.json` |
| License | CC0 1.0 |
| Format | JSON |

### Data Extracted

| Field | Description |
|-------|-------------|
| `hgnc_id` | Canonical identifier (HGNC:12345) |
| `symbol` | Official gene symbol |
| `name` | Full gene name |
| `ensembl_gene_id` | Ensembl ID for genomic data |
| `uniprot_ids` | UniProt accession (first if multiple) |
| `entrez_id` | NCBI Gene ID |
| `alias_symbol` | Alternative symbols (JSON array) |
| `prev_symbol` | Historical symbols (JSON array) |
| `locus_type`, `locus_group` | Gene classification |

### Filtering

- Only `status = "Approved"` genes loaded
- ~43,000 approved human genes

### Graph Impact

Updates `kg.Gene` with canonical nomenclature. Builds synonym index for fuzzy matching.

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.hgnc import HGNCDownloader; HGNCDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.hgnc import HGNCParser; HGNCParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.hgnc import HGNCLoader; HGNCLoader().load()"
```

---

## 2. DrugCentral

### Purpose

Primary source for drug entities and drug-target interactions. Establishes the Drug->Gene edges with mechanism of action data.

### Source

| Field | Value |
|-------|-------|
| URL | `https://unmtid-dbs.net/download/DrugCentral/` |
| License | CC BY-SA 4.0 |
| Format | TSV |

### Files

| File | Content |
|------|---------|
| `drug.target.interaction.tsv.gz` | Drug-target interactions with action types |
| `structures.smiles.tsv` | Drug structures with SMILES, InChIKey |
| `FDA+EMA+PMDA_Approved.csv` | Approved drug list |

### Data Extracted

**Drugs:**
| Field | Description |
|-------|-------------|
| `preferred_name` | Drug name (INN) |
| `drugcentral_id` | DrugCentral structure ID |
| `cas_rn` | CAS Registry Number |
| `inchikey` | Standard InChIKey |
| `smiles` | Canonical SMILES |

**Targets:**
| Field | Description |
|-------|-------------|
| `symbol` | Gene symbol |
| `uniprot_id` | UniProt accession |
| `target_name` | Protein name |
| `target_class` | Target classification |

**Interactions:**
| Field | Description |
|-------|-------------|
| `action_type` | INHIBITOR, AGONIST, ANTAGONIST, etc. |
| `act_value` | Activity value (Ki, IC50) |
| `moa` | Mechanism of action text |

### Filtering

- Targets filtered to `organism = "Homo sapiens"`
- Multi-value fields (gene symbols) split and deduplicated

### Graph Impact

- `kg.Drug`: ~5,500 approved drugs
- `kg.Gene`: ~2,000 target genes
- `kg.Claim` (DRUG_TARGET): Drug-target edges with action type

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.drugcentral import DrugCentralDownloader; DrugCentralDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.drugcentral import DrugCentralParser; DrugCentralParser().parse()"

# Normalize
uv run python -c "from kg_ae.datasets.drugcentral import DrugCentralNormalizer; DrugCentralNormalizer().normalize()"

# Load
uv run python -c "from kg_ae.datasets.drugcentral import DrugCentralLoader; DrugCentralLoader().load()"
```

---

## 3. Open Targets Platform

### Purpose

High-quality gene-disease associations from integrated evidence. Provides the Gene->Disease edges with confidence scores.

### Source

| Field | Value |
|-------|-------|
| URL | `https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/25.03/output/` |
| License | CC0 |
| Format | Partitioned Parquet |

### Files

| Directory | Content |
|-----------|---------|
| `association_overall_direct/` | Gene-disease association scores |
| `disease/` | Disease metadata with ontology mappings |
| `target/` | Target (gene) metadata |

### Data Extracted

**Associations:**
| Field | Description |
|-------|-------------|
| `targetId` | Ensembl gene ID |
| `diseaseId` | EFO disease ID |
| `score` | Overall association score (0-1) |

**Diseases:**
| Field | Description |
|-------|-------------|
| `id` | EFO ID |
| `name` | Disease name |
| `description` | Disease description |
| `dbXRefs` | Cross-references (MONDO, DOID, OMIM) |

### Filtering

- Associations filtered to `score > 0.1` (high confidence)
- Reduces ~12M associations to ~500K

### Graph Impact

- `kg.Disease`: ~28,000 diseases with ontology mappings
- `kg.Claim` (GENE_DISEASE): Gene-disease edges with scores

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.opentargets import OpenTargetsDownloader; OpenTargetsDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.opentargets import OpenTargetsParser; OpenTargetsParser().parse()"

# Normalize
uv run python -c "from kg_ae.datasets.opentargets import OpenTargetsNormalizer; OpenTargetsNormalizer().normalize()"

# Load
uv run python -c "from kg_ae.datasets.opentargets import OpenTargetsLoader; OpenTargetsLoader().load()"
```

---

## 4. Reactome

### Purpose

Curated biological pathways. Provides Gene->Pathway edges showing which genes participate in which biological processes.

### Source

| Field | Value |
|-------|-------|
| URL | `https://reactome.org/download/current/` |
| License | CC BY 4.0 |
| Format | TSV |

### Files

| File | Content |
|------|---------|
| `ReactomePathways.txt` | Pathway names and species |
| `ReactomePathwaysRelation.txt` | Pathway hierarchy |
| `UniProt2Reactome.txt` | UniProt to pathway mapping |
| `Ensembl2Reactome.txt` | Ensembl to pathway mapping |

### Data Extracted

**Pathways:**
| Field | Description |
|-------|-------------|
| `reactome_id` | Reactome stable ID (R-HSA-12345) |
| `pathway_name` | Pathway name |

**Gene-Pathway:**
| Field | Description |
|-------|-------------|
| `uniprot_id` | UniProt accession |
| `reactome_id` | Pathway ID |
| `evidence_code` | Evidence type (TAS, IEA) |

### Filtering

- Filtered to `species = "Homo sapiens"`
- Deduplicated by (gene, pathway) pairs

### Graph Impact

- `kg.Pathway`: ~2,800 human pathways
- `kg.Claim` (GENE_PATHWAY): Gene-pathway membership edges

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.reactome import ReactomeDownloader; ReactomeDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.reactome import ReactomeParser; ReactomeParser().parse()"

# Normalize
uv run python -c "from kg_ae.datasets.reactome import ReactomeNormalizer; ReactomeNormalizer().normalize()"

# Load
uv run python -c "from kg_ae.datasets.reactome import ReactomeLoader; ReactomeLoader().load()"
```

---

## 5. GtoPdb (Guide to PHARMACOLOGY)

### Purpose

Expert-curated pharmacological targets with quantitative affinity data. Complements DrugCentral with high-quality binding constants.

### Source

| Field | Value |
|-------|-------|
| URL | `https://www.guidetopharmacology.org/DATA/` |
| License | CC BY-SA 4.0 |
| Format | TSV |

### Files

| File | Content |
|------|---------|
| `interactions.tsv` | Ligand-target interactions with affinity |
| `ligands.tsv` | Ligand (drug) metadata |
| `targets_and_families.tsv` | Target metadata |
| `GtP_to_HGNC_mapping.csv` | HGNC symbol mapping |

### Data Extracted

**Interactions:**
| Field | Description |
|-------|-------------|
| `ligand_id` | GtoPdb ligand ID |
| `target_id` | GtoPdb target ID |
| `action` | Action type (agonist, antagonist, etc.) |
| `affinity_median` | Median affinity value (pKi, pIC50) |
| `affinity_units` | Units (pKi, pIC50, pKd) |

### Filtering

- Interactions filtered to `target_species = "Human"`
- Ligands filtered to approved drugs or synthetic organics

### Graph Impact

- Updates `kg.Drug` with GtoPdb ligand IDs
- `kg.Claim` (DRUG_TARGET_GTOPDB): Drug-target edges with affinity

### Future Additions

- Selectivity data across target families
- Endogenous ligand information

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.gtop import GtoPdbDownloader; GtoPdbDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.gtop import GtoPdbParser; GtoPdbParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.gtop import GtoPdbLoader; GtoPdbLoader().load()"
```

---

## 6. SIDER (Side Effect Resource)

### Purpose

Drug-adverse event pairs extracted from drug labels. Primary source for Drug->AdverseEvent edges with frequency data.

### Source

| Field | Value |
|-------|-------|
| URL | `http://sideeffects.embl.de/media/download/` |
| License | CC BY-NC-SA 4.0 (non-commercial) |
| Format | TSV.gz |

### Files

| File | Content |
|------|---------|
| `meddra_all_se.tsv.gz` | All drug-side effect pairs |
| `drug_names.tsv` | STITCH ID to drug name mapping |
| `meddra_freq.tsv.gz` | Side effect frequencies |

### Data Extracted

**Drug-AE pairs:**
| Field | Description |
|-------|-------------|
| `stitch_id` | STITCH compound ID |
| `umls_cui` | UMLS concept ID for AE |
| `side_effect_name` | MedDRA preferred term |
| `meddra_type` | PT (preferred term) or LLT |
| `frequency` | Frequency category or percentage |

### Transformations

- STITCH ID converted to PubChem CID: `pubchem_cid = stitch_numeric - 100000000`
- MedDRA hierarchy: Only PT (Preferred Term) level used
- Frequency score computed from frequency ranges

### Graph Impact

- `kg.Drug`: ~1,400 drugs (matched to existing or created)
- `kg.AdverseEvent`: ~5,800 unique AE terms
- `kg.Claim` (DRUG_AE_LABEL): ~140,000 drug-AE associations
- `kg.Evidence` (CURATED_DB): Provenance records

### Licensing Note

SIDER is non-commercial. Downstream use must respect CC BY-NC-SA.

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.sider import SiderDownloader; SiderDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.sider import SiderParser; SiderParser().parse()"

# Normalize
uv run python -c "from kg_ae.datasets.sider import SiderNormalizer; SiderNormalizer().normalize()"

# Load
uv run python -c "from kg_ae.datasets.sider import SiderLoader; SiderLoader().load()"
```

---

## 7. openFDA Labels

### Purpose

FDA drug labels with structured safety information. Provides evidence for drug-AE relationships from official labeling.

### Source

| Field | Value |
|-------|-------|
| URL | `https://api.fda.gov/download.json` (manifest) |
| License | Public Domain (CC0) |
| Format | Nested ZIP/JSON |

### Files

| File | Content |
|------|---------|
| `drug-label-*.json.zip` | Drug label JSON partitions |

### Data Extracted

| Field | Description |
|-------|-------------|
| `set_id` | Label set ID (unique per drug) |
| `brand_name` | Brand name(s) |
| `generic_name` | Generic name(s) |
| `effective_time` | Label version date |
| `rxcui` | RxNorm CUI |
| `unii` | FDA UNII codes |
| `adverse_reactions` | AE section text |
| `warnings` | Warnings section text |
| `boxed_warning` | Black box warning text |
| `contraindications` | Contraindication text |

### Transformations

- Extracts from nested ZIP files
- Deduplicates by `set_id` (keeps most recent)
- Text sections truncated to 10KB
- Creates evidence records with safety text

### Graph Impact

- `kg.Evidence`: Label evidence with safety sections
- `kg.Claim` (DRUG_LABEL): Drug to label claims

### Future Additions

- NLP extraction of specific AE terms from text
- Structured product labeling (SPL) parsing

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.openfda import OpenFDADownloader; OpenFDADownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.openfda import OpenFDAParser; OpenFDAParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.openfda import OpenFDALoader; OpenFDALoader().load()"
```

---

## 8. CTD (Comparative Toxicogenomics Database)

### Purpose

Curated chemical-gene-disease interactions from literature. Provides additional Drug->Disease and Gene->Disease edges with publication evidence.

### Source

| Field | Value |
|-------|-------|
| URL | `https://ctdbase.org/reports/` |
| License | Open Access (non-commercial research) |
| Format | TSV.gz |

### Files

| File | Content |
|------|---------|
| `CTD_chem_gene_ixns.tsv.gz` | Chemical-gene interactions |
| `CTD_chemicals_diseases.tsv.gz` | Chemical-disease associations |
| `CTD_genes_diseases.tsv.gz` | Gene-disease associations |
| `CTD_chemicals.tsv.gz` | Chemical vocabulary |

### Data Extracted

**Chemical-Gene:**
| Field | Description |
|-------|-------------|
| `chemical_name` | Chemical name |
| `gene_symbol` | Gene symbol |
| `interaction` | Interaction description |
| `interaction_actions` | increases/decreases expression, etc. |
| `pubmed_ids` | Supporting publications |

**Gene-Disease:**
| Field | Description |
|-------|-------------|
| `gene_symbol` | Gene symbol |
| `disease_name` | Disease name |
| `disease_id` | MESH or OMIM ID |
| `direct_evidence` | marker/mechanism |
| `pubmed_ids` | Supporting publications |

### Filtering

- Chemical-gene: `organism_id = 9606` (human only)
- Gene/chemical-disease: `direct_evidence IS NOT NULL` (curated only)
- Excludes inferred associations

### Graph Impact

- `kg.Disease`: New diseases with MESH/OMIM IDs
- `kg.Claim` (GENE_DISEASE_CTD, DRUG_DISEASE_CTD): Curated associations

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.ctd import CTDDownloader; CTDDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.ctd import CTDParser; CTDParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.ctd import CTDLoader; CTDLoader().load()"
```

---

## 9. STRING

### Purpose

Protein-protein interaction network. Provides Gene<->Gene edges showing functional associations.

### Source

| Field | Value |
|-------|-------|
| URL | `https://stringdb-downloads.org/download/` (v12.0, taxon 9606) |
| License | CC BY 4.0 |
| Format | TSV.gz |

### Files

| File | Content |
|------|---------|
| `9606.protein.links.v12.0.txt.gz` | Protein interactions with scores |
| `9606.protein.aliases.v12.0.txt.gz` | STRING ID to gene symbol mapping |
| `9606.protein.info.v12.0.txt.gz` | Protein annotations |

### Data Extracted

| Field | Description |
|-------|-------------|
| `protein1`, `protein2` | STRING protein IDs |
| `combined_score` | Interaction confidence (0-1000) |

**Aliases for mapping:**
| Field | Description |
|-------|-------------|
| `string_id` | STRING protein ID |
| `alias` | Gene symbol or other ID |
| `source` | Alias source (BioMart_HUGO preferred) |

### Filtering

- `combined_score >= 700` (high confidence)
- Self-interactions removed
- Deduplicated (A-B = B-A)

### Graph Impact

- `kg.Claim` (GENE_GENE_STRING): ~400,000 protein interactions

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.string import STRINGDownloader; STRINGDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.string import STRINGParser; STRINGParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.string import STRINGLoader; STRINGLoader().load()"
```

---

## 10. ClinGen

### Purpose

Expert-curated gene-disease validity assessments. High-confidence Gene->Disease edges with classification levels.

### Source

| Field | Value |
|-------|-------|
| URL | `https://search.clinicalgenome.org/kb/gene-validity/download` |
| License | CC BY 4.0 |
| Format | TSV (or CSV/JSON fallback) |

### Data Extracted

| Field | Description |
|-------|-------------|
| `gene_symbol` | HGNC gene symbol |
| `hgnc_id` | HGNC ID |
| `disease_label` | Disease name |
| `mondo_id` | MONDO disease ID |
| `classification` | Validity classification |
| `inheritance` | Mode of inheritance |

### Classification Scores

| Classification | Score |
|---------------|-------|
| Definitive | 1.0 |
| Strong | 0.9 |
| Moderate | 0.7 |
| Limited | 0.5 |
| Disputed | 0.3 |
| Refuted | 0.1 |

### Graph Impact

- `kg.Claim` (GENE_DISEASE_CLINGEN): ~3,000 curated gene-disease assertions

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.clingen import ClinGenDownloader; ClinGenDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.clingen import ClinGenParser; ClinGenParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.clingen import ClinGenLoader; ClinGenLoader().load()"
```

---

## 11. HPO (Human Phenotype Ontology)

### Purpose

Phenotype-disease and gene-phenotype associations. Links genes to clinical manifestations.

### Source

| Field | Value |
|-------|-------|
| URL | `http://purl.obolibrary.org/obo/hp/hpoa/` |
| License | HPO License |
| Format | TSV |

### Files

| File | Content |
|------|---------|
| `genes_to_phenotype.txt` | Gene-phenotype associations |
| `phenotype_to_genes.txt` | Phenotype-gene associations |
| `phenotype.hpoa` | Disease-phenotype annotations |

### Data Extracted

| Field | Description |
|-------|-------------|
| `ncbi_gene_id` | NCBI Gene ID |
| `gene_symbol` | Gene symbol |
| `hpo_id` | HPO term ID (HP:0000001) |
| `hpo_name` | Phenotype name |
| `disease_id` | OMIM or ORPHA disease ID |

### Filtering

- Disease-phenotype: OMIM and ORPHA diseases only
- Gene-phenotype: Valid NCBI gene IDs only

### Graph Impact

- `kg.Claim` (GENE_PHENOTYPE_HPO): Gene-phenotype associations

### Future Additions

- Phenotype-disease edges
- HPO term hierarchy

### Commands

```bash
# Download
uv run python -c "from kg_ae.datasets.hpo import HPODownloader; HPODownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.hpo import HPOParser; HPOParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.hpo import HPOLoader; HPOLoader().load()"
```

---

## 12. ChEMBL

### Purpose

Bioactivity data with quantitative binding affinities. Provides Drug->Gene edges with pChEMBL values for potency ranking.

### Source

| Field | Value |
|-------|-------|
| URL | `https://www.ebi.ac.uk/chembl/api/data/` (REST API) |
| License | CC BY-SA 3.0 |
| Format | JSON (paginated API) |

### API Query Parameters

```
standard_type__in=IC50,Ki,Kd,EC50
pchembl_value__isnull=false
target_type=SINGLE PROTEIN
target_organism=Homo sapiens
```

### Data Extracted

| Field | Description |
|-------|-------------|
| `molecule_chembl_id` | ChEMBL compound ID |
| `molecule_pref_name` | Compound name |
| `target_chembl_id` | ChEMBL target ID |
| `target_pref_name` | Target name |
| `standard_type` | Activity type (IC50, Ki, Kd, EC50) |
| `pchembl_value` | -log10(activity) normalized value |

### Transformations

- Aggregates by molecule-target pair
- Takes best (max) pchembl value
- Normalizes to 0-1: `score = (pchembl - 4) / 6`

### Filtering

- `target_organism = "Homo sapiens"`
- `pchembl_value IS NOT NULL`
- `target_type = "SINGLE PROTEIN"`

### Graph Impact

- `kg.Claim` (DRUG_TARGET_CHEMBL): Drug-target edges with binding affinity

### Commands

```bash
# Download (uses API, takes ~30 min)
uv run python -c "from kg_ae.datasets.chembl import ChEMBLDownloader; ChEMBLDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.chembl import ChEMBLParser; ChEMBLParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.chembl import ChEMBLLoader; ChEMBLLoader().load()"
```

---

## 13. FAERS (FDA Adverse Event Reporting System)

### Purpose

Statistical signal detection from spontaneous adverse event reports. Provides Drug->AE edges with disproportionality scores.

### Source

| Field | Value |
|-------|-------|
| URL | `https://api.fda.gov/download.json` (manifest) |
| License | Public Domain |
| Format | ZIP/JSON partitions |

### Data Extracted

From each report:
| Field | Description |
|-------|-------------|
| `patient.drug[].medicinalproduct` | Drug names in report |
| `patient.reaction[].reactionmeddrapt` | Reactions in report |

### Signal Detection

Computes disproportionality metrics for each drug-AE pair:

| Metric | Formula |
|--------|---------|
| PRR | (a/a+b) / (c/c+d) |
| ROR | (a*d) / (b*c) |
| Chi-square | For statistical significance |

Where:
- a = reports with drug AND AE
- b = reports with drug, without AE
- c = reports without drug, with AE
- d = reports without drug or AE

### Filtering

Signals must meet ALL criteria:
- `PRR > 1.0`
- `chi_square > 3.84` (p < 0.05)
- `count >= 3`

### Score Normalization

```
strength_score = min(log2(PRR) / 5, 1.0)
```

### Graph Impact

- `kg.Claim` (DRUG_AE_FAERS): Drug-AE signals with PRR/ROR/chi2

### Commands

```bash
# Download (configurable partitions, large download)
uv run python -c "from kg_ae.datasets.faers import FAERSDownloader; FAERSDownloader().download()"

# Parse
uv run python -c "from kg_ae.datasets.faers import FAERSParser; FAERSParser().parse()"

# Load
uv run python -c "from kg_ae.datasets.faers import FAERSLoader; FAERSLoader().load()"
```

---

## Summary Table

| Dataset | License | Entities | Claim Type | Edges |
|---------|---------|----------|------------|-------|
| HGNC | CC0 | Gene | - | - |
| DrugCentral | CC BY-SA 4.0 | Drug, Gene | DRUG_TARGET | ~15K |
| Open Targets | CC0 | Disease | GENE_DISEASE | ~500K |
| Reactome | CC BY 4.0 | Pathway | GENE_PATHWAY | ~100K |
| GtoPdb | CC BY-SA 4.0 | - | DRUG_TARGET_GTOPDB | ~10K |
| SIDER | CC BY-NC-SA 4.0 | Drug, AE | DRUG_AE_LABEL | ~140K |
| openFDA | CC0 | Evidence | DRUG_LABEL | ~100K |
| CTD | Non-commercial | Disease | DRUG/GENE_DISEASE_CTD | ~200K |
| STRING | CC BY 4.0 | - | GENE_GENE_STRING | ~400K |
| ClinGen | CC BY 4.0 | - | GENE_DISEASE_CLINGEN | ~3K |
| HPO | HPO License | - | GENE_PHENOTYPE_HPO | ~150K |
| ChEMBL | CC BY-SA 3.0 | - | DRUG_TARGET_CHEMBL | ~200K |
| FAERS | Public Domain | - | DRUG_AE_FAERS | ~50K |

**Total Claims**: ~1.8M edges across all sources
