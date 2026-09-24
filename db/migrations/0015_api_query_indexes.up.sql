-- Индексы под API nearby/city/map: bbox по адресам + фильтры ленты.

CREATE INDEX IF NOT EXISTS ix_addresses_lat_lon
    ON addresses (latitude, longitude);

-- Nearby: importance ∈ (1,2) AND geo_by ∈ (street,home) AND active_to
CREATE INDEX IF NOT EXISTS ix_events_feed_nearby
    ON events (importance, geo_by, active_to)
    WHERE address_id IS NOT NULL;

-- City / map: importance + active_to при наличии адреса
CREATE INDEX IF NOT EXISTS ix_events_feed_addressed
    ON events (importance, active_to)
    WHERE address_id IS NOT NULL;

-- City feed JOIN addresses ON city = 'Москва'
CREATE INDEX IF NOT EXISTS ix_addresses_city_lat_lon
    ON addresses (city, latitude, longitude);
