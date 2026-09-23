# pv-agent: agent instructions

Pharmacovigilance assistant. A LangGraph over live public APIs answers drug interaction,
adverse event and mechanism questions with cited sources. No database, no local data.

Read `README.md` first for the graph diagram and source list.

## Hard rules

- Every factual claim in an answer cites a `[ref:N]` id that exists in `tools.STORE`. `graph._check`
  enforces this in code before any model review. Do not weaken it.
- Tools fetch, trim and cite. They never infer. Judgement belongs to the model, working from what
  it is shown.
- Tools never raise. A dead source returns `{"error": ...}` so the graph continues with partial
  evidence.
- Every tool payload is capped at `tools.MAX_CHARS`. A 52 KB tool result once made the model reply
  with nothing.
- User spelling never reaches a downstream tool. `graph._resolve` runs first and maps
  `ciclosporin`, `co-trimoxazole`, `paracetamol` to RxNorm generics via approximate match.
- Web search (`sources/web.py`) is scrubbed against a biomedical allowlist before transmission and
  restricted to regulator/literature domains. It is weaker evidence than a label and the prompt
  says so.
- Only open-source models. Current: `deepseek/deepseek-v4.1-flash` via OpenRouter.
- No emojis anywhere.

## Layout

```
src/pv_agent/
  chat.py      rich terminal: `pv chat` (loop, /exit) and `pv ask "..."`
  graph.py     plan -> resolve -> [us_labels | eu_labels | signals | mechanism] -> answer -> check -> verify
  tools.py     the LangChain tools + RefStore (the [ref:N] registry)
  llm.py       one ChatOpenAI factory
  config.py    settings, PV_ prefix, keys read unprefixed from .env
  sources/     one thin client per API: rxnorm, openfda, ema, chembl, opentargets, dgidb,
               pathways, europepmc, web (Tavily + scrubber), http
```

## Commands

```powershell
uv sync
uv run pv chat
uv run pv ask "Is there an interaction between ciclosporin and posaconazole?"
uv run ruff check src; uv run ruff format src
```

## Source gotchas (all verified live; do not re-litigate)

- openFDA label search must exclude `route:OPHTHALMIC` and prefer records with interaction
  text, or "cyclosporine" returns eye drops and looks like the systemic label is missing.
- EMA SmPC PDFs split ligatures (`eff ects`) and wrap headings; `sources/ema.py` handles both.
  Use short heading titles when matching sections.
- The EMA medicines spreadsheet carries authorisation status. Filter withdrawn products there;
  do not guess from page text.
- RxNav's drug-interaction API is retired (404). Interactions come from labels only.
- Use RxNorm `properties.json` (plural). `property.json` 400s.
- DGIdb `interactionScore` is distinctiveness, not evidence strength. Rank by interaction type
  and source count first.
- UniProt: take the Swiss-Prot (reviewed) accession. TrEMBL accessions 404 on Reactome.
- Open Targets drug search is fuzzy and returns proteins. Require an exact name match.
- Tavily 0.8.4: set `include_domains_mode="restrict"` explicitly; default lets the provider
  return off-domain pages.

## LangGraph gotchas

- Node `config` params are annotated `Optional[RunnableConfig]` with `# noqa: UP045`. LangGraph
  string-matches the annotation and does not accept the `| None` spelling under postponed
  annotations.
- Parallel fan-out uses `Send`. Branch outputs merge through the `evidence` reducer.
