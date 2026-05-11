-- Identity prompt versions: append-only history
CREATE TABLE IF NOT EXISTS prompt_versions (
    id          SERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    author_id   BIGINT NOT NULL,
    author_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS prompt_versions_created_at_idx
    ON prompt_versions (created_at DESC);

-- Whitelist of users allowed to edit the prompt
CREATE TABLE IF NOT EXISTS prompt_admins (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT,
    granted_by  BIGINT,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
