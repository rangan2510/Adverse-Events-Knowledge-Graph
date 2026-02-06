# Agent Control Flow: ReAct Iterative Loop

```mermaid
flowchart TD
    START(["User Query"])
    INIT["Initialize IterativeContext<br>max_iterations = 3<br>cumulative_context = empty"]
    CHECK_CONTINUE{"Can continue?<br>iteration < max"}

    subgraph REACT_LOOP ["ReAct Iteration Loop"]
        direction TB
        THOUGHT["**THOUGHT + ACTION**<br>Planner LLM (small model)<br>- Reasons about gaps<br>- Selects tools + args<br>- Outputs ToolPlan"]
        
        STOP_CHECK{"Planner<br>stop signal?"}
        STOP_REASON["sufficient_information<br>OR no_relevant_tools"]

        EXECUTE["**EXECUTE**<br>Tool Executor runs synchronously<br>-- LLM is blocked --<br>resolve_drugs, get_drug_targets,<br>get_gene_pathways, find_paths, etc.<br>Max 30 items per tool, priority fields first"]

        OBSERVE["**OBSERVATION**<br>Narrator LLM (large model)<br>- Evaluates tool outputs<br>- Identifies remaining gaps<br>- Classifies sufficiency"]

        SUFFICIENCY{"Sufficiency<br>status?"}
    end

    UPDATE["Update cumulative_context<br>Append: thought + tool outputs + observation"]
    INCREMENT["Increment iteration counter"]

    MAX_ITER["Max iterations reached<br>Best-effort response"]
    
    FINAL["**Generate Final Response**<br>Narrator synthesizes ALL iterations<br>References ONLY tool outputs"]

    subgraph OUTPUTS ["Three Output Artifacts"]
        direction LR
        O1["Subgraph JSON<br>nodes + edges<br>+ evidence IDs<br>+ scores"]
        O2["Ranked Paths<br>top-K mechanistic<br>paths with<br>provenance"]
        O3["Narrative<br>Summary<br>LLM-generated<br>text"]
    end

    START --> INIT --> CHECK_CONTINUE
    CHECK_CONTINUE -- Yes --> THOUGHT
    CHECK_CONTINUE -- "No (max reached)" --> MAX_ITER --> FINAL

    THOUGHT --> STOP_CHECK
    STOP_CHECK -- "Yes" --> STOP_REASON --> FINAL
    STOP_CHECK -- "No" --> EXECUTE
    EXECUTE --> OBSERVE
    OBSERVE --> SUFFICIENCY

    SUFFICIENCY -- "SUFFICIENT<br>can_answer = true" --> FINAL
    SUFFICIENCY -- "NEEDS_MORE<br>gaps identified" --> UPDATE
    UPDATE --> INCREMENT --> CHECK_CONTINUE

    FINAL --> OUTPUTS
```
