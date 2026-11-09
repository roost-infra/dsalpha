-- Billing schema for the self-hosted quota service.
-- Idempotent: applied on startup and safe to re-run.

CREATE SCHEMA IF NOT EXISTS billing;

CREATE TABLE IF NOT EXISTS billing.plans (
    code            text PRIMARY KEY,
    name            text NOT NULL,
    description     text,
    access_tier     int  NOT NULL DEFAULT 0,
    scopes          text[] NOT NULL DEFAULT '{}',
    limits          jsonb  NOT NULL DEFAULT '{}'::jsonb,
    sandbox_pricing jsonb  NOT NULL DEFAULT '{}'::jsonb,
    monthly_credits numeric(20,6) NOT NULL DEFAULT 0,
    -- 展示/对账用的月费与包含小时数；扣费仍统一走 credits。
    price_cny           numeric(10,2) NOT NULL DEFAULT 0,
    included_hours_month numeric(10,2) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 已存在的库：补列（幂等）
ALTER TABLE billing.plans
    ADD COLUMN IF NOT EXISTS price_cny numeric(10,2) NOT NULL DEFAULT 0;
ALTER TABLE billing.plans
    ADD COLUMN IF NOT EXISTS included_hours_month numeric(10,2) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS billing.user_plans (
    user_id     text PRIMARY KEY,
    plan_code   text NOT NULL REFERENCES billing.plans(code),
    assigned_by text,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    note        text
);

CREATE TABLE IF NOT EXISTS billing.wallets (
    user_id    text PRIMARY KEY,
    balance    numeric(20,6) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing.ledger (
    id         bigserial PRIMARY KEY,
    user_id    text NOT NULL,
    delta      numeric(20,6) NOT NULL,
    reason     text NOT NULL,
    source     text,
    source_id  text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_ledger_user
    ON billing.ledger (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS billing.leases (
    run_ref          text PRIMARY KEY,
    user_id          text NOT NULL,
    reserved_credits numeric(20,6) NOT NULL DEFAULT 0,
    generation       int NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    expires_at       timestamptz NOT NULL,
    released_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_leases_user
    ON billing.leases (user_id) WHERE released_at IS NULL;

CREATE TABLE IF NOT EXISTS billing.run_billing (
    run_id         uuid PRIMARY KEY,
    user_id        text NOT NULL,
    billed_until   timestamptz NOT NULL,
    credits_billed numeric(20,6) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS billing.ingest_state (
    name       text PRIMARY KEY,
    cursor     text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing.admin_audit (
    id         bigserial PRIMARY KEY,
    actor      text NOT NULL,
    action     text NOT NULL,
    target     text,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 按沙箱 tier 的月费档位。积分换算：sandbox_pricing 是每 tier 每小时消耗的
-- credits，定为「Daytona 2× 成本」的上限，自建宿主机可以后续下调。
INSERT INTO billing.plans
    (code, name, description, access_tier, scopes, limits, sandbox_pricing,
     monthly_credits, price_cny, included_hours_month)
VALUES
    (
        'free', 'Free', 'Free tier: one standard computer, no monthly credits.',
        0, ARRAY[]::text[],
        '{"computer_count": 1, "always_on": 0, "spec_computers": 0, "per_turn_credits": 200}'::jsonb,
        '{"standard": 166.7}'::jsonb,
        0, 0, 0
    ),
    (
        'basic', 'Basic', 'Standard sandbox, 5000 credits (about 30h), ¥69/month.',
        1, ARRAY[]::text[],
        '{"computer_count": 1, "always_on": 0, "spec_computers": 0, "per_turn_credits": 300}'::jsonb,
        '{"standard": 166.7}'::jsonb,
        5000, 69, 30
    ),
    (
        'pro', 'Pro', 'Performance sandbox, 10000 credits (about 30h), ¥129/month.',
        2,
        ARRAY['workspace:always_on', 'workspace:spec:performance']::text[],
        '{"computer_count": 3, "always_on": 1, "spec_computers": 1, "per_turn_credits": 500}'::jsonb,
        '{"standard": 166.7, "performance": 333.3}'::jsonb,
        10000, 129, 30
    ),
    (
        'max', 'Max', 'Max sandbox, 15000 credits (about 30h), ¥299/month.',
        3,
        ARRAY['workspace:always_on', 'workspace:spec:performance',
              'workspace:spec:max', 'workspace:spec:xlarge']::text[],
        '{"computer_count": 5, "always_on": 2, "spec_computers": 2, "per_turn_credits": 1000}'::jsonb,
        '{"standard": 166.7, "performance": 333.3, "max": 500}'::jsonb,
        15000, 299, 30
    )
ON CONFLICT (code) DO NOTHING;
