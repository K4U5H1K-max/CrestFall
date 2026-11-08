from .placeholder import PlaceholderModel
from .predictive_refill import PlaceholderPredictiveRefillModel


ROLE_NAMES = (
    "order_management",
    "picker",
    "inventory",
    "packer",
    "dispatch",
    "delivery",
    "return_evaluation",
)


def load_models(model_paths=None):
    """Load one policy object per operational role at simulation startup."""
    del model_paths
    models = {role: PlaceholderModel() for role in ROLE_NAMES}
    models["predictive_refill"] = PlaceholderPredictiveRefillModel()
    return models
