# Scoring Policy: Mathematical Framework

## 1. Problem Statement

Given a knowledge graph $G = (V, E)$ encoding pharmacological, genomic, and clinical relationships, the scoring policy assigns a confidence value $s \in [0, 1]$ to every claim and a composite score to every mechanistic path through the graph.

The goal: rank candidate drug-adverse event explanations by the strength of their underlying evidence, penalizing speculative chains while rewarding independent corroboration.

---

## 2. Graph Formalism

### 2.1 Entities and Claims

Let the entity node types be:

$$\mathcal{N} = \{D, G, P, \Delta, A\}$$

where $D$ = Drug, $G$ = Gene/Protein, $P$ = Pathway, $\Delta$ = Disease, $A$ = Adverse Event.

Every relationship in the graph is mediated by a **Claim** node $c \in C$. A claim is an assertion linking a source entity to a target entity:

$$c = (\text{type}, \sigma_c, \pi_c, d_c)$$

where:
- $\text{type} \in \{\texttt{DRUG$_$TARGET}, \texttt{GENE\_DISEASE}, \texttt{GENE\_PATHWAY}, \texttt{DRUG\_AE\_LABEL}, \ldots\}$
- $\sigma_c \in [0, 1]$ is the **strength score** (computed at ETL time)
- $\pi_c \in \{-1, 0, +1\}$ is the **polarity** (inhibitory, unknown, activating)
- $d_c$ is the **source dataset** identifier

Each claim $c$ is connected to one or more **Evidence** nodes $e \in \mathcal{E}$ via $\texttt{SupportedBy}$ edges, providing full provenance.

### 2.2 Mechanistic Path

A mechanistic path $\rho$ from drug $d$ to adverse event $a$ is a sequence:

$$\rho = (n_0, c_1, n_1, c_2, n_2, \ldots, c_k, n_k)$$

where $n_0 = d \in D$, $n_k = a \in A$, each $n_i \in V$, and each $c_i \in C$ is a claim connecting $n_{i-1}$ to $n_i$. The **hop count** is $k = |\rho| - 1$.

---

## 3. Claim-Level Scoring (ETL Time)

Each data source computes $\sigma_c$ from its native confidence metric. All scores are normalized to $[0, 1]$.

### 3.1 Binding Affinity Sources

For ChEMBL and GtoPdb, confidence derives from **target binding potency**. The stronger a drug binds its molecular target, the more likely it is to elicit downstream biological effects.

**ChEMBL** uses pChEMBL, a normalized $-\log_{10}$ of activity values (IC$_{50}$, K$_i$, K$_d$, EC$_{50}$) in molar units:

$$\sigma_{\text{ChEMBL}}(c) = \text{clamp}\!\left(\frac{\text{pChEMBL} - 4}{6},\ 0,\ 1\right)$$

| pChEMBL | Molar Activity | Interpretation | $\sigma$ |
|---------|---------------|----------------|----------|
| 5 | $10\ \mu M$ | Weak binder, may not reach effect at therapeutic dose | 0.17 |
| 7 | $100\ nM$ | Moderate, typical drug-like potency | 0.50 |
| 9 | $1\ nM$ | Very potent, high occupancy at low concentration | 0.83 |
| 10 | $100\ pM$ | Extremely potent | 1.00 |

*Biological basis:* A drug with $K_i = 100\ nM$ for its target occupies $\sim$50% of receptors at $100\ nM$ concentration (assuming simple competitive binding). Higher potency means the drug-target interaction dominates at therapeutic plasma levels, making the downstream pathway perturbation more certain.

**GtoPdb** uses the same logarithmic affinity scale (pK$_i$, pIC$_{50}$, pK$_d$, pEC$_{50}$):

$$\sigma_{\text{GtoPdb}}(c) = \text{clamp}\!\left(\frac{\text{affinity\_median}}{10},\ 0,\ 1\right)$$

| pK$_i$ | Interpretation | $\sigma$ |
|---------|----------------|----------|
| 5 | Moderate affinity | 0.50 |
| 8 | High affinity (10 nM) | 0.80 |
| 10 | Ultra-high affinity | 1.00 |

