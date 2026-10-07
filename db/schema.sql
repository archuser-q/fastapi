-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;

-- Tables
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    phone VARCHAR(15) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    full_name VARCHAR(150) NOT NULL,
    avatar_url TEXT,
    role VARCHAR(20) NOT NULL CHECK (role IN ('customer', 'worker', 'admin')),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'blocked', 'pending')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE social_accounts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('google', 'facebook')),
    provider_user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

CREATE TABLE device_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL,
    platform VARCHAR(10) NOT NULL CHECK (platform IN ('android', 'ios', 'web')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (token)
);

CREATE TABLE customer_addresses (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label VARCHAR(50),
    address_line VARCHAR(255) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE worker_profiles (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bio TEXT,
    experience_years INT NOT NULL DEFAULT 0,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (verification_status IN ('pending', 'approved', 'rejected')),
    availability VARCHAR(20) NOT NULL DEFAULT 'offline' CHECK (availability IN ('online', 'busy', 'offline')),
    service_radius_km NUMERIC(5,2) NOT NULL DEFAULT 10,
    current_latitude DOUBLE PRECISION,
    current_longitude DOUBLE PRECISION,
    location geography(Point, 4326),
    geohash VARCHAR(12),
    location_updated_at TIMESTAMP,
    trust_score NUMERIC(5,4) NOT NULL DEFAULT 0,
    review_count INT NOT NULL DEFAULT 0,
    completed_orders INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE worker_documents (
    id BIGSERIAL PRIMARY KEY,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    doc_type VARCHAR(30) NOT NULL CHECK (doc_type IN ('id_card_front', 'id_card_back', 'certificate', 'portrait')),
    file_url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by BIGINT REFERENCES users(id),
    reject_reason TEXT,
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

CREATE TABLE service_categories (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT REFERENCES service_categories(id),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    icon_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE services (
    id BIGSERIAL PRIMARY KEY,
    category_id BIGINT NOT NULL REFERENCES service_categories(id),
    name VARCHAR(150) NOT NULL,
    description TEXT,
    base_price NUMERIC(12,0) NOT NULL,
    unit VARCHAR(30),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE worker_services (
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    service_id BIGINT NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    PRIMARY KEY (worker_id, service_id)
);

CREATE TABLE matching_configs (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('instant', 'batch')),
    weight_distance NUMERIC(4,3) NOT NULL,
    weight_trust NUMERIC(4,3) NOT NULL,
    weight_price NUMERIC(4,3) NOT NULL,
    weight_workload NUMERIC(4,3) NOT NULL,
    batch_window_seconds INT,
    search_radius_km NUMERIC(5,2) NOT NULL DEFAULT 5,
    max_offers INT NOT NULL DEFAULT 3,
    offer_timeout_seconds INT NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by BIGINT REFERENCES users(id),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_matching_configs_active
    ON matching_configs (is_active) WHERE is_active;

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES users(id),
    worker_id BIGINT REFERENCES worker_profiles(user_id),
    service_id BIGINT NOT NULL REFERENCES services(id),
    address_line VARCHAR(255) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    description TEXT,
    image_urls TEXT[] NOT NULL DEFAULT '{}',
    scheduled_at TIMESTAMP,
    matching_mode VARCHAR(20) CHECK (matching_mode IN ('instant', 'batch')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'matched', 'accepted', 'on_the_way', 'arrived', 'in_progress', 'completed', 'cancelled')),
    estimated_price NUMERIC(12,0),
    final_price NUMERIC(12,0),
    cancel_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE order_status_history (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    changed_by BIGINT REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE order_offers (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id),
    match_score NUMERIC(8,5),
    distance_km NUMERIC(8,3),
    status VARCHAR(20) NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'accepted', 'rejected', 'expired')),
    sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMP,
    UNIQUE (order_id, worker_id)
);

CREATE TABLE order_extra_quotes (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id),
    description TEXT NOT NULL,
    amount NUMERIC(12,0) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMP
);

CREATE TABLE worker_location_logs (
    id BIGSERIAL PRIMARY KEY,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id) ON DELETE CASCADE,
    order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    sender_id BIGINT NOT NULL REFERENCES users(id),
    content TEXT,
    image_url TEXT,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE payments (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    amount NUMERIC(12,0) NOT NULL,
    method VARCHAR(20) NOT NULL CHECK (method IN ('cash', 'momo', 'vnpay')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'refunded')),
    transaction_code VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMP
);

CREATE TABLE worker_earnings (
    id BIGSERIAL PRIMARY KEY,
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id),
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id),
    gross_amount NUMERIC(12,0) NOT NULL,
    commission_amount NUMERIC(12,0) NOT NULL,
    net_amount NUMERIC(12,0) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE reviews (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id),
    customer_id BIGINT NOT NULL REFERENCES users(id),
    worker_id BIGINT NOT NULL REFERENCES worker_profiles(user_id),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    is_flagged BOOLEAN NOT NULL DEFAULT FALSE,
    flag_reason VARCHAR(255),
    is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    moderated_by BIGINT REFERENCES users(id),
    moderated_at TIMESTAMP,
    moderation_note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE warranties (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id),
    terms TEXT,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'claimed', 'expired'))
);

CREATE TABLE complaints (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    complainant_id BIGINT NOT NULL REFERENCES users(id),
    reason VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'processing', 'resolved', 'rejected')),
    resolution TEXT,
    handled_by BIGINT REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE TABLE notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    body TEXT,
    type VARCHAR(30),
    reference_id BIGINT,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_worker ON orders(worker_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_reviews_worker ON reviews(worker_id);
CREATE INDEX idx_messages_order ON messages(order_id);
CREATE INDEX idx_notifications_user ON notifications(user_id);
CREATE INDEX idx_location_logs_worker ON worker_location_logs(worker_id);

-- Triggers

CREATE OR REPLACE FUNCTION sync_worker_location() RETURNS trigger AS $$
BEGIN
    IF NEW.current_latitude IS NULL OR NEW.current_longitude IS NULL THEN
        NEW.location := NULL;
        NEW.geohash := NULL;
    ELSE
        NEW.location := ST_SetSRID(
            ST_MakePoint(NEW.current_longitude, NEW.current_latitude), 4326
        )::geography;
        NEW.geohash := ST_GeoHash(NEW.location::geometry, 7);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
 
DROP TRIGGER IF EXISTS trg_sync_worker_location ON worker_profiles;
CREATE TRIGGER trg_sync_worker_location
    BEFORE INSERT OR UPDATE OF current_latitude, current_longitude ON worker_profiles
    FOR EACH ROW EXECUTE FUNCTION sync_worker_location();