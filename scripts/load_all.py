"""Load all data sources into the knowledge graph.

ETL pipeline for all datasets. Order matters:
1. SIDER - Drug names and AE terms (creates base Drug/AE nodes)
2. DrugCentral - Drug targets (enriches Drug nodes, creates Gene nodes)
3. HGNC - Gene nomenclature (enriches Gene nodes with canonical data)
4. GtoPdb - Drug-target pharmacology (adds curated drug-target claims)
5. Reactome - Pathways (creates Pathway nodes and gene-pathway claims)
6. OpenTargets - Gene-disease associations (enriches Disease nodes)
"""

from kg_ae.datasets.sider import (
    SIDERDownloader, SIDERParser, SIDERNormalizer, SIDERLoader
)
from kg_ae.datasets.drugcentral import (
    DrugCentralDownloader, DrugCentralParser, DrugCentralNormalizer, DrugCentralLoader
)
from kg_ae.datasets.hgnc import (
    HGNCDownloader, HGNCParser, HGNCLoader
)
from kg_ae.datasets.gtop import (
    GtoPdbDownloader, GtoPdbParser, GtoPdbLoader
)
from kg_ae.datasets.reactome import (
    ReactomeDownloader, ReactomeParser, ReactomeNormalizer, ReactomeLoader
)
from kg_ae.datasets.opentargets import (
    OpenTargetsDownloader, OpenTargetsParser, OpenTargetsNormalizer, OpenTargetsLoader
)

# Sources with full ETL pipeline (download → parse → normalize → load)
SOURCES_FULL = [
    ("SIDER", SIDERDownloader, SIDERParser, SIDERNormalizer, SIDERLoader),
    ("DrugCentral", DrugCentralDownloader, DrugCentralParser, DrugCentralNormalizer, DrugCentralLoader),
    ("Reactome", ReactomeDownloader, ReactomeParser, ReactomeNormalizer, ReactomeLoader),
    ("OpenTargets", OpenTargetsDownloader, OpenTargetsParser, OpenTargetsNormalizer, OpenTargetsLoader),
]

# Sources with simplified ETL (download → parse → load, no normalization)
SOURCES_SIMPLE = [
    ("HGNC", HGNCDownloader, HGNCParser, HGNCLoader),
    ("GtoPdb", GtoPdbDownloader, GtoPdbParser, GtoPdbLoader),
]

def load_all():
    """Load all data sources in order."""
    
    # Phase 1: Load base datasets (SIDER, DrugCentral)
    print("\n" + "=" * 60)
    print("PHASE 1: Base datasets (SIDER, DrugCentral)")
    print("=" * 60)
    
    for name, Downloader, Parser, Normalizer, Loader in SOURCES_FULL[:2]:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        Downloader().download()
        Parser().parse()
        Normalizer().normalize()
        Loader().load()
    
    # Phase 2: Enrich genes with canonical HGNC data
    print("\n" + "=" * 60)
    print("PHASE 2: Gene enrichment (HGNC)")
    print("=" * 60)
    
    print(f"\n{'='*60}\nHGNC\n{'='*60}")
    HGNCDownloader().download()
    HGNCParser().parse()
    HGNCLoader().load()
    
    # Phase 3: Add curated pharmacology (GtoPdb)
    print("\n" + "=" * 60)
    print("PHASE 3: Curated pharmacology (GtoPdb)")
    print("=" * 60)
    
    print(f"\n{'='*60}\nGtoPdb\n{'='*60}")
    GtoPdbDownloader().download()
    GtoPdbParser().parse()
    GtoPdbLoader().load()
    
    # Phase 4: Load remaining datasets (Reactome, OpenTargets)
    print("\n" + "=" * 60)
    print("PHASE 4: Pathways & disease associations (Reactome, OpenTargets)")
    print("=" * 60)
    
    for name, Downloader, Parser, Normalizer, Loader in SOURCES_FULL[2:]:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        Downloader().download()
        Parser().parse()
        Normalizer().normalize()
        Loader().load()
    
    print("\n" + "=" * 60)
    print("✓ All sources loaded successfully!")
    print("=" * 60)

if __name__ == "__main__":
    load_all()
