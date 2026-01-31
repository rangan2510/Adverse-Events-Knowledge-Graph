/* ============================================================
   Knowledge Graph schema (SQL Server 2025): NODE/EDGE + Evidence
   - Pattern: Entity nodes + Claim/Evidence nodes for provenance
   - JSON stored as NVARCHAR(MAX) with ISJSON checks
   - Optional embeddings stored as VECTOR(n)
   ============================================================ */

-- 0) Schema
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'kg')
    EXEC(N'CREATE SCHEMA kg AUTHORIZATION dbo;');
GO

-- 1) Drop in dependency order (edges -> nodes -> relational)
DROP TABLE IF EXISTS kg.SupportedBy;
DROP TABLE IF EXISTS kg.ClaimAdverseEvent;
DROP TABLE IF EXISTS kg.ClaimPathway;
DROP TABLE IF EXISTS kg.ClaimDisease;
DROP TABLE IF EXISTS kg.ClaimGene;
DROP TABLE IF EXISTS kg.HasClaim;
GO

DROP TABLE IF EXISTS kg.Evidence;
DROP TABLE IF EXISTS kg.Claim;
DROP TABLE IF EXISTS kg.AdverseEvent;
DROP TABLE IF EXISTS kg.Pathway;
DROP TABLE IF EXISTS kg.Disease;
DROP TABLE IF EXISTS kg.Gene;
DROP TABLE IF EXISTS kg.Drug;
GO

DROP TABLE IF EXISTS kg.Dataset;
DROP TABLE IF EXISTS kg.IngestRun;
GO

/* ============================================================
   2) Relational metadata tables (dataset registry + ingest runs)
   ============================================================ */

CREATE TABLE kg.Dataset
(
    dataset_id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Dataset PRIMARY KEY,
    dataset_key          NVARCHAR(64)       NOT NULL,  -- e.g., 'drugcentral', 'chembl', 'openfda_faers'
    dataset_name         NVARCHAR(200)      NOT NULL,
    dataset_version      NVARCHAR(64)       NULL,      -- release tag/date
    -- Computed column for unique constraint (handles NULL version)
    version_key AS (ISNULL(dataset_version, N'')) PERSISTED,
    released_at          DATE               NULL,
    license_name         NVARCHAR(200)      NULL,
    source_url           NVARCHAR(2048)     NULL,
    sha256               CHAR(64)           NULL,
    meta_json            NVARCHAR(MAX)      NULL
        CONSTRAINT CK_Dataset_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)       NOT NULL CONSTRAINT DF_Dataset_CreatedAt DEFAULT SYSUTCDATETIME()
);

CREATE UNIQUE INDEX UX_Dataset_KeyVer
ON kg.Dataset(dataset_key, version_key);
GO

CREATE TABLE kg.IngestRun
(
    ingest_run_id        BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_IngestRun PRIMARY KEY,
    dataset_id           INT                  NOT NULL CONSTRAINT FK_IngestRun_Dataset
        FOREIGN KEY REFERENCES kg.Dataset(dataset_id),
    started_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_IngestRun_StartedAt DEFAULT SYSUTCDATETIME(),
    finished_at          DATETIME2(3)         NULL,
    status               NVARCHAR(32)         NOT NULL,     -- 'running'|'success'|'failed'
    row_count            BIGINT               NULL,
    notes_json           NVARCHAR(MAX)        NULL
        CONSTRAINT CK_IngestRun_NotesJson CHECK (notes_json IS NULL OR ISJSON(notes_json) = 1)
);

CREATE INDEX IX_IngestRun_DatasetStarted
ON kg.IngestRun(dataset_id, started_at DESC);
GO

/* ============================================================
   3) NODE tables (entities + Claim + Evidence)
   Notes:
   - $node_id is implicit on NODE tables.
   - Keep your own surrogate keys for stable joins from ETL.
   ============================================================ */

