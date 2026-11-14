"""Modello neurale locale per candidati di restauro High."""

from .engine import MAX_GAP_MS, MIN_GAP_MS, MIN_SIDE_MS, inpaint
from .registry import MODEL_ID, install_model, list_models, model_for_stem, model_limits, verify_model

__all__ = ["MODEL_ID", "MIN_GAP_MS", "MAX_GAP_MS", "MIN_SIDE_MS", "inpaint",
           "install_model", "list_models", "model_for_stem", "model_limits", "verify_model"]
