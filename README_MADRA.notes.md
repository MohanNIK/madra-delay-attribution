# MAD-RA Research Prototype

MAD-RA is a blackboard-mediated and evidence-grounded multi-agent deliberation framework for responsibility attribution in construction delay disputes. It is a research prototype and decision-support tool. It is not an automated adjudication system, legal advice system, or substitute for professional dispute resolution.

## Research Purpose

The prototype supports SCI-style experiments on whether blackboard-mediated multi-role deliberation improves construction delay responsibility attribution beyond single-label prediction. It models:

1. multi-role argumentation,
2. Shared Case Blackboard state management,
3. structured message passing,
4. evidence verification,
5. conflict detection,
6. targeted re-deliberation,
7. convergence into a responsibility result with evidence and management implications.

The contribution should be framed as a evidence-constrained multi-agent responsibility attribution framework, not as merely calling a Qwen API.

## Blackboard Communication Protocol

MAD-RA does not treat agents as free-chat participants. Each agent reads and writes a shared, evidence-indexed case state.

`BlackboardState` contains:

- `case_profile`
- `evidence_registry`
- `claim_ledger`
- `argument_graph`
- `message_pool`
- `verification_records`
- `conflict_graph`
- `consensus_state`
- `revision_history`
- `audit_log`
- `workflow_trace`

Message types are defined in `madra/messages.py`:

- `ClaimMessage`
- `EvidenceMessage`
- `ChallengeMessage`
- `RebuttalMessage`
- `ConcessionMessage`
- `VerificationMessage`
- `CoordinatorFeedback`

Every message contains:

- `message_id`
- `round_id`
- `sender`
- `receiver`
- `claim_id`
- `evidence_ids`
- `message_type`
- `content`
- `confidence`
- `required_action`

The BPMN-style workflow trace records `task_started -> agent_argument_submitted -> evidence_verified -> conflict_detected -> feedback_posted -> re_deliberation_completed -> final_output_generated`. The trace is not a visual-only flowchart; it is serialized in prediction outputs and can be exported as `audit_log.jsonl`.

## Algorithm Workflow

Input is a `CaseRecord` JSON object with stable evidence span IDs. MAD-RA retrieves relevant evidence, runs role agents, computes disagreement, and repeats deliberation until:

- `disagreement_score <= tau` and `consensus_score >= gamma`, or
- the maximum number of rounds is reached.

Default full mode uses:

- `owner_agent`
- `contractor_agent`
- `delay_analysis_agent`
- `contract_rule_agent`
- `evidence_verification_agent`
- deterministic coordination and convergence metrics

The disagreement score is a weighted composite:

- label disagreement
- allocation disagreement
- evidence citation disagreement
- unsupported-claim rate

Default pilot weights are configurable in `madra.metrics.composite_disagreement`; they should be reported as pilot settings and checked in sensitivity analysis. The stop condition requires disagreement, unsupported-claim rate, and consensus thresholds.

## Input Schema

Dataset format is JSONL, one `CaseRecord` per line:

```json
{
  "case_id": "SYN-001",
  "project_type": "commercial building",
  "dispute_type": "delay responsibility",
  "parties": {"owner": "Employer", "contractor": "Main contractor"},
  "facts": ["The owner issued a late design change."],
  "claims": ["The contractor claimed extension of time."],
  "evidence_spans": [
    {"span_id": "E1", "text": "The owner issued a late design change.", "source": "judgment"}
  ],
  "reasoning_spans": [
    {"span_id": "E1", "text": "The tribunal accepted the owner-side delay.", "source": "reasoning"}
  ],
  "final_decision": "Shared responsibility.",
  "liability_label": "shared_responsibility",
  "allocation_ground_truth": {"owner": 60, "contractor": 40}
}
```

Evidence IDs must be stable because evidence precision, evidence recall, and Hit@k are computed over `evidence_ids`.

## Agent Output Schema

Every role agent must return strict JSON:

