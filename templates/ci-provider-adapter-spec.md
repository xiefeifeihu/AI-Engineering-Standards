# CI Provider Adapter Interface Specification (STD-032 / STD-034)

## 1. Overview
The CI Provider Adapter (`scripts/release/ci_provider_adapter.py`) abstracts the execution environment, supporting:
1. `local_runner`: Workstation or server local execution (WSL2, Linux, Windows native).
2. `github_actions`: GitHub Actions hosted runner execution with structured annotations (`::group::`, `::notice`, `::error`).

## 2. Core Method Signatures

```python
class CIProviderAdapter:
    def __init__(self, provider: str | None = None, repo_root: Path | None = None) -> None: ...
    def get_ci_metadata(self) -> Dict[str, Any]: ...
    def emit_stage_start(self, stage: str) -> None: ...
    def emit_stage_end(self, stage: str, passed: bool, detail: str = "") -> None: ...
    def run_stages(
        self,
        stage_handlers: Dict[str, Callable[[], Dict[str, Any]]],
        stages: List[str] | None = None,
        fail_closed: bool = True,
    ) -> Dict[str, Any]: ...
```

## 3. Mandatory Fail-Closed Contract
If `fail_closed=True` (default), when any mandatory stage fails (`passed=False` or `status in ("FAIL", "BLOCK")`):
- Execution of subsequent stages MUST immediately cease.
- Subsequent stages MUST be marked `SKIPPED` with explanation.
- Destructive stages like `DEPLOY` MUST NEVER execute following an upstream gate failure.
