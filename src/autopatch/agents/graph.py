"""LangGraph agent graph — wires all agents into a stateful pipeline.

Flow:
  monitor → diagnosis → patch → [guardrail] → (commit PR | open issue)
                                     ↓ FAIL
                                 open issue only
"""
from langgraph.graph import END, StateGraph

from src.autopatch.agents.diagnosis import diagnosis_node
from src.autopatch.agents.monitor import monitor_node
from src.autopatch.agents.patch import patch_node
from src.autopatch.agents.verifier import verifier_node
from src.autopatch.guardrails.opa_checker import opa_check
from src.autopatch.guardrails.z3_checker import z3_check
from src.autopatch.models.schemas import AgentGraphState, AgentState, GuardrailVerdict

# ---------------------------------------------------------------------------
# Guardrail node — runs both Z3 and OPA, gates the merge decision
# ---------------------------------------------------------------------------

def guardrail_node(state: AgentGraphState) -> AgentGraphState:
    """Formal guardrail: runs Z3 invariants + OPA policies on the candidate patch."""
    agent_state: AgentState = state["state"]
    patch = agent_state.patch

    if patch is None:
        return {**state, "state": agent_state.model_copy(
            update={"status": "rejected", "guardrail_verdict": GuardrailVerdict(
                passed=False, violations=["No patch was generated"], explanation="Patch Agent produced no output"
            )}
        )}

    z3_result = z3_check(patch)
    opa_result = opa_check(patch)

    all_violations = z3_result.get("violations", []) + opa_result.get("violations", [])
    passed = len(all_violations) == 0

    verdict = GuardrailVerdict(
        passed=passed,
        z3_result=z3_result,
        opa_result=opa_result,
        violations=all_violations,
        explanation="All invariants and policies satisfied." if passed
                    else f"Blocked by {len(all_violations)} violation(s).",
    )
    return {**state, "state": agent_state.model_copy(update={"guardrail_verdict": verdict})}


def _route_after_guardrail(state: AgentGraphState) -> str:
    """Conditional edge: pass → verifier, fail → reject."""
    verdict = state["state"].guardrail_verdict
    return "verifier" if verdict is not None and verdict.passed else END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AgentGraphState)

    graph.add_node("monitor", monitor_node)
    graph.add_node("diagnosis", diagnosis_node)
    graph.add_node("patch", patch_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("verifier", verifier_node)

    graph.set_entry_point("monitor")
    graph.add_edge("monitor", "diagnosis")
    graph.add_edge("diagnosis", "patch")
    graph.add_edge("patch", "guardrail")
    graph.add_conditional_edges("guardrail", _route_after_guardrail, {
        "verifier": "verifier",
        END: END,
    })
    graph.add_edge("verifier", END)

    return graph.compile()