```json
{
  "agent_role": "owner_agent",
  "liability_label": "shared_responsibility",
  "allocation": {"owner": 60, "contractor": 40},
  "key_claims": ["Owner design change contributed to delay."],
  "evidence_ids": ["E1"],
  "reasoning_steps": ["E1 records the design change."],
  "uncertainty": 0.2,
  "unsupported_claims": []
}
```

Malformed or incomplete JSON is retried up to two times. If the response still fails validation, `SchemaValidationError` reports the role, missing fields, and raw response excerpt.

## Final Output Schema

Predictions include:

- `liability_label`
- `allocation`
- `key_claims`
- `evidence_ids`
- `consensus_score`
- `disagreement_score`
- `unsupported_claim_rate`
- `conflict_points`
- `management_implications`
- full `rounds` history
- `audit_log`
- `blackboard_state`

`management_implications` contains:

- `key_risk_points`
- `evidence_preparation_suggestions`
- `claim_negotiation_focus`
- `preventive_actions`

These fields are intended for project decision support and dispute prevention, not automatic adjudication.

## Qwen/DashScope Setup

The client uses Qwen/DashScope OpenAI-compatible mode by default:

```powershell
$env:DASHSCOPE_API_KEY="your-key"
$env:DASHSCOPE_MODEL="qwen-plus"
```

Default base URL:

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

You can also set `DASHSCOPE_BASE_URL`, `QWEN_BASE_URL`, or `OPENAI_BASE_URL` for other compatible endpoints.

## Run Commands

Mock single case:

```powershell
python run_madra.py --dataset examples/dataset.sample.jsonl --output out_case.json --mock
```

Qwen single case:

```powershell
python run_madra.py --dataset examples/dataset.sample.jsonl --output out_case.json --model qwen-plus
```

Mock batch experiment:

```powershell
python run_experiment.py --dataset examples/dataset.sample.jsonl --output predictions.jsonl --mock --num-runs 3 --seed 7
```

Evaluate:

```powershell
python evaluate_results.py --dataset examples/dataset.sample.jsonl --predictions predictions.jsonl --hit-k 2
```

Ablation:

```powershell
python run_ablation.py --dataset examples/dataset.sample.jsonl --output-dir ablation_out --mock
```

Prepare the 500-case SCI pilot dataset from the local structured case files:

```powershell
python prepare_pilot_dataset.py --output-dir outputs/pilot_500 --limit 500 --human-checked-size 50
```

Run the staged pilot workflow. Use `--skip-api` for Stage 1 only; omit it to run Stage 2 Qwen calibration and Stage 3 formal 500-case pilot:

```powershell
python run_pilot_study.py --output-dir outputs/pilot_500 --limit 500 --skip-api
python run_pilot_study.py --output-dir outputs/pilot_500 --limit 500 --model qwen-plus
```

The staged workflow is:

- Stage 1: mock 10 cases for schema, evidence ID, JSONL, and plotting-data checks.
- Stage 2: Qwen API calibration on 30 cases for JSON validity, schema compliance, evidence grounding, retry rate, unsupported claim rate, and prompt robustness.
- Stage 3: formal 500-case pilot for the Results section.

Generate engineering informatics style editable SVG figures:

```powershell
python generate_engineering_figures.py --output-dir outputs/pilot_500/figures
```

Build the IEEE TEM manuscript, figures, audit files, and rerun manifest from the current 500-case dataset:

```powershell
python run_tem_harness.py --dataset outputs/pilot_500/dataset_madra_500.jsonl --output-dir outputs/ieee_tem_harness
```

The harness writes:

- `IEEE_TEM_MADRA_full_draft.md`
- `IEEE_TEM_MADRA_full_draft.docx`
- `dataset_profile_500.json`
- `manuscript_audit.json`
- `figure_contract.md`
- `figure_prompts.md`
- `ppt_absorption_checklist.md`
- `rerun_update_manifest.md`
- `figures/*.svg`, `figures/*.pdf`, `figures/*.png`, and `figures/*.tiff`

