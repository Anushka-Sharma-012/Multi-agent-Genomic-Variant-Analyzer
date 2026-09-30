"""The three agents: research -> synthesize -> verify."""
import json, os, re
from sources import snapshot, live, source_text, links

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
LABEL = {"clinvar": "ClinVar", "freq": "Population frequency", "vep": "Ensembl VEP", "lit": "Literature"}

def parse_vcf(text):
    out = []
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            f = line.split()
            if len(f) >= 3:
                out.append({"chr": f[0], "pos": f[1], "id": f[2]})
    return out

def cat(af):
    return "rare" if af < 0.001 else "low-frequency" if af < 0.01 else "common"

# Agent 1
async def research(v, use_live, client):
    if use_live and v["id"].startswith("rs"):
        try:
            rec = await live(v["id"], client)
            if rec: return rec, "live"
        except Exception as e:
            return snapshot(v["id"]), f"live lookup failed ({type(e).__name__}), used snapshot"
    return snapshot(v["id"]), "snapshot"

# Agent 2
def rule_claims(r):
    who = " ".join(x for x in (r["gene"], r["hgvs"]) if x) or r["id"]
    c = []
    if r["sig"]: c.append(dict(text=f"ClinVar classifies {who} as {r['sig']}.", field="sig", value=r["sig"], cites=["clinvar"]))
    if r["af"] is not None: c.append(dict(text=f"The variant is {cat(r['af'])} in the general population.", field="af", value=cat(r["af"]), cites=["freq"]))
    if r["csq"]: c.append(dict(text=f"It is predicted to cause a {r['csq'].replace('_', ' ')}.", field="csq", value=r["csq"], cites=["vep"]))
    if r["lit"]: c.append(dict(text=f"{len(r['lit'])} literature item(s) discuss this variant.", field="lit", value=len(r["lit"]), cites=["lit"]))
    return c

def llm_claims(r):
    import anthropic
    system = ("You write claims for a genomic report using ONLY the evidence JSON. Return ONLY a JSON list of "
              "{text, field, value, cites}. field is one of sig, af, csq, lit. value: sig -> the classification string; "
              "af -> rare|low-frequency|common (rare<0.001, low-frequency<0.01); csq -> the consequence term; "
              "lit -> integer count of literature items. cites is a list drawn from clinvar, freq, vep, lit.")
    m = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=1000, system=system,
        messages=[{"role": "user", "content": json.dumps(r)}])
    return json.loads(re.sub(r"```json|```", "", m.content[0].text).strip())

def synthesize(r, bad):
    try:
        claims = llm_claims(r) if os.getenv("ANTHROPIC_API_KEY") else rule_claims(r)
        writer = "LLM" if os.getenv("ANTHROPIC_API_KEY") else "rules"
    except Exception:
        claims, writer = rule_claims(r), "rules (LLM failed)"
    if bad:
        claims.append(dict(text=f"{r['gene'] or r['id']} is benign.", field="sig", value="Benign", cites=["clinvar"]))
        claims.append(dict(text="Carriers should start targeted therapy immediately.", field=None, value=None, cites=[]))
    return claims, writer

# Agent 3 (deterministic: it never trusts the writer)
def verify(r, c):
    if not c.get("cites"): return "rejected", "No citation. Every claim must link to a source."
    actual = {"sig": r["sig"], "af": cat(r["af"]) if r["af"] is not None else None, "csq": r["csq"], "lit": len(r["lit"])}.get(c.get("field"))
    try: same = actual is not None and str(actual) == str(c["value"])
    except Exception: same = False
    if not same: return "rejected", f"Cited source says \"{actual}\", not \"{c.get('value')}\"."
    if c["cites"][0] == "clinvar" and r["conflict"]: return "review", "ClinVar submitters disagree. A human reviewer should decide."
    if c["cites"][0] == "lit" and r["lit_conflict"]: return "review", "Studies disagree on functional effect. Both shown."
    return "verified", "Matches the cited source."

def cites_out(r, keys):
    out = []
    for k in keys:
        if k == "lit":
            out += [{"label": x[0], "text": x[1], "url": x[2], "detail": x[3]} for x in r["lit"]]
        elif k in LABEL:
            out.append({"label": LABEL[k], "text": source_text(r, k), "url": links(r["id"]).get(k)})
    return out
