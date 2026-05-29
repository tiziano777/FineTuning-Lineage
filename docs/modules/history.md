# history/ Module — Experiment History Navigation

## Overview

Navigate experiment history (forward/back through lineage chain), rollback to prior states, and squash consecutive experiments into one.

**Location:** `graph_lineage/history/`

## Public API

```python
from graph_lineage.history import (
    ExperimentRepository,
    navigate,      # Move to next/prev in chain
    rollback,      # Revert to prior state
    squash,        # Merge N experiments
)
```

## Key Classes

### ExperimentRepository
```python
class ExperimentRepository:
    async def navigate(exp_id: str, direction: str) -> NavigationResult
        """Move forward/backward in lineage chain."""
        # direction: "next" | "prev"
        # Returns: next_exp_id, strategy, changed_files

    async def rollback(from_id: str, to_id: str) -> RollbackPreview
        """Preview rollback (show what would change)."""
        # Requires confirmation before committing

    async def squash(exp_ids: list[str]) -> SquashResult
        """Merge N consecutive experiments into base + final diff."""
```

---

## Use Cases

**Navigate lineage:**
- Show user experiment history UI
- Trace where a bug was introduced (walk backward)

**Rollback:**
- "My last 3 runs failed, take me back to the working state"
- Uses diff reconstruction to recover codebase

**Squash:**
- "I had 10 tiny experiments, merge them into 1 for storage"
- Reduces redundant diffs

---

## Testing

Location: `tests/test_history.py`

---

## See Also

- [diff.md](diff.md) — Reconstruction logic used by rollback
- [lineage.md](lineage.md) — How experiments are created

