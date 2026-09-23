-- 0004_create_addresses.up.sql
CREATE TABLE addresses (
    id SERIAL PRIMARY KEY,
    postal_code VARCHAR(6),
    address_text VARCHAR(1000) NOT NULL,
    latitude NUMERIC(10, 7) NOT NULL,
    longitude NUMERIC(10, 7) NOT NULL,
    is_private BOOLEAN,
    CONSTRAINT uq_addresses_address_text UNIQUE (address_text),
    CONSTRAINT ck_addresses_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_addresses_longitude CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_addresses_postal_code CHECK (
        postal_code IS NULL OR postal_code ~ '^[0-9]{6}$'
    ),
    CONSTRAINT ck_addresses_text CHECK (length(trim(address_text)) > 0)
);

CREATE INDEX ix_addresses_postal_code ON addresses (postal_code);
