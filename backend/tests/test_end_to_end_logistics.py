import unittest

from backend.utils import (
    AgentAction,
    CustomerAgent,
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


class EndToEndLogisticsTests(unittest.TestCase):
    def setUp(self):
        self.inventory = InventoryAgent("inventory", items={"A": [0.9]})
        self.returns = ReturnEvaluationAgent(
            "returns", neighboring_agents=[self.inventory]
        )
        self.delivery = DeliveryAgent(
            "delivery", 1, neighboring_agents=[self.returns]
        )
        self.dispatch = DispatchAgent(
            "dispatch", 1, neighboring_agents=[self.delivery]
        )
        self.packer = PackerAgent(
            "packer", 1, neighboring_agents=[self.dispatch]
        )
        self.picker = PickerAgent(
            "picker",
            1,
            neighboring_agents=[self.inventory, self.packer],
            state="wait",
        )
        self.manager = OrderManagementAgent(
            "orders", neighboring_agents=[self.picker, self.dispatch]
        )
        self.customer = CustomerAgent(
            "customer", neighboring_agents=[self.manager]
        )
        self.engine = SimulationEngine(
            SimulationState(
                agents=[
                    self.manager,
                    self.picker,
                    self.packer,
                    self.dispatch,
                    self.delivery,
                    self.returns,
                    self.inventory,
                    self.customer,
                ]
            ),
            models={},
        )

    def _step(self, agent_id, action_type, parameters=None):
        timestep = self.engine.state.time
        return self.engine.step([
            AgentAction(
                agent_id,
                action_type,
                {} if parameters is None else parameters,
                timestep,
            )
        ])

    def _complete_forward_delivery(self, order_obj):
        actions = [
            ("orders", "release_order", {"order_id": order_obj.order_id}),
            ("picker", "find_items", {"order_id": order_obj.order_id}),
            (
                "picker",
                "pick",
                {"order_id": order_obj.order_id, "item": "A"},
            ),
            (
                "picker",
                "move_to_packer",
                {"order_id": order_obj.order_id},
            ),
            (
                "packer",
                "accept_package",
                {"order_id": order_obj.order_id},
            ),
            (
                "packer",
                "move_to_dispatch",
                {"order_id": order_obj.order_id},
            ),
            (
                "dispatch",
                "assign_delivery",
                {"order_id": order_obj.order_id},
            ),
            (
                "delivery",
                "accept_delivery",
                {"order_id": order_obj.order_id},
            ),
            ("delivery", "travel_to_customer", {"duration": 1}),
            ("delivery", "wait", {}),
            ("delivery", "deliver_order", {}),
        ]
        for agent_id, action_type, parameters in actions:
            self._step(agent_id, action_type, parameters)

    def test_customer_actions_run_as_engine_transitions(self):
        request = orderRequest("customer", "customer", {"A": 1}, "zone-a")
        self.customer.order_requests.append(request)
        self.customer.pending_requests.append(request)

        transitions = self._step(
            "customer",
            "submit_order",
            {"order_request": request},
        )

        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].result["action"], "submit_order")
        self.assertEqual(len(self.manager.order_queue), 1)
        self.assertEqual(
            self.customer.observe()["action_mask"],
            [{"action_type": "wait", "parameters": {}}],
        )

    def test_customer_forward_and_reverse_logistics(self):
        created = self.customer.place_order_request(
            orderRequest("customer", "customer", {"A": 1}, "zone-a")
        )
        self._complete_forward_delivery(created)

        self.customer.receive_order(created)
        self.assertEqual(created.status, "completed")
        self.assertEqual(self.inventory.get_inventory(), {"A": 0})

        self.assertTrue(self.customer.return_items({"A": (1, 0.72)}))
        self._step(
            "dispatch",
            "assign_return",
            {"order_id": created.order_id},
        )
        self._step(
            "delivery",
            "accept_delivery",
            {"order_id": created.order_id},
        )
        self._step("delivery", "travel_to_customer", {"duration": 1})
        self._step("delivery", "wait")
        self._step("delivery", "deliver_order")
        self._step(
            "returns",
            "evaluate_return",
            {"order_id": created.order_id},
        )

        self.assertEqual(created.status, "returned")
        self.assertEqual(self.inventory.get_item_inventory(), {"A": [0.72]})

    def test_customer_cannot_return_an_order_before_delivery(self):
        created = self.customer.place_order_request(
            orderRequest("customer", "customer", {"A": 1}, "zone-a")
        )

        with self.assertRaisesRegex(ValueError, "completed order"):
            self.customer.return_items(order_id=created.order_id)

    def test_customer_cannot_submit_invalid_order_or_duplicate_return(self):
        with self.assertRaises(TypeError):
            self.customer.place_order_request({"A": 1})

        created = self.customer.place_order_request(
            orderRequest("customer", "customer", {"A": 1}, "zone-a")
        )
        self._complete_forward_delivery(created)
        self.customer.receive_order(created)
        self.assertTrue(self.customer.return_items())

        with self.assertRaisesRegex(ValueError, "completed order"):
            self.customer.return_items()


if __name__ == "__main__":
    unittest.main()
