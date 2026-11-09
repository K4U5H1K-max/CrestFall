import unittest

from backend.utils import (
    DispatchAgent,
    DeliveryAgent,
    InventoryAgent,
    OrderManagementAgent,
    PickerAgent,
    ReturnEvaluationAgent,
    orderRequest,
)


class OrderManagementAgentTests(unittest.TestCase):
    def test_order_request_is_queued_with_default_priority(self):
        manager = OrderManagementAgent("orders")
        request = orderRequest(
            "order-customer",
            "customer",
            {"A": 1},
            "zone-a",
        )

        created = manager.process_order_request(request)

        self.assertIn(created, manager.order_queue)
        self.assertEqual(created.status, "pending")
        self.assertEqual(created.priority, 0)
        self.assertIn(
            {
                "action_type": "release_order",
                "parameters": {"order_id": created.order_id},
            },
            manager.available_actions(),
        )

    def test_release_waits_for_picker_and_then_assigns_order(self):
        picker = PickerAgent("picker", item_capacity=1, state="wait")
        manager = OrderManagementAgent(
            "orders",
            neighboring_agents=[picker],
        )
        created = manager.process_order_request(
            orderRequest("request-1", "customer", {"A": 1}, "zone-a")
        )

        result = manager.execute_action({
            "agent_id": "orders",
            "action_type": "release_order",
            "parameters": {"order_id": created.order_id},
        })

        self.assertTrue(result["success"])
        self.assertEqual(created.status, "picking")
        self.assertEqual(picker.order_queue, [created])
        self.assertEqual(manager.order_queue, [])

    def test_return_request_is_routed_to_dispatch(self):
        return_evaluation = ReturnEvaluationAgent(
            "returns",
            neighboring_agents=[InventoryAgent("inventory")],
        )
        delivery = DeliveryAgent(
            "delivery",
            delivery_capacity=1,
            neighboring_agents=[return_evaluation],
        )
        dispatch = DispatchAgent(
            "dispatch",
            delivery_capacity=1,
            neighboring_agents=[delivery],
        )
        manager = OrderManagementAgent(
            "orders",
            neighboring_agents=[dispatch],
        )
        created = manager.process_order_request(
            orderRequest("request-2", "customer", {"A": 1}, "zone-a")
        )
        created.status = "completed"

        returned_items = {"A": (1, 0.72)}
        result = manager.accept_return_request(created, returned_items)

        self.assertTrue(result)
        self.assertEqual(created.status, "return_requested")
        self.assertEqual(dispatch.order_queue[0]["order"], created)
        self.assertTrue(dispatch.order_queue[0]["return_request"])
        self.assertEqual(dispatch.order_queue[0]["items"], returned_items)

        dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_return",
            "parameters": {"order_id": created.order_id},
        })
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "accept_delivery",
            "parameters": {"order_id": created.order_id},
        })
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "travel_to_customer",
            "parameters": {"duration": 1},
        })
        delivery.wait()
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "deliver_order",
            "parameters": {},
        })
        return_evaluation.execute_action({
            "agent_id": "returns",
            "action_type": "evaluate_return",
            "parameters": {"order_id": created.order_id},
        })

        self.assertEqual(created.status, "returned")
        self.assertEqual(
            return_evaluation.neighboring_agents[0].get_inventory(),
            {"A": 1},
        )
        self.assertEqual(
            return_evaluation.neighboring_agents[0].get_item_inventory(),
            {"A": [0.72]},
        )


if __name__ == "__main__":
    unittest.main()
