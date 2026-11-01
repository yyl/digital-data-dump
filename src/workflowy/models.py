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

CREATE_NODE_MODIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS node_modifications (
    node_id TEXT NOT NULL,
    modified_at REAL NOT NULL,
    PRIMARY KEY (node_id, modified_at)
);
"""

CREATE_NODE_REMOVALS_TABLE = """
CREATE TABLE IF NOT EXISTS node_removals (
    node_id TEXT NOT NULL,
    removed_at TEXT NOT NULL,
    PRIMARY KEY (node_id, removed_at)
);
"""

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT PRIMARY KEY,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    nodes_added INTEGER NOT NULL DEFAULT 0,
    nodes_modified INTEGER NOT NULL DEFAULT 0,
    nodes_removed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
"""

RAW_TABLES = [
    CREATE_NODES_TABLE, CREATE_SYNC_STATE_TABLE,
    CREATE_NODE_MODIFICATIONS_TABLE, CREATE_NODE_REMOVALS_TABLE,
]

RAW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_parent_id ON nodes(parent_id);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_modified_at ON nodes(modified_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_created_at ON nodes(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_completed_at ON nodes(completed_at);",
    "CREATE INDEX IF NOT EXISTS idx_workflowy_nodes_is_deleted ON nodes(is_deleted);",
]
