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
