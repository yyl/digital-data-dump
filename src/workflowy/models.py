"""SQLite schema definitions for Workflowy."""

CREATE_NODES_TABLE = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    name TEXT NOT NULL,
    note TEXT,
    priority REAL NOT NULL,
    layout_mode TEXT,
    completed INTEGER NOT NULL,
    created_at REAL NOT NULL,
    modified_at REAL,
    completed_at REAL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
"""

CREATE_SYNC_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    entity_type TEXT PRIMARY KEY,
    last_successful_sync_at TEXT,
    last_export_started_at TEXT,
    last_export_node_count INTEGER,
    last_inserted_count INTEGER,
    last_updated_count INTEGER,
    last_unchanged_count INTEGER,
    last_tombstoned_count INTEGER
);
"""

RAW_TABLES = [CREATE_NODES_TABLE, CREATE_SYNC_STATE_TABLE]

RAW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_parent_id ON nodes(parent_id);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_modified_at ON nodes(modified_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_created_at ON nodes(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_completed_at ON nodes(completed_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_is_deleted ON nodes(is_deleted);",
]
