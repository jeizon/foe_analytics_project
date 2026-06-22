"""Universal game-state capture module."""

from modules.game_state.classifier import classify_service
from modules.game_state.mapper import GameStateMapping, map_game_state_event

__all__ = ["GameStateMapping", "classify_service", "map_game_state_event"]
