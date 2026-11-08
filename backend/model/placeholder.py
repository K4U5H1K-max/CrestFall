class PlaceholderModel:
    """Deterministic policy used until a trained RL model is available."""

    def predict(self, observation, action_mask):
        if not action_mask:
            raise ValueError("No legal actions available")
        wait_action = next(
            (action for action in action_mask if action["action_type"] == "wait"),
            None,
        )
        return wait_action if wait_action is not None else action_mask[0]