### 3.2 Open Targets Gene-Disease Score

Open Targets pre-integrates evidence across multiple data types into a single score $s_{\text{OT}} \in [0, 1]$:

$$\sigma_{\text{OT}}(c) = s_{\text{OT}}$$

Their score aggregates:
- **Genetic associations** (GWAS, rare disease genetics)
- **Somatic mutations** (cancer genomics)
- **Known drugs** (approved indications)
- **Literature mining** (text co-occurrence)
- **Animal models** (phenotype data)
- **Pathways/systems biology** (pathway enrichment)

*Biological basis:* A gene-disease association with $s_{\text{OT}} = 0.9$ means multiple independent evidence streams converge -- e.g., GWAS variants near the gene are associated with the disease, the gene's protein product is a known drug target for the disease, and animal knockouts recapitulate the phenotype. A score of $0.1$ might rest on text-mining co-occurrence alone.

### 3.3 FAERS Disproportionality Signal

The FDA Adverse Event Reporting System yields statistical signals via the **Proportional Reporting Ratio**:

$$\text{PRR} = \frac{a / (a + b)}{c / (c + d)}$$

where for a given drug-AE pair in a $2 \times 2$ table: $a$ = reports of this drug with this AE, $b$ = reports of this drug with other AEs, $c$ = reports of other drugs with this AE, $d$ = reports of other drugs with other AEs.

The strength score normalizes via log scale:

$$\sigma_{\text{FAERS}}(c) = \text{clamp}\!\left(\frac{\log_{10}(\text{PRR})}{2},\ 0,\ 1\right)$$

| PRR | Interpretation | $\sigma$ |
|-----|----------------|----------|
| 1.0 | Background rate, no signal | 0.00 |
| 3.2 | Mild disproportionality | 0.25 |
| 10 | Strong signal ($10\times$ overreporting) | 0.50 |
| 100 | Very strong signal | 1.00 |

*Biological basis:* PRR measures whether a drug-AE combination appears in spontaneous reports more than expected by chance. However, FAERS data is subject to **reporting bias** (newly approved drugs are over-reported), **confounding by indication** (the disease itself causes the AE), and **notoriety bias** (media attention inflates reports). The log transform compresses the heavy-tailed PRR distribution, and the low maximum weight ($w_{\text{FAERS}} = 0.5$, see Section 4) reflects these known limitations.

### 3.4 SIDER Label Frequency

SIDER extracts adverse event frequencies from structured drug labels. The score is the **mean of reported frequency bounds**:

$$\sigma_{\text{SIDER}}(c) = \frac{f_{\text{lower}} + f_{\text{upper}}}{2}$$

where $f_{\text{lower}}$ and $f_{\text{upper}}$ are the lower and upper frequency bounds from the label (e.g., "1-10%" becomes $f_{\text{lower}} = 0.01$, $f_{\text{upper}} = 0.10$, $\sigma = 0.055$).

*Biological basis:* Label frequencies are derived from controlled clinical trials (phase II/III). A side effect observed in 30% of trial participants represents a strong, reproducible pharmacological effect. One observed in 0.01% may be coincidental or idiosyncratic. The frequency directly approximates the conditional probability $P(\text{AE} \mid \text{Drug})$ from trial data.

### 3.5 STRING Protein-Protein Interaction

STRING provides a combined confidence score integrating experimental data, text mining, co-expression, and genomic context on an integer scale $[0, 999]$:

$$\sigma_{\text{STRING}}(c) = \frac{s_{\text{combined}}}{1000}$$

| STRING score | Channel | $\sigma$ |
|-------------|---------|----------|
| $\geq 900$ | Highest confidence (experimental + multiple channels) | $\geq 0.9$ |
| 700-899 | High confidence | 0.7-0.9 |
| 400-699 | Medium (may include text-mining only) | 0.4-0.7 |

