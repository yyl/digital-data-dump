"""SQL schema definitions for GitHub activity tracking."""

VISIBILITY_METRICS = (
    "public_commits", "private_commits", "public_repos_touched", "private_repos_touched",
)

CREATE_COMMITS_TABLE = """
CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    message TEXT,
    author_date TEXT NOT NULL,
    date_month TEXT NOT NULL,
    is_private INTEGER NOT NULL DEFAULT 0,
    is_discoverable INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
)
"""

CREATE_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS analysis (
    year_month TEXT PRIMARY KEY,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    commits INTEGER DEFAULT 0,
    repos_touched INTEGER DEFAULT 0,
    public_commits INTEGER,
    private_commits INTEGER,
    public_repos_touched INTEGER,
    private_repos_touched INTEGER,
    updated_at TEXT
)
"""

ANALYSIS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_analysis_year_month ON analysis(year, month);",
]
