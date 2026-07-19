BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username);

CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id INTEGER PRIMARY KEY
        REFERENCES users (id) ON DELETE CASCADE,
    ciphertext BYTEA NOT NULL,
    last_four VARCHAR(4) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE,
    data BYTEA,
    expiry TIMESTAMP WITHOUT TIME ZONE
);

COMMIT;