CREATE TABLE kg.Drug
(
    drug_key             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Drug PRIMARY KEY,
    preferred_name       NVARCHAR(400)        NOT NULL,

    -- common external IDs
    drugcentral_id       INT                 NULL,
    chembl_id            NVARCHAR(32)         NULL,
    pubchem_cid          INT                 NULL,
    inchikey             CHAR(27)             NULL,

    synonyms_json        NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Drug_SynonymsJson CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    xrefs_json           NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Drug_XrefsJson CHECK (xrefs_json IS NULL OR ISJSON(xrefs_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Drug_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Drug_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Drug_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE UNIQUE INDEX UX_Drug_DrugCentralId ON kg.Drug(drugcentral_id) WHERE drugcentral_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Drug_ChEMBLId      ON kg.Drug(chembl_id)      WHERE chembl_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Drug_PubChemCID    ON kg.Drug(pubchem_cid)    WHERE pubchem_cid IS NOT NULL;
CREATE UNIQUE INDEX UX_Drug_InChIKey      ON kg.Drug(inchikey)       WHERE inchikey IS NOT NULL;
GO

CREATE TABLE kg.Gene
(
    gene_key             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Gene PRIMARY KEY,
    hgnc_id              NVARCHAR(32)         NULL,
    symbol               NVARCHAR(64)         NOT NULL,
    ensembl_gene_id      NVARCHAR(32)         NULL,
    uniprot_id           NVARCHAR(16)         NULL,

    synonyms_json        NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Gene_SynonymsJson CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    xrefs_json           NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Gene_XrefsJson CHECK (xrefs_json IS NULL OR ISJSON(xrefs_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Gene_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Gene_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Gene_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE UNIQUE INDEX UX_Gene_HGNC   ON kg.Gene(hgnc_id)         WHERE hgnc_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Gene_EnsG   ON kg.Gene(ensembl_gene_id) WHERE ensembl_gene_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Gene_UniP   ON kg.Gene(uniprot_id)      WHERE uniprot_id IS NOT NULL;
CREATE INDEX        IX_Gene_Symbol ON kg.Gene(symbol);
GO

CREATE TABLE kg.Disease
(
    disease_key          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Disease PRIMARY KEY,
    mondo_id             NVARCHAR(32)         NULL,
    doid                 NVARCHAR(32)         NULL,
    efo_id               NVARCHAR(32)         NULL,  -- common in Open Targets

    label                NVARCHAR(400)        NOT NULL,

    synonyms_json        NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Disease_SynonymsJson CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),
    xrefs_json           NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Disease_XrefsJson CHECK (xrefs_json IS NULL OR ISJSON(xrefs_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Disease_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Disease_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Disease_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE UNIQUE INDEX UX_Disease_MONDO ON kg.Disease(mondo_id) WHERE mondo_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Disease_DOID  ON kg.Disease(doid)     WHERE doid IS NOT NULL;
CREATE UNIQUE INDEX UX_Disease_EFO   ON kg.Disease(efo_id)   WHERE efo_id IS NOT NULL;
CREATE INDEX        IX_Disease_Label ON kg.Disease(label);
GO

CREATE TABLE kg.Pathway
(
    pathway_key          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Pathway PRIMARY KEY,
    reactome_id          NVARCHAR(32)         NULL,
    wikipathways_id      NVARCHAR(32)         NULL,

    label                NVARCHAR(400)        NOT NULL,

    xrefs_json           NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Pathway_XrefsJson CHECK (xrefs_json IS NULL OR ISJSON(xrefs_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Pathway_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Pathway_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Pathway_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE UNIQUE INDEX UX_Pathway_Reactome ON kg.Pathway(reactome_id) WHERE reactome_id IS NOT NULL;
CREATE UNIQUE INDEX UX_Pathway_WP       ON kg.Pathway(wikipathways_id) WHERE wikipathways_id IS NOT NULL;
CREATE INDEX        IX_Pathway_Label    ON kg.Pathway(label);
GO

CREATE TABLE kg.AdverseEvent
(
    ae_key               BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AdverseEvent PRIMARY KEY,
    -- keep ontology open; many pipelines will store raw MedDRA-like terms from sources
    ae_label             NVARCHAR(400)        NOT NULL,
    ae_code              NVARCHAR(64)         NULL,     -- optional: open ontology code if you map (e.g., OAE ID)
    ae_ontology          NVARCHAR(64)         NULL,     -- e.g., 'OAE', 'UMLS', 'raw'

    synonyms_json        NVARCHAR(MAX)        NULL
        CONSTRAINT CK_AE_SynonymsJson CHECK (synonyms_json IS NULL OR ISJSON(synonyms_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_AE_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_AE_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_AE_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE INDEX IX_AE_Label ON kg.AdverseEvent(ae_label);
CREATE INDEX IX_AE_Code  ON kg.AdverseEvent(ae_code) WHERE ae_code IS NOT NULL;
GO

/* ---------------------------
   Claim node: one "assertion"
   --------------------------- */
CREATE TABLE kg.Claim
(
    claim_key            BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Claim PRIMARY KEY,

    claim_type           NVARCHAR(64)         NOT NULL,
    -- examples: 'DRUG_TARGET', 'DRUG_AE_LABEL', 'DRUG_AE_FAERS_SIGNAL', 'GENE_PATHWAY', 'GENE_DISEASE', 'DRUG_DISEASE'

    polarity             SMALLINT             NULL,   -- optional: -1/0/+1 for inhibitory/unknown/activating etc.
    strength_score       FLOAT               NULL,   -- normalized 0..1, computed by your pipeline
    directionality_json  NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Claim_DirectionalityJson CHECK (directionality_json IS NULL OR ISJSON(directionality_json) = 1),

    dataset_id           INT                  NULL CONSTRAINT FK_Claim_Dataset
        FOREIGN KEY REFERENCES kg.Dataset(dataset_id),

    source_record_id     NVARCHAR(256)        NULL,  -- id in source dataset (e.g., openfda safetyreportid)
    statement_json       NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Claim_StatementJson CHECK (statement_json IS NULL OR ISJSON(statement_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Claim_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Claim_CreatedAt DEFAULT SYSUTCDATETIME(),
    updated_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Claim_UpdatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE INDEX IX_Claim_Type ON kg.Claim(claim_type);
CREATE INDEX IX_Claim_Dataset ON kg.Claim(dataset_id) WHERE dataset_id IS NOT NULL;
CREATE INDEX IX_Claim_SourceRecord ON kg.Claim(source_record_id) WHERE source_record_id IS NOT NULL;
GO

/* ---------------------------
   Evidence node: provenance payload
   --------------------------- */
CREATE TABLE kg.Evidence
(
    evidence_key         BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Evidence PRIMARY KEY,

    dataset_id           INT                  NULL CONSTRAINT FK_Evidence_Dataset
        FOREIGN KEY REFERENCES kg.Dataset(dataset_id),

    evidence_type        NVARCHAR(64)         NOT NULL,
    -- examples: 'CURATED_DB', 'LABEL_SECTION', 'FAERS_CASE', 'FAERS_SIGNAL', 'TRIAL_REGISTRY', 'PATHWAY_CURATED'

    source_record_id     NVARCHAR(256)        NULL,
    source_url           NVARCHAR(2048)       NULL,

    payload_json         NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Evidence_PayloadJson CHECK (payload_json IS NULL OR ISJSON(payload_json) = 1),

    embedding            VECTOR(1536)         NULL,
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_Evidence_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),

    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_Evidence_CreatedAt DEFAULT SYSUTCDATETIME()
) AS NODE;
GO

CREATE INDEX IX_Evidence_Type ON kg.Evidence(evidence_type);
CREATE INDEX IX_Evidence_Dataset ON kg.Evidence(dataset_id) WHERE dataset_id IS NOT NULL;
CREATE INDEX IX_Evidence_SourceRecord ON kg.Evidence(source_record_id) WHERE source_record_id IS NOT NULL;
GO

/* ============================================================
   4) EDGE tables (typed relationships)
   Notes:
   - $edge_id, $from_id, $to_id are implicit on EDGE tables.
   - Create indexes on ($from_id, $to_id) for traversal performance.
   ============================================================ */

-- Drug -> Claim
CREATE TABLE kg.HasClaim
(
    role                 NVARCHAR(32)         NULL,  -- optional: 'subject', etc.
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_HasClaim_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_HasClaim_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_HasClaim_FromTo ON kg.HasClaim($from_id, $to_id);
GO

-- Claim -> Gene
CREATE TABLE kg.ClaimGene
(
    relation             NVARCHAR(64)         NULL,  -- e.g., 'targets', 'associated_with'
    effect               NVARCHAR(64)         NULL,  -- optional: 'inhibits','activates','unknown'
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_ClaimGene_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_ClaimGene_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_ClaimGene_FromTo ON kg.ClaimGene($from_id, $to_id);
GO

-- Claim -> Disease
CREATE TABLE kg.ClaimDisease
(
    relation             NVARCHAR(64)         NULL,  -- e.g., 'indication','contraindication','risk_factor_context'
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_ClaimDisease_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_ClaimDisease_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_ClaimDisease_FromTo ON kg.ClaimDisease($from_id, $to_id);
GO

-- Claim -> Pathway
CREATE TABLE kg.ClaimPathway
(
    relation             NVARCHAR(64)         NULL,  -- e.g., 'perturbs','member_of'
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_ClaimPathway_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_ClaimPathway_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_ClaimPathway_FromTo ON kg.ClaimPathway($from_id, $to_id);
GO

-- Claim -> AdverseEvent
CREATE TABLE kg.ClaimAdverseEvent
(
    relation             NVARCHAR(64)         NULL,  -- e.g., 'causes','associated_with','listed_in_label'
    frequency            FLOAT                NULL,  -- e.g., SIDER freq or label bucket normalized
    signal_score         FLOAT                NULL,  -- e.g., PRR/ROR/IC normalized for FAERS
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_ClaimAE_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_ClaimAE_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_ClaimAE_FromTo ON kg.ClaimAdverseEvent($from_id, $to_id);
GO

-- Claim -> Evidence
CREATE TABLE kg.SupportedBy
(
    support_strength     FLOAT                NULL,  -- optional: per-evidence weight 0..1
    meta_json            NVARCHAR(MAX)        NULL
        CONSTRAINT CK_SupportedBy_MetaJson CHECK (meta_json IS NULL OR ISJSON(meta_json) = 1),
    created_at           DATETIME2(3)         NOT NULL CONSTRAINT DF_SupportedBy_CreatedAt DEFAULT SYSUTCDATETIME()
) AS EDGE;
GO
CREATE INDEX IX_SupportedBy_FromTo ON kg.SupportedBy($from_id, $to_id);
GO
