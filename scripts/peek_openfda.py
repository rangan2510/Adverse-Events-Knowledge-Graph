"""Inspect openFDA download manifest."""
import json

with open("data/raw/openfda/download.json") as f:
    manifest = json.load(f)

print("=== openFDA Download Manifest ===")
print(f"Endpoints available: {list(manifest['results'].keys())}")

# Check drug endpoints
drug = manifest["results"]["drug"]
print(f"\nDrug endpoints: {list(drug.keys())}")

# FAERS event data
event = drug["event"]
parts = event.get("partitions", [])
print(f"\nFAERS partitions: {len(parts)}")
total_size = sum(float(p.get("size_mb", 0) or 0) for p in parts)
print(f"Total size: {total_size:.0f} MB")
if parts:
    print(f"Sample partition: {parts[0]['file'][:80]}...")
    print(f"Export date: {event.get('export_date', 'N/A')}")
    # Show date range
    dates = [p.get("file", "").split("/")[-1].replace(".json.zip", "") for p in parts]
    dates = [d for d in dates if d and d[0].isdigit()]
    if dates:
        print(f"Date range: {min(dates)} to {max(dates)}")

# Label data
label = drug["label"]
label_parts = label.get("partitions", [])
print(f"\nLabel partitions: {len(label_parts)}")
label_size = sum(float(p.get("size_mb", 0) or 0) for p in label_parts)
print(f"Total size: {label_size:.0f} MB")
if label_parts:
    print(f"Sample: {label_parts[0]['file'][:80]}...")

# NDC data
ndc = drug["ndc"]
ndc_parts = ndc.get("partitions", [])
print(f"\nNDC partitions: {len(ndc_parts)}")
ndc_size = sum(float(p.get("size_mb", 0) or 0) for p in ndc_parts)
print(f"Total size: {ndc_size:.0f} MB")