*Biological basis:* Protein-protein interactions (PPIs) indicate that two gene products physically or functionally interact. If Drug $d$ targets Gene $g_1$ and $g_1$ has a high-confidence PPI with $g_2$, the pharmacological perturbation of $g_1$ may propagate to $g_2$'s function. Lower STRING scores (text-mining-heavy) represent weaker evidence for actual molecular interaction.

### 3.6 ClinGen Gene-Disease Validity

ClinGen expert panels assign discrete validity classifications. The mapping to $\sigma$ is ordinal:

$$\sigma_{\text{ClinGen}}(c) = \begin{cases}
1.0 & \text{Definitive} \\
0.9 & \text{Strong} \\
0.7 & \text{Moderate} \\
0.5 & \text{Limited} \\
0.3 & \text{Disputed} \\
0.1 & \text{Refuted} \\
0.0 & \text{No Known Relationship}
\end{cases}$$

*Biological basis:* "Definitive" means the gene-disease relationship is supported by multiple lines of genetic evidence (segregation in families, functional studies, replication). "Limited" means early-stage evidence exists but replication or functional validation is lacking. These classifications are from expert panels who weigh genetic, experimental, and clinical data according to the ClinGen Clinical Validity Framework.

### 3.7 CTD Literature-Curated Associations

The Comparative Toxicogenomics Database scores are based on **evidence volume** (PubMed citation count $n_{\text{PMID}}$) and **evidence type**.

**Drug-Gene interactions:**

$$\sigma_{\text{CTD}}^{DG}(c) = \min\!\left(0.5 + 0.1 \cdot n_{\text{PMID}},\ 1.0\right)$$

Base of 0.5 (already literature-curated), +0.1 per supporting publication, capped at 1.0.

**Gene-Disease associations:**

$$\sigma_{\text{CTD}}^{G\Delta}(c) = \min\!\left(\beta + 0.05 \cdot n_{\text{PMID}},\ 1.0\right), \quad \beta = \begin{cases} 0.8 & \text{direct evidence} \\ 0.5 & \text{inferred} \end{cases}$$

*Biological basis:* Direct evidence means a curator found explicit statements linking the gene to the disease in the literature. Inferred associations are transitively derived (chemical affects gene, chemical affects disease, therefore gene may relate to disease). More publications increase confidence through independent replication.

**Drug-Disease associations:**

$$\sigma_{\text{CTD}}^{D\Delta}(c) = \begin{cases} 0.9 & \text{therapeutic relationship} \\ 0.7 & \text{marker/mechanistic relationship} \end{cases}$$

*Biological basis:* A therapeutic relationship means the drug is used to treat the disease (strong, clinically validated link). A marker relationship means the drug biomarker is associated with the disease (mechanistically informative but not a proven intervention).

### 3.8 openFDA Drug Labels

Scored by the **severity level** of the label section containing safety information:

$$\sigma_{\text{openFDA}}(c) = \begin{cases}
0.9 & \text{boxed warning present} \\
0.7 & \text{adverse reactions section present} \\
0.5 & \text{other label content only}
\end{cases}$$

*Biological basis:* FDA boxed warnings ("black box") represent the most serious known risks -- they are reserved for adverse events that are life-threatening or have been clearly established in post-marketing surveillance. The adverse reactions section documents events observed in clinical trials. A label with neither likely describes a drug with minimal documented safety signals.

### 3.9 HPO Gene-Phenotype

HPO (Human Phenotype Ontology) associations are loaded with $\sigma = \text{NULL}$, as the source does not provide a native confidence metric. These are curated associations between genes and clinical phenotypes.

When used in scoring, NULL strength scores default to 0.5 (see Section 5.1).

---

## 4. Source Reliability Weights

Each dataset $d$ carries a **source weight** $w_d \in [0, 1]$ reflecting the overall trustworthiness of that data source:

$$\mathbf{w} = \begin{pmatrix} w_{\text{drugcentral}} \\ w_{\text{opentargets}} \\ w_{\text{chembl}} \\ w_{\text{reactome}} \\ w_{\text{gtop}} \\ w_{\text{clingen}} \\ w_{\text{sider}} \\ w_{\text{hpo}} \\ w_{\text{ctd}} \\ w_{\text{string}} \\ w_{\text{faers}} \\ w_{\text{openfda}} \end{pmatrix} = \begin{pmatrix} 1.00 \\ 0.95 \\ 0.90 \\ 0.90 \\ 0.85 \\ 0.85 \\ 0.80 \\ 0.70 \\ 0.70 \\ 0.60 \\ 0.50 \\ 0.50 \end{pmatrix}$$

