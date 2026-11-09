import unittest

from backend.utils import (
    AgentAction,
    DeliveryAgent,
    DispatchAgent,
    InventoryAgent,
    OrderManagementAgent,
    PackerAgent,
    PickerAgent,
    ReturnEvaluationAgent,
    SimulationEngine,
    SimulationState,
    orderRequest,
)


class SimulationEngineWorkflowTests(unittest.TestCase):
    def test_forward_workflow_runs_through_engine(self):
        inventory = InventoryAgent("inventory", items={"A": [0.9]})
        picker = PickerAgent(
            "picker", 1, neighboring_agents=[inventory], state="wait"
        )
        packer = PackerAgent("packer", 1)
        dispatch = DispatchAgent("dispatch", 1)
        delivery = DeliveryAgent("delivery", 1)
        picker.neighboring_agents.append(packer)
        packer.neighboring_agents = [dispatch]
        dispatch.neighboring_agents = [delivery]
        manager = OrderManagementAgent("orders", neighboring_agents=[picker])
        request = orderRequest("customer", "customer", {"A": 1}, "zone")
        created = manager.process_order_request(request)
        engine = SimulationEngine(
            SimulationState(agents=[
                manager, picker, packer, dispatch, delivery, inventory
            ])
        )

        actions = [
            AgentAction("orders", "release_order", {"order_id": created.order_id}, 0),
            AgentAction("picker", "find_items", {"order_id": created.order_id}, 1),
            AgentAction("picker", "pick", {"order_id": created.order_id, "item": "A"}, 2),
            AgentAction("picker", "move_to_packer", {"order_id": created.order_id}, 3),
            AgentAction("packer", "accept_package", {"order_id": created.order_id}, 4),
            AgentAction("packer", "move_to_dispatch", {"order_id": created.order_id}, 5),
            AgentAction("dispatch", "assign_delivery", {"order_id": created.order_id}, 6),
            AgentAction("delivery", "accept_delivery", {"order_id": created.order_id}, 7),
            AgentAction("delivery", "travel_to_customer", {"duration": 1}, 8),
            AgentAction("delivery", "wait", {}, 9),
            AgentAction("delivery", "deliver_order", {}, 10),
        ]
        for action in actions:
            engine.step([action])

        self.assertEqual(created.status, "completed")
        self.assertEqual(inventory.get_inventory(), {"A": 0})

    def test_reverse_workflow_runs_through_engine(self):
        inventory = InventoryAgent("inventory")
        returns = ReturnEvaluationAgent(
            "returns", neighboring_agents=[inventory]
        )
        delivery = DeliveryAgent(
            "delivery", 1, neighboring_agents=[returns]
        )
        dispatch = DispatchAgent(
            "dispatch", 1, neighboring_agents=[delivery]
        )
        manager = OrderManagementAgent(
            "orders", neighboring_agents=[dispatch]
        )
        created = manager.process_order_request(
            orderRequest("customer", "customer", {"A": 1}, "zone")
        )
        created.status = "completed"
        manager.accept_return_request(created, {"A": (1, 0.72)})
        engine = SimulationEngine(
            SimulationState(agents=[dispatch, delivery, returns, inventory])
        )

        for action in [
            AgentAction("dispatch", "assign_return", {"order_id": created.order_id}, 0),
            AgentAction("delivery", "accept_delivery", {"order_id": created.order_id}, 1),
            AgentAction("delivery", "travel_to_customer", {"duration": 1}, 2),
            AgentAction("delivery", "wait", {}, 3),
            AgentAction("delivery", "deliver_order", {}, 4),
            AgentAction("returns", "evaluate_return", {"order_id": created.order_id}, 5),
        ]:
            engine.step([action])

        self.assertEqual(created.status, "returned")
        self.assertEqual(inventory.get_item_inventory(), {"A": [0.72]})


if __name__ == "__main__":
    unittest.main()
