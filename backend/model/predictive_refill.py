class PlaceholderPredictiveRefillModel:
    """Deterministic refill forecaster used until a trained model is available."""

    def __init__(self, target_stock=None):
        self.target_stock = {} if target_stock is None else dict(target_stock)

    def forecast(self, observation):
        del observation
        return dict(self.target_stock)