If the formal 500-case API results are not present, the manuscript keeps
`[FORMAL_500_RESULTS_TO_BE_UPDATED]` markers and does not claim model superiority.
After `metrics_500.json`, `token_usage_500.json`, and `runtime_500.json` are generated,
rerun the same harness command to refresh the Results section and figures.

Supported modes:

- `full`
- `no_evidence_verification`
- `no_coordination`
- `single_round`
- `single_agent`
- `single_agent_same_context`
- `single_agent_long_prompt`
- `rag_only`
- `no_blackboard`
- `multi_agent_without_blackboard`
- `multi_agent_direct_message_only`
- `all_agent_fixed_rounds`

## Evaluation Metrics

`evaluate_results.py` reports:

- Accuracy
- Macro-F1
- per-class F1
- Evidence Precision
- Evidence Recall
- Hit@k
- unsupported claim rate
- unsupported claim rate std
- label consistency
- allocation variance
- evidence chain overlap
- consensus score mean/std

SCI pilot reporting groups metrics into four families:

1. Responsibility attribution performance: Accuracy, Macro-F1, per-class F1.
2. Evidence grounding quality: Evidence Precision, Evidence Recall, Hit@k, unsupported-claim rate, evidence-chain overlap.
3. Deliberation behavior: number of rounds, disagreement reduction, consensus score, conflict resolution rate, stop-condition satisfaction rate.
4. Practical usability: runtime, token cost, human usefulness rating, evidence-preparation usefulness, negotiation-focus usefulness.

The pilot workflow also writes:

- `cost_500.json`
- `runtime_500.json`
- `token_usage_500.json`

These files report average tokens per case, average running time per case, average API cost per case if `MADRA_COST_PER_1K_TOKENS` is set, successful JSON rate, retry rate, and malformed output rate.

For stability tests, run with `--num-runs`, `--seed`, and `--temperature`.

## Ablation Design

The ablation script isolates whether improvements come from deliberation rather than longer prompts:

- remove evidence verification,
- remove coordination,
- force a single deliberation round,
- use a single-agent baseline,
- use a single-agent baseline with comparable evidence context,
- use a long-prompt single-agent baseline to control for prompt length,
- use a RAG-only baseline.

These modes support RQ-style analysis:

- RQ1: Does multi-agent deliberation improve responsibility attribution?
- RQ2: Does evidence verification improve explanation quality?
- RQ3: Does coordination reduce contradiction and improve stability?
- RQ4: Do management implications support claim preparation and dispute prevention?

## Reproducibility Notes

- Standard library only.
- Mock mode is deterministic and does not require API access.
- Qwen mode reads `DASHSCOPE_API_KEY`.
- Temperature defaults to `0.0`.
- Dataset rows must preserve evidence IDs.
- Local files named `gold500_v1.csv` or `candidate_gold_*` are mapped only into `candidate_labels` / `weak_labels`; manuscript text should describe them as machine-assisted candidate labels or weak-supervised labels, not as a fully human-validated benchmark.
- `human_checked_50.jsonl` is a small-scale validation subset for liability label, allocation, evidence span, unsupported claims, and explanation quality.
- The current retriever is keyword-based. It can be replaced by BM25, pgvector, FAISS, or a legal-case search service without changing the dataset schema.

## Limitations

MAD-RA does not make binding responsibility determinations by itself. It structures evidence-grounded responsibility reasoning for research and decision support. Results depend on dataset quality, label consistency, jurisdiction, contract terms, evidence completeness, and LLM reliability. Claims without valid evidence IDs are treated as unsupported and should not be used for final attribution.

For SCI pilot reporting, state explicitly that candidate labels have not completed full human validation. The multi-agent design increases token cost and runtime, so any performance claim should be justified by improved evidence grounding, stability, and interpretability rather than accuracy alone.
