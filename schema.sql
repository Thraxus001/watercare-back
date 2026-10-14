-- WaterCare – PostgreSQL schema
-- Run once on an empty database:  psql -d watercare -f schema.sql

CREATE TYPE user_role      AS ENUM ('admin', 'user');
CREATE TYPE check_category AS ENUM ('operation', 'maintenance');
CREATE TYPE input_type     AS ENUM ('radio', 'checkbox');

-- ───────────── Users & permissions ─────────────
CREATE TABLE users (
    id               SERIAL PRIMARY KEY,
    email            VARCHAR(255) NOT NULL UNIQUE,
    full_name        VARCHAR(150) NOT NULL,
    hashed_password  VARCHAR(255) NOT NULL,
    role             user_role    NOT NULL DEFAULT 'user',
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Admins bypass this table (they can do everything). Regular users get
-- only the permission codes an admin grants here.
CREATE TABLE user_permissions (
    user_id     INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission  VARCHAR(50) NOT NULL,
    PRIMARY KEY (user_id, permission)
);

-- ───────────── Machines & checklist definition ─────────────
CREATE TABLE machine_types (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(150) NOT NULL UNIQUE,
    description  TEXT
);

CREATE TABLE machines (
    id               SERIAL PRIMARY KEY,
    machine_type_id  INTEGER      NOT NULL REFERENCES machine_types(id),
    name             VARCHAR(150) NOT NULL,
    serial_number    VARCHAR(100) NOT NULL UNIQUE,
    location         VARCHAR(255),
    installed_on     DATE,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_machines_type ON machines(machine_type_id);

-- A check the admin defines for every machine of a given type.
-- Items are archived (is_active = false), never deleted, so history stays intact.
CREATE TABLE check_items (
    id               SERIAL PRIMARY KEY,
    machine_type_id  INTEGER        NOT NULL REFERENCES machine_types(id) ON DELETE CASCADE,
    category         check_category NOT NULL,
    label            VARCHAR(255)   NOT NULL,
    description      TEXT,
    input_type       input_type     NOT NULL,
    is_required      BOOLEAN        NOT NULL DEFAULT FALSE,
    sort_order       INTEGER        NOT NULL DEFAULT 0,
    is_active        BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE INDEX ix_check_items_type ON check_items(machine_type_id, is_active);

-- Choices for a check item. radio = pick one, checkbox = tick any number.
-- A simple "done / not done" check is a checkbox item with one option, "Done".
CREATE TABLE check_item_options (
    id             SERIAL PRIMARY KEY,
    check_item_id  INTEGER      NOT NULL REFERENCES check_items(id) ON DELETE CASCADE,
    label          VARCHAR(200) NOT NULL,
    sort_order     INTEGER      NOT NULL DEFAULT 0,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX ix_check_item_options_item ON check_item_options(check_item_id);

-- ───────────── Inspections (the actual checkups) ─────────────
CREATE TABLE inspections (
    id            SERIAL PRIMARY KEY,
    machine_id    INTEGER     NOT NULL REFERENCES machines(id),
    performed_by  INTEGER     NOT NULL REFERENCES users(id),
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary       TEXT
);
CREATE INDEX ix_inspections_machine_date ON inspections(machine_id, performed_at DESC);
CREATE INDEX ix_inspections_user ON inspections(performed_by);

-- One row per checklist item at the time of the checkup. Labels are
-- snapshotted so later edits to the checklist never rewrite history.
CREATE TABLE inspection_answers (
    id               SERIAL PRIMARY KEY,
    inspection_id    INTEGER        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    check_item_id    INTEGER        REFERENCES check_items(id) ON DELETE SET NULL,
    check_item_label VARCHAR(255)   NOT NULL,
    category         check_category NOT NULL,
    input_type       input_type     NOT NULL
);
CREATE INDEX ix_answers_inspection ON inspection_answers(inspection_id);

-- Every option of the item, with whether it was ticked => shows what was
-- done AND what was not.
CREATE TABLE inspection_answer_options (
    id            SERIAL PRIMARY KEY,
    answer_id     INTEGER      NOT NULL REFERENCES inspection_answers(id) ON DELETE CASCADE,
    option_id     INTEGER      REFERENCES check_item_options(id) ON DELETE SET NULL,
    option_label  VARCHAR(200) NOT NULL,
    is_checked    BOOLEAN      NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_answer_options_answer ON inspection_answer_options(answer_id);

-- ───────────── Notes ─────────────
CREATE TABLE machine_notes (
    id             SERIAL PRIMARY KEY,
    machine_id     INTEGER     NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    inspection_id  INTEGER     REFERENCES inspections(id) ON DELETE SET NULL,  -- optional link to a checkup
    author_id      INTEGER     NOT NULL REFERENCES users(id),
    body           TEXT        NOT NULL CHECK (length(btrim(body)) > 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_notes_machine ON machine_notes(machine_id, created_at DESC);
