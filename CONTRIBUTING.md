# Contributing

MADRA is published as a compact research framework focused on explainable multi-agent responsibility attribution. Contributions should keep the public package easy to run and easy to inspect.

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python smoke_test.py
python -m unittest tests.test_madra_research_prototype
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Contribution Rules

- Keep examples small and public-safe.
- Avoid machine-specific paths and private source documents.
- Prefer changes that improve clarity, tests, or reproducibility.

## Pull Request Checklist

- [ ] Smoke test passes
- [ ] Core unit test passes
- [ ] Docs updated if behavior changed
- [ ] No credentials or sensitive text added
