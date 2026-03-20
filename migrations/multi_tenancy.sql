-- Multi-tenancy migration: add companies table + company_id columns
-- Run this manually ONLY if you are not using Alembic autogenerate.
-- Preferred: alembic revision --autogenerate -m "add_multi_tenancy" && alembic upgrade head

-- 1. Create companies (tenants) table
CREATE TABLE IF NOT EXISTS companies (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    license_key     VARCHAR(50),
    plan            VARCHAR(50) NOT NULL DEFAULT 'starter',
    max_users       INTEGER NOT NULL DEFAULT 10,
    max_storage_gb  INTEGER NOT NULL DEFAULT 10,
    billing_cycle   VARCHAR(20) NOT NULL DEFAULT 'monthly',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    owner_email     VARCHAR(255),
    logo_url        VARCHAR(500),
    brand_color     VARCHAR(20),
    custom_domain   VARCHAR(255),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_companies_slug ON companies (slug);
CREATE INDEX IF NOT EXISTS ix_companies_owner_email ON companies (owner_email);

-- 2. Add company_id + is_super_admin to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS company_id    VARCHAR(36) REFERENCES companies(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_users_company_id ON users (company_id);

-- 3. Add company_id to teams (teams are scoped per company; drop old unique constraint on name first)
ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_name_key;
ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_teams_company_id ON teams (company_id);

-- 4. Add company_id to collections
ALTER TABLE collections
    ADD COLUMN IF NOT EXISTS company_id VARCHAR(36) REFERENCES companies(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_collections_company_id ON collections (company_id);
