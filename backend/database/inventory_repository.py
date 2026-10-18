from __future__ import annotations

import sqlite3


class InventoryRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def add_unit(
        self,
        unit_id: str,
        product_id: str,
        health: float = 1.0,
        condition: str = "new",
    ) -> None:
        if not 0.0 <= health <= 1.0:
            raise ValueError("Unit health must be between 0.0 and 1.0")

        try:
            self.connection.execute(
                """
                INSERT INTO inventory (product_id, available_quantity)
                VALUES (?, 1)
                ON CONFLICT(product_id) DO UPDATE SET
                    available_quantity = available_quantity + 1
                """,
                (product_id,),
            )
            self.connection.execute(
                """
                INSERT INTO inventory_units
                    (unit_id, product_id, health, condition)
                VALUES (?, ?, ?, ?)
                """,
                (unit_id, product_id, health, condition),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_unit(self, unit_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM inventory_units WHERE unit_id = ?", (unit_id,)
        ).fetchone()

    def update_unit_health(
        self, unit_id: str, health: float, condition: str | None = None
    ) -> None:
        if not 0.0 <= health <= 1.0:
            raise ValueError("Unit health must be between 0.0 and 1.0")

        if condition is None:
            cursor = self.connection.execute(
                "UPDATE inventory_units SET health = ? WHERE unit_id = ?",
                (health, unit_id),
            )
        else:
            cursor = self.connection.execute(
                """
                UPDATE inventory_units
                SET health = ?, condition = ?
                WHERE unit_id = ?
                """,
                (health, condition, unit_id),
            )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise ValueError(f"Inventory unit does not exist: {unit_id}")
        self.connection.commit()

    def quarantine_unit(self, unit_id: str) -> None:
        try:
            unit = self.get_unit(unit_id)
            if unit is None:
                raise ValueError(f"Inventory unit does not exist: {unit_id}")
            if unit["status"] != "available":
                raise ValueError(f"Only available units can be quarantined: {unit_id}")

            self.connection.execute(
                """
                UPDATE inventory_units
                SET status = 'quarantined', condition = 'damaged'
                WHERE unit_id = ?
                """,
                (unit_id,),
            )
            self.connection.execute(
                """
                UPDATE inventory
                SET available_quantity = available_quantity - 1,
                    damaged_quantity = damaged_quantity + 1
                WHERE product_id = ? AND available_quantity >= 1
                """,
                (unit["product_id"],),
            )
            if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError(f"Inventory count is inconsistent for unit: {unit_id}")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def add_stock(
        self,
        product_id: str,
        quantity: int,
        simulation_time: int = 0,
        reorder_level: int = 0,
    ) -> None:
        if quantity <= 0:
            raise ValueError("Stock quantity must be positive")

        self.connection.execute(
            """
            INSERT INTO inventory (product_id, available_quantity, reorder_level)
            VALUES (?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                available_quantity = available_quantity + excluded.available_quantity,
                reorder_level = excluded.reorder_level
            """,
            (product_id, quantity, reorder_level),
        )
        self._record_movement(product_id, quantity, "stock_received", simulation_time)
        self.connection.commit()

    def get_available_quantity(self, product_id: str) -> int:
        row = self.connection.execute(
            "SELECT available_quantity FROM inventory WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        return 0 if row is None else row["available_quantity"]

    def reserve_stock(
        self, order_id: str, product_id: str, quantity: int, simulation_time: int = 0
    ) -> None:
        if quantity <= 0:
            raise ValueError("Reservation quantity must be positive")

        try:
            cursor = self.connection.execute(
                """
                UPDATE inventory
                SET available_quantity = available_quantity - ?,
                    reserved_quantity = reserved_quantity + ?
                WHERE product_id = ? AND available_quantity >= ?
                """,
                (quantity, quantity, product_id, quantity),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Insufficient stock for product: {product_id}")
            self._record_movement(
                product_id, quantity, "reserved", simulation_time, order_id
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def release_stock(
        self, order_id: str, product_id: str, quantity: int, simulation_time: int = 0
    ) -> None:
        if quantity <= 0:
            raise ValueError("Release quantity must be positive")

        try:
            cursor = self.connection.execute(
                """
                UPDATE inventory
                SET available_quantity = available_quantity + ?,
                    reserved_quantity = reserved_quantity - ?
                WHERE product_id = ? AND reserved_quantity >= ?
                """,
                (quantity, quantity, product_id, quantity),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Insufficient reservation for product: {product_id}")
            self._record_movement(
                product_id, quantity, "released", simulation_time, order_id
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def commit_pick(
        self, order_id: str, product_id: str, quantity: int, simulation_time: int = 0
    ) -> None:
        if quantity <= 0:
            raise ValueError("Picked quantity must be positive")

        try:
            cursor = self.connection.execute(
                """
                UPDATE inventory
                SET reserved_quantity = reserved_quantity - ?
                WHERE product_id = ? AND reserved_quantity >= ?
                """,
                (quantity, product_id, quantity),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Insufficient reservation for product: {product_id}")

            self.connection.execute(
                """
                UPDATE order_items
                SET picked_quantity = picked_quantity + ?
                WHERE order_id = ? AND product_id = ?
                    AND picked_quantity + ? <= quantity
                """,
                (quantity, order_id, product_id, quantity),
            )
            if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError(f"Invalid pick for order item: {order_id}/{product_id}")

            self._record_movement(
                product_id, quantity, "picked", simulation_time, order_id
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _record_movement(
        self,
        product_id: str,
        quantity: int,
        movement_type: str,
        simulation_time: int,
        order_id: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_movements
                (product_id, order_id, quantity, movement_type, simulation_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, order_id, quantity, movement_type, simulation_time),
        )
