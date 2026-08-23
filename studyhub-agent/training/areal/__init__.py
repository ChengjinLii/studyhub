"""CPU-testable AReaL adapter skeleton."""

from training.areal.config_schema import AREAL_CONFIG_VERSION, TrainingConfig, load_training_config
from training.areal.grouped_rollout import GroupedEpisode, GroupedEpisodeCoordinator, RolloutRequest, RolloutResult

__all__ = [
    "AREAL_CONFIG_VERSION",
    "GroupedEpisode",
    "GroupedEpisodeCoordinator",
    "RolloutRequest",
    "RolloutResult",
    "TrainingConfig",
    "load_training_config",
]
