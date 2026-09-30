# Provenance prototype

Evidence-first multi-agent genomic variant analyzer: research -> synthesize -> verify.

## Run
    cd backend
    python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    uvicorn app:app --reload
Open http://127.0.0.1:8000

## Modes
- Default: bundled snapshot (3 real variants + 1 synthetic conflict case), works offline.
- "Use live databases": queries Ensembl (clinical significance, MAF, VEP) and Europe PMC by rsID. Falls back to the snapshot on failure.
- Set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`) so the synthesis agent uses an LLM. Without it, a rule-based writer is used.

## Layout
- backend/sources.py  data sources + snapshot
- backend/agents.py   the three agents (verifier is deterministic)
- backend/app.py      FastAPI: POST /api/analyze, serves the frontend
- frontend/index.html UI

## Notes
- Live lookups use rsIDs; the CHROM/POS columns in the sample VCF are placeholders.
- Allele frequency in live mode is Ensembl's MAF. Swap in the gnomAD GraphQL API for true gnomAD values.
- Research use only. Not clinical advice.

## Clinician workflow
1. Enter case ID and reviewer name, paste the VCF, click Analyze case.
2. The queue is ordered: flagged claims first, then high-impact auto-verified, then the rest, then variants with no evidence.
3. For each flagged claim compare the sources side by side and choose Accept, Edit wording, Reject or Escalate. A note is required.
4. Sign-off unlocks only when every flagged claim has a decision. It generates the report (with uncertainty section and audit trail) and saves the audit JSON to backend/audit/.
5. The report can be printed or saved as PDF from the browser.
The frontend falls back to an in-browser engine with the bundled snapshot when no backend is reachable.

## Checking sources yourself
- Every rsID variant has a "Check it yourself" row (ClinVar, dbSNP, gnomAD, Ensembl, PubMed, Europe PMC).
- Each source card has an "Open source" link. In live mode, literature cards link to the PubMed record (or DOI) and include a "Read abstract" panel from Europe PMC.
- Bundled snapshot literature lines are curated summaries, not tied to one paper: they link to a Europe PMC search for the variant.
- SYN-0001 is synthetic and has no real papers.