These encode an **evidence hierarchy** rooted in pharmacological practice:

### Tier 1: Expert-Curated Pharmacology ($w \geq 0.9$)

- **DrugCentral (1.0):** Regulatory-grade approved drug-target annotations reviewed by pharmacologists. Mechanism-of-action data from FDA/EMA/PMDA labels.
- **Open Targets (0.95):** Multi-evidence integration platform aggregating genetics, clinical, and functional genomics data with systematic scoring.
- **ChEMBL (0.9):** Experimental bioactivity data from medicinal chemistry literature. High-quality but includes assay-level variability.
- **Reactome (0.9):** Expert-curated pathway maps with literature-backed enzyme-substrate and protein-complex relationships.

### Tier 2: Curated Associations ($w = 0.7\text{--}0.85$)

- **GtoPdb (0.85):** IUPHAR expert-curated pharmacological targets; smaller coverage but high quality.
- **ClinGen (0.85):** Gene-disease validity from expert panels using a standardized curation framework.
- **SIDER (0.8):** Label-derived drug-AE pairs. Reliable (from controlled trials) but data is from an older snapshot.
- **HPO (0.7):** Gene-phenotype associations from clinical literature; variable curation depth.
- **CTD (0.7):** Literature-curated chemical-gene-disease interactions; depends on publication quality.

### Tier 3: Statistical/Computational ($w \leq 0.6$)

- **STRING (0.6):** Includes text-mining-derived interactions alongside experimental data; mixed precision.
- **FAERS (0.5):** Spontaneous reports with known biases (reporting, confounding by indication, notoriety, Weber effect).
- **openFDA (0.5):** Structured label data; provides regulatory context but not primary evidence.

---

## 5. Path-Level Scoring (Query Time)

### 5.1 Composite Path Score

Given a mechanistic path $\rho = (n_0, c_1, n_1, \ldots, c_k, n_k)$ with $k$ hops, the scoring policy computes:

$$S(\rho) = \underbrace{\sigma_{\text{base}}}_{\text{claim strength}} \times \underbrace{\lambda^{k}}_{\text{length penalty}} \times \underbrace{\mu(\rho)}_{\text{multi-source bonus}}$$

where:

$$\sigma_{\text{base}} = \sigma_{c^*}, \quad c^* = \text{primary claim on the path}$$

If $\sigma_{c^*}$ is NULL, the default is $\sigma_{\text{base}} = 0.5$.

$$\lambda = 0.95 \quad \text{(length penalty per hop)}$$

$$\mu(\rho) = \begin{cases} 1.2 & \text{if } |\mathcal{E}(\rho)| > 1 \\ 1.0 & \text{otherwise} \end{cases}$$

where $|\mathcal{E}(\rho)|$ is the number of independent evidence nodes supporting claims on $\rho$.

### 5.2 Length Penalty Rationale

The factor $\lambda^k$ models the compounding of inferential uncertainty across hops:

| Hops $k$ | $\lambda^k$ | Path Type | Example |
|-----------|-------------|-----------|---------|
| 1 | 0.950 | Direct | Drug $\to$ AE (label-listed) |
| 2 | 0.903 | One inference | Drug $\to$ Gene $\to$ Disease |
| 3 | 0.857 | Two inferences | Drug $\to$ Gene $\to$ Pathway $\to$ AE |
| 4 | 0.815 | Three inferences | Drug $\to$ Gene $\to$ Pathway $\to$ Disease $\to$ AE |

