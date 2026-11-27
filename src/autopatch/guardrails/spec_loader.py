"""Loads YAML agent contract specs from specs/agents/.

The YAML contracts are the single source of truth for agent requirements.
Z3 and OPA rules are derived from them at runtime.
"""
from functools import lru_cache
from pathlib import Path

import yaml

SPECS_DIR = Path(__file__).parents[3] / "specs" / "agents"


@lru_cache(maxsize=10)
def load_agent_spec(agent_name: str) -> dict:
    """Load and cache a YAML agent contract by name (e.g. 'patch_agent')."""
    spec_path = SPECS_DIR / f"{agent_name}.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"Agent spec not found: {spec_path}")
    with open(spec_path) as f:
        return yaml.safe_load(f)


def get_all_specs() -> dict[str, dict]:
    """Load all agent specs — useful for dashboard / introspection."""
    return {
        p.stem: load_agent_spec(p.stem)
        for p in SPECS_DIR.glob("*.yaml")
    }
