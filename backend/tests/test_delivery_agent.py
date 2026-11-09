import unittest

from backend.utils import (
    DeliveryAgent,
    ReturnEvaluationAgent,
    order,
)


class DeliveryAgentTests(unittest.TestCase):
    def test_outbound_delivery_uses_wait_and_on_route_states(self):
        delivery = DeliveryAgent("delivery", 1)
        package = {
            "order_id": "order-1",
            "order": order(
                "order-1", "customer", {"A": 1}, "zone", {}, "packed"
            ),
            "status": "dispatched",
            "route_type": "outbound",
        }
        delivery.deliver_packages([package])

        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "accept_delivery",
            "parameters": {"order_id": "order-1"},
        })
        self.assertEqual(delivery.state, "on-route")
        self.assertEqual(package["status"], "in_transit")

        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "travel_to_customer",
            "parameters": {"duration": 2},
        })
        self.assertEqual(delivery.state, "on-route")
        with self.assertRaisesRegex(ValueError, "already started"):
            delivery.execute_action({
                "agent_id": "delivery",
                "action_type": "travel_to_customer",
                "parameters": {"duration": 1},
            })

        delivery.wait()
        delivery.wait()
        self.assertEqual(delivery.state, "on-route")
        self.assertIn(
            {
                "action_type": "deliver_order",
                "parameters": {},
            },
            delivery.available_actions(),
        )

        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "deliver_order",
            "parameters": {},
        })
        self.assertEqual(delivery.state, "wait")
        self.assertEqual(package["status"], "delivered")

    def test_delivery_cannot_finish_before_travel_starts_or_ends(self):
        delivery = DeliveryAgent("delivery", 1)
        package = {"order_id": "order-2", "status": "dispatched"}
        delivery.deliver_packages([package])
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "accept_delivery",
            "parameters": {"order_id": "order-2"},
        })

        with self.assertRaisesRegex(ValueError, "has not started"):
            delivery.execute_action({
                "agent_id": "delivery",
                "action_type": "deliver_order",
                "parameters": {},
            })

        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "travel_to_customer",
            "parameters": {"duration": 1},
        })
        with self.assertRaisesRegex(ValueError, "not reached"):
            delivery.execute_action({
                "agent_id": "delivery",
                "action_type": "deliver_order",
                "parameters": {},
            })

    def test_return_delivery_updates_metadata_and_routes_to_evaluation(self):
        returns = ReturnEvaluationAgent("returns")
        delivery = DeliveryAgent(
            "delivery", 1, neighboring_agents=[returns]
        )
        package = {
            "order_id": "return-1",
            "status": "return_assigned",
            "return_request": True,
            "route_type": "return",
        }
        delivery.deliver_packages([package])
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "accept_delivery",
            "parameters": {"order_id": "return-1"},
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

        self.assertEqual(package["status"], "return_delivered")
        self.assertEqual(delivery.state, "wait")
        self.assertEqual(returns.order_queue, [package])


if __name__ == "__main__":
    unittest.main()
