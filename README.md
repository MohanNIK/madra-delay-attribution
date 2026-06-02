# madra-delay-attribution

`madra-delay-attribution` is the multi-agent responsibility-attribution layer for construction delay disputes. It models blackboard-mediated deliberation, evidence verification, disagreement tracking, and structured convergence into a responsibility-oriented result.

## Scope

- Shared blackboard state for case evidence and claims
- Multi-role agent protocol for owner/contractor/delay-analysis reasoning
- Mock and live LLM execution paths
- Offline tests and example JSONL case inputs

## Repository Layout

- `madra/`: package source for protocol, models, metrics, and coordination
- `examples/`: sample JSONL case data
- `tests/`: research and smoke-oriented tests
- `run_madra.py`: single-case runner
- `run_experiment.py`: batch experiment entrypoint
- `evaluate_results.py`: metrics and evidence-overlap evaluation
- `run_pilot_study.py`: staged pilot helper

## Quick Start

```powershell
python smoke_test.py
python run_madra.py --dataset examples/dataset.sample.jsonl --output examples/mock_result.json --mock
python -m unittest tests.test_madra_research_prototype
```

The default smoke path uses `MockLLM` and does not call an external API.

## Notes

- This public snapshot excludes raw case corpora, manuscript drafts, and intermediate rendering artifacts.
- Live endpoint usage requires `DASHSCOPE_API_KEY` or `QWEN_API_KEY`.
- This repo is the argumentation / attribution layer and is designed to complement `delay-dispute-leap`.
