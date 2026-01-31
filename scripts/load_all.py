"""Load all data sources into the knowledge graph."""

from kg_ae.datasets.sider import (
    SIDERDownloader, SIDERParser, SIDERNormalizer, SIDERLoader
)
from kg_ae.datasets.drugcentral import (
    DrugCentralDownloader, DrugCentralParser, DrugCentralNormalizer, DrugCentralLoader
)
from kg_ae.datasets.reactome import (
    ReactomeDownloader, ReactomeParser, ReactomeNormalizer, ReactomeLoader
)
from kg_ae.datasets.opentargets import (
    OpenTargetsDownloader, OpenTargetsParser, OpenTargetsNormalizer, OpenTargetsLoader
)

SOURCES = [
    ("SIDER", SIDERDownloader, SIDERParser, SIDERNormalizer, SIDERLoader),
    ("DrugCentral", DrugCentralDownloader, DrugCentralParser, DrugCentralNormalizer, DrugCentralLoader),
    ("Reactome", ReactomeDownloader, ReactomeParser, ReactomeNormalizer, ReactomeLoader),
    ("OpenTargets", OpenTargetsDownloader, OpenTargetsParser, OpenTargetsNormalizer, OpenTargetsLoader),
]

if __name__ == "__main__":
    for name, Downloader, Parser, Normalizer, Loader in SOURCES:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        Downloader().download()
        Parser().parse()
        Normalizer().normalize()
        Loader().load()
    print("\n✓ All sources loaded.")
