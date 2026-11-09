import unittest

from backend.utils import DeliveryAgent, DispatchAgent, order


class DispatchAgentTests(unittest.TestCase):
    def setUp(self):
        self.delivery = DeliveryAgent("delivery", delivery_capacity=1)
        self.dispatch = DispatchAgent(
            "dispatch",
            delivery_capacity=1,
            neighboring_agents=[self.delivery],
        )

    def test_observation_exposes_routes_and_delivery_capacity(self):
        outbound = {
            "order_id": "order-1",
            "status": "packed",
            "order": order(
                "order-1", "customer", {"A": 1}, "zone", {}, "packed"
            ),
            "items": {"A": [1.0]},
        }
        returned = {
            "order_id": "order-2",
            "order": order(
                "order-2", "customer", {"B": 1}, "zone", {}, "return_requested"
            ),
            "return_request": True,
        }
        self.dispatch.order_queue.extend([outbound, returned])

        observation = self.dispatch.observe()

        self.assertEqual(observation["outbound_queue"], ["order-1"])
        self.assertEqual(observation["return_queue"], ["order-2"])
        self.assertEqual(
            observation["connected_delivery_agents"][0]["capacity_remaining"],
            1,
        )
        self.assertIn(
            {
                "action_type": "assign_delivery",
                "parameters": {"order_id": "order-1"},
            },
            observation["action_mask"],
        )
        self.assertIn(
            {
                "action_type": "assign_return",
                "parameters": {"order_id": "order-2"},
            },
            observation["action_mask"],
        )

    def test_assign_delivery_marks_package_dispatched(self):
        package = {
            "order_id": "order-1",
            "status": "packed",
            "order": order(
                "order-1", "customer", {"A": 1}, "zone", {}, "packed"
            ),
        }
        self.dispatch.order_queue.append(package)

        self.dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_delivery",
            "parameters": {"order_id": "order-1"},
        })

        self.assertEqual(package["status"], "dispatched")
        self.assertEqual(self.dispatch.order_queue, [])
        self.assertEqual(self.delivery.order_queue, [package])

    def test_incomplete_package_is_not_assignable(self):
        package = {
            "order_id": "order-1",
            "status": "accumulating",
            "order": order(
                "order-1", "customer", {"A": 1}, "zone", {}, "packing"
            ),
        }
        self.dispatch.order_queue.append(package)

        with self.assertRaisesRegex(ValueError, "Only packed packages"):
            self.dispatch.execute_action({
                "agent_id": "dispatch",
                "action_type": "assign_delivery",
                "parameters": {"order_id": "order-1"},
            })

        self.assertEqual(self.dispatch.order_queue, [package])

    def test_return_assignment_marks_return_route(self):
        request = {
            "order_id": "order-2",
            "order": order(
                "order-2", "customer", {"A": 1}, "zone", {}, "return_requested"
            ),
            "return_request": True,
        }
        self.dispatch.order_queue.append(request)

        self.dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_return",
            "parameters": {"order_id": "order-2"},
        })

        self.assertEqual(request["status"], "return_assigned")
        self.assertEqual(self.delivery.order_queue, [request])

    def test_route_waits_when_delivery_agent_has_no_capacity(self):
        self.delivery.order_queue.append({"order_id": "existing"})
        package = {"order_id": "order-1", "status": "packed"}
        self.dispatch.order_queue.append(package)

        self.assertFalse(any(
            action["action_type"] == "assign_delivery"
            for action in self.dispatch.available_actions()
        ))
        with self.assertRaisesRegex(ValueError, "No delivery agent"):
            self.dispatch.execute_action({
                "agent_id": "dispatch",
                "action_type": "assign_delivery",
                "parameters": {"order_id": "order-1"},
            })

    def test_duplicate_outbound_route_is_rejected(self):
        package = {
            "order_id": "order-duplicate",
            "status": "packed",
        }
        self.dispatch.order_queue.append(package)
        self.dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_delivery",
            "parameters": {"order_id": "order-duplicate"},
        })

        duplicate = {
            "order_id": "order-duplicate",
            "status": "packed",
        }
        self.dispatch.order_queue.append(duplicate)
        with self.assertRaisesRegex(ValueError, "already been routed"):
            self.dispatch.execute_action({
                "agent_id": "dispatch",
                "action_type": "assign_delivery",
                "parameters": {"order_id": "order-duplicate"},
            })

    def test_duplicate_return_route_is_rejected(self):
        request = {
            "order_id": "return-duplicate",
            "return_request": True,
            "items": {"A": (1, 0.7)},
        }
        self.dispatch.order_queue.append(request)
        self.dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_return",
            "parameters": {"order_id": "return-duplicate"},
        })

        duplicate = {
            "order_id": "return-duplicate",
            "return_request": True,
            "items": {"A": (1, 0.7)},
        }
        self.dispatch.order_queue.append(duplicate)
        with self.assertRaisesRegex(ValueError, "already been routed"):
            self.dispatch.execute_action({
                "agent_id": "dispatch",
                "action_type": "assign_return",
                "parameters": {"order_id": "return-duplicate"},
            })

if __name__ == "__main__":
    unittest.main()
