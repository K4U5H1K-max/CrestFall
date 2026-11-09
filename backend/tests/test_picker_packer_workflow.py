import unittest

from backend.utils import (
    DeliveryAgent,
    DispatchAgent,
    InventoryAgent,
    PackerAgent,
    PickerAgent,
    order,
)


class PickerPackerWorkflowTests(unittest.TestCase):
    def test_packer_observation_and_mask_reflect_package_state(self):
        dispatch = DispatchAgent("dispatch-observe", delivery_capacity=1)
        packer = PackerAgent(
            "packer-observe",
            package_capacity=1,
            neighboring_agents=[dispatch],
        )
        order_obj = order(
            "order-observe",
            "customer",
            {"A": 2},
            "zone",
            {"A": 100},
            "picking",
        )
        packer.order_queue.append({
            "order_id": order_obj.order_id,
            "order": order_obj,
            "items": {"A": [0.8]},
        })

        observation = packer.observe()

        self.assertEqual(observation["incoming_packages"][0]["order_id"], "order-observe")
        self.assertEqual(observation["dispatch_available"], True)
        self.assertIn(
            {
                "action_type": "accept_package",
                "parameters": {"order_id": "order-observe"},
            },
            observation["action_mask"],
        )

        packer.execute_action({
            "agent_id": "packer-observe",
            "action_type": "accept_package",
            "parameters": {"order_id": "order-observe"},
        })
        self.assertEqual(packer.packages[0]["status"], "accumulating")
        self.assertFalse(any(
            action["action_type"] == "move_to_dispatch"
            for action in packer.available_actions()
        ))
        self.assertEqual(
            packer.observe()["packages"][0]["remaining_items"],
            {"A": 1},
        )

    def test_packer_rejects_incomplete_dispatch_and_preserves_package(self):
        dispatch = DispatchAgent("dispatch-incomplete", delivery_capacity=1)
        packer = PackerAgent(
            "packer-incomplete",
            package_capacity=1,
            neighboring_agents=[dispatch],
        )
        order_obj = order(
            "order-incomplete",
            "customer",
            {"A": 2},
            "zone",
            {"A": 100},
            "picking",
        )
        package = {
            "order_id": order_obj.order_id,
            "order": order_obj,
            "items": {"A": [0.8]},
        }
        packer.order_queue.append(package)
        packer.execute_action({
            "agent_id": "packer-incomplete",
            "action_type": "accept_package",
            "parameters": {"order_id": "order-incomplete"},
        })

        with self.assertRaisesRegex(ValueError, "Only packed packages"):
            packer.execute_action({
                "agent_id": "packer-incomplete",
                "action_type": "move_to_dispatch",
                "parameters": {"order_id": "order-incomplete"},
            })

        self.assertEqual(len(packer.packages), 1)
        self.assertEqual(len(dispatch.order_queue), 0)

    def test_packer_capacity_rejection_does_not_remove_incoming_package(self):
        packer = PackerAgent("packer-capacity", package_capacity=1)
        first_order = order("order-first", "customer", {"A": 1}, "zone", {}, "picking")
        second_order = order("order-second", "customer", {"B": 1}, "zone", {}, "picking")
        packer.pack_items({
            "order_id": first_order.order_id,
            "order": first_order,
            "items": {"A": [1.0]},
        })
        packer.order_queue.append({
            "order_id": second_order.order_id,
            "order": second_order,
            "items": {"B": [1.0]},
        })

        with self.assertRaisesRegex(ValueError, "capacity"):
            packer.execute_action({
                "agent_id": "packer-capacity",
                "action_type": "accept_package",
                "parameters": {"order_id": "order-second"},
            })

        self.assertEqual(len(packer.order_queue), 1)

    def test_picker_unloads_multiple_trips_and_packer_accumulates(self):
        inventory = InventoryAgent("inventory", items={"A": 3})
        packer = PackerAgent("packer", package_capacity=1)
        order_obj = order(
            "order-1",
            "customer-1",
            {"A": 3},
            "zone-a",
            {"A": 100},
            "picking",
        )
        picker = PickerAgent(
            "picker",
            item_capacity=2,
            order_queue=[order_obj],
            neighboring_agents=[inventory, packer],
        )

        picker.find_items(order_obj)
        picker.process_next_action()
        picker.process_next_action()
        self.assertEqual(picker._carried_quantity(), 2)

        picker.unload_to_packer(order_obj)
        self.assertEqual(order_obj.status, "picking")
        packer.execute_action({
            "agent_id": "packer",
            "action_type": "accept_package",
            "parameters": {"order_id": "order-1"},
        })
        self.assertEqual(packer.packages[0]["status"], "accumulating")
        self.assertEqual(len(packer.packages[0]["items"]["A"]), 2)

        picker.find_items(order_obj)
        picker.process_next_action()
        picker.unload_to_packer(order_obj)
        packer.execute_action({
            "agent_id": "packer",
            "action_type": "accept_package",
            "parameters": {"order_id": "order-1"},
        })

        self.assertEqual(order_obj.status, "packed")
        self.assertEqual(packer.packages[0]["status"], "packed")
        self.assertEqual(len(packer.packages[0]["items"]["A"]), 3)
        self.assertEqual(picker._carried_quantity(), 0)

    def test_order_is_picked_packed_dispatched_and_delivered(self):
        inventory = InventoryAgent("inventory", items={"A": 1})
        delivery = DeliveryAgent("delivery", delivery_capacity=1)
        dispatch = DispatchAgent(
            "dispatch",
            delivery_capacity=1,
            neighboring_agents=[delivery],
        )
        packer = PackerAgent(
            "packer",
            package_capacity=1,
            neighboring_agents=[dispatch],
        )
        order_obj = order(
            "order-2",
            "customer-2",
            {"A": 1},
            "zone-b",
            {"A": 100},
            "picking",
        )
        picker = PickerAgent(
            "picker-2",
            item_capacity=1,
            order_queue=[order_obj],
            neighboring_agents=[inventory, packer],
        )

        picker.find_items(order_obj)
        picker.process_next_action()
        picker.move_to_packer(order_obj)
        packer.execute_action({
            "agent_id": "packer",
            "action_type": "accept_package",
            "parameters": {"order_id": "order-2"},
        })

        self.assertIn(
            {
                "action_type": "move_to_dispatch",
                "parameters": {"order_id": "order-2"},
            },
            packer.available_actions(),
        )
        packer.execute_action({
            "agent_id": "packer",
            "action_type": "move_to_dispatch",
            "parameters": {"order_id": "order-2"},
        })
        dispatch.execute_action({
            "agent_id": "dispatch",
            "action_type": "assign_delivery",
            "parameters": {"order_id": "order-2"},
        })
        delivery.execute_action({
            "agent_id": "delivery",
            "action_type": "accept_delivery",
            "parameters": {"order_id": "order-2"},
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

        self.assertEqual(order_obj.status, "completed")
        self.assertEqual(delivery.deliveries[0]["order_id"], "order-2")


if __name__ == "__main__":
    unittest.main()
