# pv-agent

A pharmacovigilance assistant that runs in your terminal. Ask about drug interactions, adverse
events or mechanisms in plain language. It looks up the answer in public drug databases (FDA
and EMA labels, adverse event reports, ChEMBL, Open Targets, Reactome and others) while you
wait, and cites a source for every claim.

## What you need

- **Windows, macOS or Linux** with a terminal
- **uv**, the Python package manager. Install it from https://docs.astral.sh/uv/. It installs
  the right Python version for you.
- **An OpenRouter API key** (required)
- **A Tavily API key** (optional)

## API keys

| Key | Required? | What it is for | Where to get it | Cost |
|---|---|---|---|---|
| OpenRouter | Yes | Runs the language model that reads the evidence and writes the answer | https://openrouter.ai/keys | Pay per use. Load a few dollars of credit; one question costs a few cents |
| Tavily | No | Searches regulator websites (EMA, MHRA, FDA and others) for documents the databases do not cover | https://app.tavily.com | Free for 1,000 searches a month, no card needed |

Without an OpenRouter key the program will not start. Without a Tavily key it runs normally and
leaves out regulator web search; every other source still works.

OpenRouter recommends setting a spending limit on each key. Do that when you create it.

## Getting started

**1. Clone the repository**

```
git clone -b rewrite/pv-agent-v2 https://github.com/rangan2510/Adverse-Events-Knowledge-Graph.git
cd Adverse-Events-Knowledge-Graph
```

**2. Install**

```
uv sync
```

**3. Add your keys**

Either put them in a file. Copy `.env.example` to `.env` and fill in the two lines:

```
OPENROUTER_API_KEY=sk-or-v1-...
TAVILY_API_KEY=tvly-...
```

Or pass them each time you run it:

```
uv run pv chat --openrouter-key sk-or-v1-... --tavily-key tvly-...
```

If a key is in both places, the one on the command line is used. The `.env` file is safer: keys
typed on the command line end up in your shell history.

**4. Run it**

```
uv run pv chat
```

Type a question at the `>` prompt. Each answer takes one to four minutes; you will see each
lookup appear as it happens.

## Ways to run it

```
uv run pv chat                  # a conversation that remembers the last few questions
uv run pv ask "your question"   # one question, then exit
uv run pv demo                  # five prepared questions, pausing between each
```

Inside `chat`:

| Type | To |
|---|---|
| `/refs` | see every source behind the last answer, with links |
| `/network` | see which genes, pathways and reported events the drugs share |
| `/clear` | forget the conversation |
| `/exit` | quit |

With `ask`, add `--refs` or `--network` to print those after the answer.

On Windows, `.\demo.ps1` runs the demo and checks your setup first. Add `-Chat` to start a
conversation instead.

## Example questions

- Is there a drug interaction between cyclosporin and posaconazole? What is the mechanism?
- Are there interactions between cyclosporin, posaconazole and letermovir?
- Why does atorvastatin cause myopathy? Which genes and pathways are involved?

British, US and international drug spellings all work: ciclosporin, cyclosporin and
cyclosporine find the same drug.

## Limits

- This is research and decision support for qualified professionals. It is not a prescribing
  tool.
- EU labels exist only for medicines approved centrally by the EMA. Older drugs approved country
  by country, such as cyclosporine, have none.
- Adverse event report counts show how often something was reported, not how often it happens.
