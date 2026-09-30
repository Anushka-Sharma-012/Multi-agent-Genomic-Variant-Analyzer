"""Evidence sources. Live lookups (Ensembl, Europe PMC) with an offline snapshot fallback.
Every record uses the same shape:
{id, gene, hgvs, sig, review, conflict, af, csq, impact, lit:[[ref,text]], lit_conflict, origin}
A field that could not be found is None, and no claim is written for it."""

SNAPSHOT = {
 "rs80357906": dict(gene="BRCA1", hgvs="c.5266dup (p.Gln1756fs)", sig="Pathogenic", review="reviewed by expert panel", conflict=False, af=0.0001, csq="frameshift_variant", impact="HIGH", lit=[["Literature", "Recurrent founder variant reported in breast and ovarian cancer families."]]),
 "rs113993960": dict(gene="CFTR", hgvs="c.1521_1523del (p.Phe508del)", sig="Pathogenic", review="reviewed by expert panel", conflict=False, af=0.007, csq="inframe_deletion", impact="MODERATE", lit=[["Literature", "Most common cystic fibrosis-causing variant in people of European ancestry."]]),
 "rs334": dict(gene="HBB", hgvs="c.20A>T (p.Glu7Val)", sig="Pathogenic", review="reviewed by expert panel", conflict=False, af=0.005, csq="missense_variant", impact="MODERATE", lit=[["Literature", "Causes sickle cell disease when inherited from both parents."]]),
 "SYN-0001": dict(gene="GENE1", hgvs="c.123A>G (p.Lys41Arg)", sig="Conflicting interpretations", review="2 submitters disagree", conflict=True, af=0.0004, csq="missense_variant", impact="MODERATE", lit=[["Study A (synthetic)", "Assay shows loss of protein function."], ["Study B (synthetic)", "Assay shows no functional change."]], lit_conflict=True),
}
ENS = "https://rest.ensembl.org"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
JSON = {"content-type": "application/json"}

def links(rsid):
    """Stable public pages for an rsID. Empty for non-rs identifiers."""
    if not rsid.startswith("rs"):
        return {}
    return {"clinvar": f"https://www.ncbi.nlm.nih.gov/clinvar/?term={rsid}",
            "dbsnp": f"https://www.ncbi.nlm.nih.gov/snp/{rsid}",
            "freq": f"https://gnomad.broadinstitute.org/variant/{rsid}?dataset=gnomad_r4",
            "vep": f"https://www.ensembl.org/Homo_sapiens/Variation/Explore?v={rsid}",
            "lit": f"https://europepmc.org/search?query={rsid}"}

def snapshot(rsid):
    r = SNAPSHOT.get(rsid)
    if not r:
        return None
    url = links(rsid).get("lit")  # snapshot summaries are not tied to one paper: link to a search
    lit = [[a, b, url, ""] for a, b in r["lit"]]
    return dict(r, id=rsid, lit=lit, lit_conflict=r.get("lit_conflict", False), origin="snapshot")

def _sig_class(s):
    s = s.lower()
    return "benign" if "benign" in s else "uncertain" if "uncertain" in s else "pathogenic"

async def live(rsid, client):
    """Query Ensembl (variation + VEP) and Europe PMC. Returns a record or None."""
    v = (await client.get(f"{ENS}/variation/human/{rsid}", params=JSON)).json()
    if "error" in v:
        return None
    sigs = v.get("clinical_significance") or []
    conflict = len({_sig_class(s) for s in sigs}) > 1
    rec = dict(id=rsid, gene=None, hgvs=None, review="from Ensembl clinical_significance", conflict=conflict,
               sig=("Conflicting interpretations" if conflict else sigs[0].capitalize()) if sigs else None,
               af=v.get("MAF"), csq=v.get("most_severe_consequence"), impact=None, lit=[], lit_conflict=False, origin="live")
    try:
        vep = (await client.get(f"{ENS}/vep/human/id/{rsid}", params={**JSON, "hgvs": 1})).json()[0]
        tc = (vep.get("transcript_consequences") or [{}])[0]
        rec.update(gene=tc.get("gene_symbol"), hgvs=tc.get("hgvsc"), impact=tc.get("impact"))
    except Exception:
        pass
    try:
        p = (await client.get(EPMC, params={"query": f'"{rsid}"', "format": "json", "pageSize": 5, "resultType": "core"})).json()
        import re
        for r in p["resultList"]["result"]:
            pmid, doi = r.get("pmid"), r.get("doi")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else None)
            label = f"PMID {pmid or '?'} ({r.get('journalTitle', 'journal n/a')}, {r.get('pubYear', 'n/a')})"
            rec["lit"].append([label, r.get("title", ""), url, re.sub(r"<[^>]+>", "", r.get("abstractText", ""))])
    except Exception:
        pass
    return rec

def source_text(rec, key):
    if key == "clinvar": return f"ClinVar (via Ensembl): {rec['sig']} ({rec['review']})."
    if key == "freq": return f"Minor allele frequency about {rec['af']} ({rec['origin']} data)."
    if key == "vep": return f"Ensembl VEP: {rec['csq']}, impact {rec['impact'] or 'not reported'}."
    return " ".join(f"{x[0]}: {x[1]}" for x in rec["lit"])
