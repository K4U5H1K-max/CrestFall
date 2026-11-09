import unittest

from backend.model import PlaceholderPredictiveRefillModel
from backend.utils import (
    AgentAction,
    InventoryAgent,
    PickerAgent,
    SimulationEngine,
    SimulationState,
    order,
)


class InventoryAgentTests(unittest.TestCase):
    def test_placeholder_predictor_schedules_startup_refill_without_duplicates(self):
        inventory = InventoryAgent(
            "inventory",
            items={"A": 1},
            refill_delay=2,
            predictive_refill_model=PlaceholderPredictiveRefillModel(
                {"A": 3}
            ),
        )

        self.assertEqual(inventory.pending_orders, [
            {"items": {"A": 2}, "ready_at": 2}
        ])
        self.assertEqual(inventory.predictive_refill(), {})
        self.assertEqual(len(inventory.pending_orders), 1)

    def test_engine_connects_predictive_refill_model_at_startup(self):
        inventory = InventoryAgent("inventory", items={"A": 1})
        models = {
            "inventory": inventory.model,
            "predictive_refill": PlaceholderPredictiveRefillModel({"A": 2}),
        }

        SimulationEngine(
            SimulationState(agents=[inventory]),
            models=models,
        )

        self.assertEqual(inventory.pending_orders, [
            {"items": {"A": 1}, "ready_at": 2}
        ])

    def test_refill_completion_runs_next_prediction(self):
        inventory = InventoryAgent(
            "inventory",
            refill_delay=1,
            predictive_refill_model=PlaceholderPredictiveRefillModel(
                {"A": 2}
            ),
        )

        self.assertEqual(inventory.pending_orders, [
            {"items": {"A": 2}, "ready_at": 1}
        ])
        completed = inventory.wait(1)

        self.assertEqual(completed, [{"A": 2}])
        self.assertEqual(inventory.get_inventory(), {"A": 2})
        self.assertEqual(inventory.pending_orders, [])

    def test_observation_exposes_inventory_health_refills_and_waiting_pickers(self):
        inventory = InventoryAgent(
            "inventory",
            items={"A": [0.9]},
            refill_delay=2,
        )
        picker = PickerAgent(
            "picker",
            item_capacity=2,
            neighboring_agents=[inventory],
        )
        order_obj = order(
            "order-1",
            "customer-1",
            {"A": 2},
            "zone-a",
            {"A": 100},
            "picking",
        )
        picker.find_items(order_obj)

        observation = inventory.observe()

        self.assertEqual(observation["inventory"], {"A": 1})
        self.assertEqual(observation["item_inventory"], {"A": [0.9]})
        self.assertEqual(observation["simulation_time"], 0)
        self.assertEqual(
            observation["waiting_pickers"]["A"][0]["quantity"],
            1,
        )
        self.assertIn(
            {
                "action_type": "wait",
                "parameters": {"simulation_time": 1},
            },
            observation["action_mask"],
        )
        self.assertFalse(
            any(
                action["action_type"] == "refill"
                for action in observation["action_mask"]
            )
        )
        self.assertFalse(
            any(
                action["action_type"] == "pick"
                for action in observation["action_mask"]
            )
        )

    def test_wait_action_completes_refill_and_notifies_picker(self):
        inventory = InventoryAgent(
            "inventory",
            refill_delay=2,
        )
        picker = PickerAgent(
            "picker",
            item_capacity=1,
            neighboring_agents=[inventory],
        )
        order_obj = order(
            "order-2",
            "customer-2",
            {"A": 1},
            "zone-b",
            {"A": 100},
            "picking",
        )
        picker.find_items(order_obj)

        first_wait = inventory.execute_action({
            "agent_id": "inventory",
            "action_type": "wait",
            "parameters": {"simulation_time": 1},
        })
        self.assertEqual(first_wait["completed_refills"], [])
        self.assertEqual(inventory.get_inventory(), {})

        second_wait = inventory.execute_action({
            "agent_id": "inventory",
            "action_type": "wait",
            "parameters": {"simulation_time": 1},
        })
        self.assertEqual(second_wait["completed_refills"], [{"A": 1}])
        self.assertEqual(inventory.get_inventory(), {"A": 1})
        self.assertEqual(
            picker.action_queue["order-2"],
            [{"item": "A", "order_id": "order-2"}],
        )

    def test_pick_action_updates_quantity_and_health_stack(self):
        inventory = InventoryAgent(
            "inventory",
            items={"A": [0.9, 0.8]},
        )

        result = inventory.execute_action({
            "agent_id": "inventory",
            "action_type": "pick",
            "parameters": {"items": {"A": 1}},
        })

        self.assertTrue(result["success"])
        self.assertEqual(inventory.get_inventory(), {"A": 1})
        self.assertEqual(inventory.get_item_inventory(), {"A": [0.9]})

    def test_engine_synchronizes_inventory_time(self):
        inventory = InventoryAgent("inventory")
        engine = SimulationEngine(
            SimulationState(agents=[inventory], time=3),
            models={"inventory": inventory.model},
        )

        self.assertEqual(inventory.simulation_time, 3)
        engine.step([
            AgentAction(
                "inventory",
                "wait",
                {"simulation_time": 1},
                3,
            )
        ])

        self.assertEqual(engine.state.time, 4)
        self.assertEqual(inventory.simulation_time, 4)


if __name__ == "__main__":
    unittest.main()