*Biological rationale:* Each hop introduces an inferential step. "Drug inhibits HMGCR" is well-established; "HMGCR is in the mevalonate pathway" is curated; "mevalonate pathway disruption affects CoQ10 synthesis" is mechanistically plausible; "CoQ10 depletion causes myopathy" is supported but less direct. The penalty of $\lambda = 0.95$ is intentionally **mild**: we favor mechanistic depth because a 3-hop explanation backed by curated data is clinically more informative than a 1-hop FAERS signal (which would score $0.5 \times 0.95 = 0.475$ on its own).

### 5.3 Multi-Source Bonus Rationale

The factor $\mu = 1.2$ implements the **independent corroboration principle** from evidence-based medicine. If DrugCentral asserts Drug $\to$ Gene and ChEMBL independently confirms it with binding data, the combined confidence exceeds either source alone.

Formally, if two independent sources each have error probability $\varepsilon$, the probability both are wrong is $\varepsilon^2$. The 1.2x multiplier is a conservative approximation of this effect -- not a Bayesian posterior, but a pragmatic reward for convergent evidence.

### 5.4 Intended Full Formula

The docstring specifies the intended (not yet fully implemented) formula:

$$S_{\text{full}}(\rho) = \sigma_{\text{base}} \times \bar{w}(\rho) \times \lambda^k \times \mu(\rho)$$

where $\bar{w}(\rho)$ is the **average source weight** across all claims on the path:

$$\bar{w}(\rho) = \frac{1}{k} \sum_{i=1}^{k} w_{d_{c_i}}$$

This would ensure that a path through FAERS ($w = 0.5$) is penalized relative to one through DrugCentral ($w = 1.0$) even if both have the same $\sigma_{\text{base}}$.

---

## 6. Context-Sensitive Boosting

### 6.1 Patient Condition Relevance

When the user provides a set of patient conditions $\mathcal{K} \subseteq \Delta$, paths traversing a matching disease node receive a **relevance boost**:

$$S_{\text{contextualized}}(\rho) = S(\rho) \times \prod_{i} \beta_i$$

where:

$$\beta_i = \begin{cases}
1.5 & \text{if } n_i \in \mathcal{K} \text{ and } n_i \in \Delta \\
1.0 & \text{otherwise}
\end{cases}$$

*Clinical rationale:* A patient with diabetes taking a drug whose mechanism perturbs glucose metabolism pathways faces a compounded risk. The boost does not increase confidence in the data -- it increases **clinical relevance** for this specific patient.

### 6.2 Edge-Type Weights in Subgraph Scoring

When rendering a subgraph for visualization, edges receive type-based weights:

$$w_{\text{edge}} = \alpha_{\text{type}} \times w_{\text{existing}}$$

where:

$$\alpha_{\text{type}} = \begin{cases}
1.0 & \texttt{TARGETS} & \text{(drug-target, experimentally validated)} \\
0.9 & \texttt{IN\_PATHWAY} & \text{(curated pathway membership)} \\
0.8 & \texttt{ASSOCIATED\_WITH} & \text{(gene-disease, often statistical)} \\
0.7 & \texttt{CAUSES} & \text{(drug-AE, observational)} \\
0.5 & \text{other} & \text{(default)}
\end{cases}$$

*Biological rationale:* Drug-target binding ($\alpha = 1.0$) is the most experimentally grounded edge type -- measured in vitro with specific assays. Pathway membership ($\alpha = 0.9$) is expert-curated from functional studies. Gene-disease associations ($\alpha = 0.8$) often derive from GWAS, which identifies statistical associations that may not reflect direct causation. Drug-AE edges ($\alpha = 0.7$) from labels or FAERS are clinical observations without explicit mechanism.

---

## 7. Worked Example: Statin Myopathy

Consider the query: "Why might atorvastatin cause myopathy in a patient with type 2 diabetes?"

### Path A: Direct label evidence
$$\rho_A: \text{Atorvastatin} \xrightarrow{\texttt{CAUSES}} \text{Myopathy}$$

- $\sigma_{\text{base}} = 0.055$ (SIDER frequency $\approx$ 5.5%)
- $k = 1$, $\lambda^1 = 0.95$
- $\mu = 1.0$ (single source)

$$S(\rho_A) = 0.055 \times 0.95 \times 1.0 = 0.052$$

