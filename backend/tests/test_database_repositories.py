import gc
import os
import tempfile
import unittest
from pathlib import Path

from backend.database import InventoryRepository, OrderRepository, connect_database


class DatabaseRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        file_descriptor, database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(file_descriptor)
        self.database_path = Path(database_path)
        self.connection = connect_database(self.database_path)
        self.orders = OrderRepository(self.connection)
        self.inventory = InventoryRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.execute("DELETE FROM inventory_movements")
        self.connection.execute("DELETE FROM inventory_units")
        self.connection.execute("DELETE FROM order_items")
        self.connection.execute("DELETE FROM orders")
        self.connection.execute("DELETE FROM inventory")
        self.connection.commit()
        self.connection.close()
        gc.collect()
        self.database_path.unlink(missing_ok=True)
        self.database_path.with_suffix(".sqlite3-wal").unlink(missing_ok=True)
        self.database_path.with_suffix(".sqlite3-shm").unlink(missing_ok=True)

    def test_reservation_partial_pick_and_release(self) -> None:
        self.orders.create_order(
            order_id="order-1",
            customer_id="customer-1",
            location="zone-a",
            items=[{"product_id": "sku-1", "quantity": 2}],
        )
        self.inventory.add_stock("sku-1", 5)

        self.inventory.reserve_stock("order-1", "sku-1", 2, simulation_time=1)
        self.assertEqual(self.inventory.get_available_quantity("sku-1"), 3)

        self.inventory.commit_pick("order-1", "sku-1", 1, simulation_time=2)
        inventory_row = self.connection.execute(
            "SELECT available_quantity, reserved_quantity FROM inventory WHERE product_id = ?",
            ("sku-1",),
        ).fetchone()
        item_row = self.connection.execute(
            "SELECT picked_quantity FROM order_items WHERE order_id = ? AND product_id = ?",
            ("order-1", "sku-1"),
        ).fetchone()
        self.assertEqual((inventory_row["available_quantity"], inventory_row["reserved_quantity"]), (3, 1))
        self.assertEqual(item_row["picked_quantity"], 1)

        self.inventory.release_stock("order-1", "sku-1", 1, simulation_time=3)
        inventory_row = self.connection.execute(
            "SELECT available_quantity, reserved_quantity FROM inventory WHERE product_id = ?",
            ("sku-1",),
        ).fetchone()
        self.assertEqual((inventory_row["available_quantity"], inventory_row["reserved_quantity"]), (4, 0))

    def test_reservation_is_atomic_when_stock_is_insufficient(self) -> None:
        self.orders.create_order(
            order_id="order-2",
            customer_id="customer-2",
            location="zone-b",
            items=[{"product_id": "sku-2", "quantity": 2}],
        )
        self.inventory.add_stock("sku-2", 1)

        with self.assertRaises(ValueError):
            self.inventory.reserve_stock("order-2", "sku-2", 2)

        row = self.connection.execute(
            "SELECT available_quantity, reserved_quantity FROM inventory WHERE product_id = ?",
            ("sku-2",),
        ).fetchone()
        self.assertEqual((row["available_quantity"], row["reserved_quantity"]), (1, 0))

    def test_inventory_unit_health_and_quarantine(self) -> None:
        self.inventory.add_unit("unit-1", "sku-3", health=0.85, condition="good")

        unit = self.inventory.get_unit("unit-1")
        self.assertEqual(unit["product_id"], "sku-3")
        self.assertEqual(unit["health"], 0.85)
        self.assertEqual(unit["condition"], "good")
        self.assertEqual(unit["status"], "available")

        self.inventory.update_unit_health("unit-1", 0.4, condition="worn")
        self.inventory.quarantine_unit("unit-1")

        unit = self.inventory.get_unit("unit-1")
        inventory = self.connection.execute(
            "SELECT available_quantity, damaged_quantity FROM inventory WHERE product_id = ?",
            ("sku-3",),
        ).fetchone()
        self.assertEqual(unit["health"], 0.4)
        self.assertEqual(unit["condition"], "damaged")
        self.assertEqual(unit["status"], "quarantined")
        self.assertEqual((inventory["available_quantity"], inventory["damaged_quantity"]), (0, 1))


if __name__ == "__main__":
    unittest.main()