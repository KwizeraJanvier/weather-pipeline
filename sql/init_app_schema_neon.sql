-- Neon-specific variant of init_app_schema.sql. On Neon, the project's
-- owner role (e.g. neondb_owner) creates and owns everything directly -
-- there's no separate "superuser vs. app role" split like the local
-- Postgres setup (see init_app_schema.sql's comment about that), so the
-- GRANT-to-warehouse workaround isn't needed here.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.audit_log (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES app.users(id),
    email TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Attempt the same dedicated read-only role as the local setup. Neon's
-- project-owner role may or may not have CREATEROLE depending on your plan;
-- if this statement errors, see the "Neon: if CREATE ROLE fails" note in
-- the README - the app falls back to running admin queries inside an
-- explicit read-only transaction on the main role instead.
--
-- Re-running this (e.g. after rotating the password secret) updates the
-- password on the existing role rather than erroring on "already exists".
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly LOGIN PASSWORD :'app_readonly_password';
    ELSE
        ALTER ROLE app_readonly PASSWORD :'app_readonly_password';
    END IF;
END
$$;

ALTER ROLE app_readonly SET statement_timeout = '5s';

GRANT USAGE ON SCHEMA raw, staging, marts TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA raw, staging, marts TO app_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw, staging, marts
    GRANT SELECT ON TABLES TO app_readonly;

REVOKE ALL ON SCHEMA app FROM app_readonly, PUBLIC;
