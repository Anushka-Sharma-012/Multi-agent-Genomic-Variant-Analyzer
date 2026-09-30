import os, json, httpx
from datetime import datetime
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agents import parse_vcf, research, synthesize, verify, cites_out

app = FastAPI(title="Provenance")

class Req(BaseModel):
    vcf: str
    simulate_bad: bool = False
    live: bool = False

@app.post("/api/analyze")
async def analyze(req: Req):
    log, out, rejected = [], [], []
    stats = dict(variants=0, claims=0, verified=0, review=0, rejected=0)
    variants = parse_vcf(req.vcf)
    stats["variants"] = len(variants)
    async with httpx.AsyncClient(timeout=15) as client:
        for v in variants:
            r, how = await research(v, req.live, client)
            log.append(["a1", f"[Research] {v['id']}: {how}" if r else f"[Research] {v['id']}: no evidence found. No claims will be written."])
            item = {"id": v["id"], "chr": v["chr"], "pos": v["pos"], "found": bool(r), "claims": []}
            if r:
                item.update(gene=r["gene"], hgvs=r["hgvs"], impact=r["impact"], sig=r["sig"])
                claims, writer = synthesize(r, req.simulate_bad)
                log.append(["a2", f"[Synthesis] {len(claims)} claims drafted by {writer}"])
                for c in claims:
                    status, why = verify(r, c)
                    stats["claims"] += 1; stats[status] += 1
                    entry = {"text": c["text"], "status": status, "why": why, "cites": cites_out(r, c.get("cites", []))}
                    (rejected if status == "rejected" else item["claims"]).append(entry | {"gene": r["gene"] or v["id"]} if status == "rejected" else entry)
                log.append(["a3", f"[Verify] {v['id']} audited"])
            out.append(item)
    log.append(["a3", f"[Verify] Done. {stats['verified']} verified, {stats['review']} need review, {stats['rejected']} rejected."])
    return {"log": log, "stats": stats, "variants": out, "rejected": rejected}

class Signoff(BaseModel):
    audit: dict

@app.post("/api/signoff")
async def signoff(s: Signoff):
    """Persist the reviewer's decisions and audit trail."""
    os.makedirs("audit", exist_ok=True)
    path = f"audit/{datetime.now():%Y%m%d-%H%M%S}.json"
    with open(path, "w") as f:
        json.dump(s.audit, f, indent=2)
    return {"saved": path}

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend"), html=True), name="ui")
