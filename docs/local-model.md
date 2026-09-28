# Run pv-agent with a model on your own computer

This guide sets up pv-agent so the language model runs on your own graphics card instead of
OpenRouter. You do not need an OpenRouter key. The drug databases (FDA, EMA, FAERS, ChEMBL,
Open Targets and others) are still queried over the internet, so you need a connection.

It was tested on Windows 11 with an AMD Radeon RX 6700 XT (12 GB). The same steps work on
NVIDIA cards.

## The model

[Qwen3-4B-Instruct-2507](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF), in the
`Q4_K_M` quantized file.

- About 2.5 GB to download and about 3 GB of graphics memory while running.
- It can call tools, which pv-agent needs for its lookups.
- A question takes 1 to 5 minutes, depending on how many drugs are in it.

"Quantized" means the model's numbers are stored with fewer digits. The file is about four
times smaller and the answers are only slightly worse. `Q4_K_M` is the usual middle setting.

## What to expect

We ran the five demo questions on this model. It got three right: it answered the
ciclosporin and posaconazole question from both labels, refused an invented drug and explained
statin myopathy with evidence levels. It got two wrong: it misread the EU letermovir label, and
it misspelled letermovir so the agent looked up a different drug.

Use it to try the tool, or when data must not leave your machine. For real questions, compare
its answer with the sources (`/refs`) or use OpenRouter.

## What you need

- Windows 10 or 11
- A graphics card with at least 4 GB of memory and up-to-date drivers
- About 5 GB of free disk space
- pv-agent installed (see the main [README](../README.md): clone the repository and run `uv sync`)

## Step 1. Install llama.cpp

llama.cpp is the program that runs the model and gives pv-agent an address to talk to. Open
PowerShell and run:

```powershell
winget install ggml.llamacpp
```

winget installs the Vulkan build. Vulkan works with the normal graphics driver on AMD, NVIDIA
and Intel cards, so you do not need ROCm or CUDA.

**Close PowerShell and open a new window.** The install adds `llama-server` to your PATH, but
windows that were already open do not see it.

Check it worked:

```powershell
llama-server --version
```

You should see a version line such as `version: 11193`.

## Step 2. Start the model server

In PowerShell, run:

```powershell
llama-server -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M --jinja -c 32768 -ngl 99 --port 8080
```

What each part means:

| Part | Meaning |
|---|---|
| `-hf unsloth/...:Q4_K_M` | Download this model from Hugging Face the first time, then reuse the saved copy |
| `--jinja` | Use the model's own chat format. Tool calls do not work without it |
| `-c 32768` | How much text the model can hold at once. Drug labels are long, so keep this |
| `-ngl 99` | Put the whole model on the graphics card |
| `--port 8080` | The address pv-agent will connect to |

The first run downloads 2.5 GB. When you see this line, the server is ready:

```
llama_server: listening on http://127.0.0.1:8080
```

**Leave this window open.** Closing it stops the model.

## Step 3. Check the server answers

Open a second PowerShell window and run:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

It should print `status: ok`.

## Step 4. Ask a question

In the second window, go to the pv-agent folder and run:

```powershell
cd path\to\Adverse-Events-Knowledge-Graph
uv run pv ask "Is there an interaction between ciclosporin and posaconazole?" --model local
```

You will see each lookup appear as it finishes, then the answer, then a line with the time and
the sources used.

## Step 5. Start a conversation

```powershell
uv run pv chat --model local
```

Type a question at the `>` prompt. The chat remembers your last few questions, so follow-ups
like "and what about tacrolimus?" work.

| Type | To |
|---|---|
| `/refs` | list every source behind the last answer, with links |
| `/network` | show the genes, pathways and reported events the drugs share |
| `/clear` | forget the conversation |
| `/exit` | quit |

To run the prepared demo instead:

```powershell
.\demo.ps1 -Local
```

## Switching back to OpenRouter

Leave out `--model local`, or pass `--model openrouter`. That uses the OpenRouter key in `.env`.

```powershell
uv run pv chat --model openrouter
```

## Each time after the first

1. Open PowerShell and start the server (step 2). It loads in a few seconds now.
2. Open a second PowerShell window and run `uv run pv chat --model local`.

## Problems

**`llama-server` is not recognized.** The window was open before the install. Open a new one.
If that fails, run it by its full path:

```powershell
& "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe" --version
```

**`couldn't bind HTTP server socket ... port: 8080`.** Another program is using port 8080.
Start the server on a different port and tell pv-agent where it is:

```powershell
llama-server -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M --jinja -c 32768 -ngl 99 --port 8089
uv run pv chat --model local --local-url http://127.0.0.1:8089/v1
```

**pv-agent says the connection was refused.** The server is not running, or it is on a
different port. Check the server window is still open and run step 3 again.

**Answers are very slow and the graphics card is idle.** The model is running on the
processor. Look in the server window for a line naming your graphics card. If none appears,
update the graphics driver.

**Out of memory when loading.** Lower the text size with `-c 16384`. If that is not enough, the
card is too small for this model.

## Trying a larger model

A larger model should make fewer of the mistakes listed above. It is slower, and we have not
tested one with pv-agent. With 12 GB of graphics memory, this one fits:

```powershell
llama-server -hf unsloth/Qwen3-14B-GGUF:Q4_K_M --jinja -c 32768 -ngl 99 --port 8080
```

That is a 9 GB download. pv-agent waits 120 seconds for each model reply
(`timeout=120` in `src/pv_agent/llm.py`). A slower model may run past that on long questions.
