from __future__ import annotations

import sqlite3
from typing import Iterable, Mapping


class OrderRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_order(
        self,
        order_id: str,
        customer_id: str,
        location: str,
        items: Iterable[Mapping[str, object]],
        customer_name: str | None = None,
        priority: int = 0,
        deadline: str | None = None,
    ) -> None:
        item_rows = list(items)
        if not item_rows:
            raise ValueError("An order must contain at least one item")

        try:
            self.connection.execute(
                """
                INSERT INTO orders
                    (order_id, customer_id, customer_name, location, priority, deadline)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (order_id, customer_id, customer_name, location, priority, deadline),
            )
            self.connection.executemany(
                """
                INSERT INTO order_items (order_id, product_id, quantity)
                VALUES (?, ?, ?)
                """,
                [
                    (order_id, item["product_id"], item["quantity"])
                    for item in item_rows
                ],
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_order(self, order_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()

    def update_status(
        self, order_id: str, status: str, failure_reason: str | None = None
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE orders
            SET status = ?, failure_reason = ?
            WHERE order_id = ?
            """,
            (status, failure_reason, order_id),
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise ValueError(f"Order does not exist: {order_id}")
        self.connection.commit()
