"""Offline evaluation and training adapters for Web-enabled DeepResearch."""

from .dataset import build_web_router_eval_cases
from .policy import DeterministicWebRouterPolicy
from .spec import WebRouterEvalCase, evaluate_predictions, gate_evaluation

__all__ = [
    "DeterministicWebRouterPolicy",
    "WebRouterEvalCase",
    "build_web_router_eval_cases",
    "evaluate_predictions",
    "gate_evaluation",
]
