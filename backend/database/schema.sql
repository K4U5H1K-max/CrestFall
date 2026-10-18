PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    customer_name TEXT,
    location TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'reserved', 'picking', 'packed',
            'dispatched', 'delivered', 'failed', 'returned', 'cancelled'
        )),
    health REAL NOT NULL DEFAULT 1.0 CHECK (health >= 0.0 AND health <= 1.0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deadline TEXT,
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    picked_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (picked_quantity >= 0 AND picked_quantity <= quantity),
    item_health REAL NOT NULL DEFAULT 1.0
        CHECK (item_health >= 0.0 AND item_health <= 1.0),
    PRIMARY KEY (order_id, product_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory (
    product_id TEXT PRIMARY KEY,
    available_quantity INTEGER NOT NULL DEFAULT 0 CHECK (available_quantity >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    damaged_quantity INTEGER NOT NULL DEFAULT 0 CHECK (damaged_quantity >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0)
);

CREATE TABLE IF NOT EXISTS inventory_units (
    unit_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    health REAL NOT NULL DEFAULT 1.0 CHECK (health >= 0.0 AND health <= 1.0),
    condition TEXT NOT NULL DEFAULT 'new'
        CHECK (condition IN ('new', 'good', 'worn', 'damaged', 'unknown')),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN (
            'available', 'reserved', 'picked', 'in_transit',
            'delivered', 'returned', 'quarantined', 'disposed'
        )),
    order_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES inventory(product_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    order_id TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    movement_type TEXT NOT NULL
        CHECK (movement_type IN (
            'stock_received', 'reserved', 'released', 'picked',
            'returned', 'damaged', 'disposed'
        )),
    simulation_time INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES inventory(product_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS simulation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_time INTEGER NOT NULL,
    order_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_status_priority
    ON orders(status, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_inventory_movements_product
    ON inventory_movements(product_id, simulation_time);

CREATE INDEX IF NOT EXISTS idx_inventory_units_product_status
    ON inventory_units(product_id, status);

CREATE INDEX IF NOT EXISTS idx_simulation_events_time
    ON simulation_events(simulation_time, event_id);
