"""Clean up STRING claims for reload."""

from kg_ae.db.connection import execute

# Delete edges first
print("Deleting HasClaim edges...")
execute(
    "DELETE e FROM kg.HasClaim e "
    "INNER JOIN kg.Claim c ON e.$to_id = c.$node_id "
    "WHERE c.claim_type = 'GENE_GENE_STRING'"
)

print("Deleting ClaimGene edges...")
execute(
    "DELETE e FROM kg.ClaimGene e "
    "INNER JOIN kg.Claim c ON e.$from_id = c.$node_id "
    "WHERE c.claim_type = 'GENE_GENE_STRING'"
)

print("Deleting STRING claims...")
execute("DELETE FROM kg.Claim WHERE claim_type = 'GENE_GENE_STRING'")

print("Done!")