### Path B: Mechanistic via HMGCR
$$\rho_B: \text{Atorvastatin} \xrightarrow{\texttt{TARGETS}} \text{HMGCR} \xrightarrow{\texttt{IN\_PATHWAY}} \text{Cholesterol Biosynthesis}$$

- $\sigma_{\text{base}} = 0.8$ (DrugCentral curated target)
- $k = 2$, $\lambda^2 = 0.9025$
- $\mu = 1.2$ (DrugCentral + Reactome = two evidence sources)

$$S(\rho_B) = 0.8 \times 0.9025 \times 1.2 = 0.866$$

### Path C: Mechanistic via disease context
$$\rho_C: \text{Atorvastatin} \xrightarrow{\texttt{TARGETS}} \text{HMGCR} \xrightarrow{\texttt{ASSOCIATED\_WITH}} \text{Type 2 Diabetes}$$

- $\sigma_{\text{base}} = 0.65$ (Open Targets gene-disease score for HMGCR-T2D)
- $k = 2$, $\lambda^2 = 0.9025$
- $\mu = 1.0$ (single source chain)
- $\beta = 1.5$ (patient has T2D, so condition relevance boost applies)

$$S(\rho_C) = 0.65 \times 0.9025 \times 1.0 \times 1.5 = 0.880$$

### Ranking

| Rank | Path | Score | Interpretation |
|------|------|-------|----------------|
| 1 | $\rho_C$ | 0.880 | Mechanistic + patient-relevant: HMGCR perturbation in diabetic context |
| 2 | $\rho_B$ | 0.866 | Mechanistic: curated target + pathway, multi-source corroboration |
| 3 | $\rho_A$ | 0.052 | Direct but low-frequency label observation |

The system surfaces the mechanistic explanations over the bare label frequency, and the patient's diabetes context pushes $\rho_C$ above the purely mechanistic $\rho_B$.

---

## 8. Summary of All Claim-Level Score Formulas

| Source | Claim Type | Formula | Domain Basis |
|--------|-----------|---------|--------------|
| ChEMBL | `DRUG_TARGET` | $\text{clamp}\!\left(\frac{\text{pChEMBL} - 4}{6},\ 0,\ 1\right)$ | Binding potency (K$_i$, IC$_{50}$) |
| GtoPdb | `DRUG_TARGET` | $\text{clamp}\!\left(\frac{\text{pAffinity}}{10},\ 0,\ 1\right)$ | Pharmacological affinity (pK$_i$, pIC$_{50}$) |
| Open Targets | `GENE_DISEASE` | $s_{\text{OT}}$ (pass-through) | Multi-evidence integration |
| FAERS | `DRUG_AE_FAERS` | $\text{clamp}\!\left(\frac{\log_{10}(\text{PRR})}{2},\ 0,\ 1\right)$ | Disproportionality signal |
| SIDER | `DRUG_AE_LABEL` | $\frac{f_{\text{lower}} + f_{\text{upper}}}{2}$ | Clinical trial frequency |
| STRING | `GENE_GENE` | $\frac{s_{\text{combined}}}{1000}$ | PPI confidence (experimental + computational) |
| ClinGen | `GENE_DISEASE` | Ordinal lookup (Definitive=1.0 $\to$ Refuted=0.1) | Expert panel classification |
| CTD (drug-gene) | `DRUG_GENE` | $\min(0.5 + 0.1 \cdot n_{\text{PMID}},\ 1.0)$ | Literature citation volume |
| CTD (gene-disease) | `GENE_DISEASE` | $\min(\beta + 0.05 \cdot n_{\text{PMID}},\ 1.0)$; $\beta \in \{0.5, 0.8\}$ | Direct vs inferred evidence |
| CTD (drug-disease) | `DRUG_DISEASE` | $0.9$ (therapeutic) or $0.7$ (marker) | Relationship type |
| openFDA | `DRUG_LABEL` | $0.9$ / $0.7$ / $0.5$ | Label section severity |
| HPO | `GENE_PHENOTYPE` | NULL (defaults to $0.5$) | No native confidence metric |
