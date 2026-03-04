CREATE TABLE IF NOT EXISTS court_games (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    defendant TEXT NOT NULL,
    crime TEXT NOT NULL,
    prosecutor_id BIGINT,
    lawyer_id BIGINT,
    witness_id BIGINT,
    prosecutor_cards JSONB DEFAULT '[]',
    lawyer_cards JSONB DEFAULT '[]',
    witness_cards JSONB DEFAULT '[]',
    played_cards JSONB DEFAULT '[]',
    current_round INT DEFAULT 0,
    prosecutor_cards_left INT DEFAULT 4,
    lawyer_cards_left INT DEFAULT 2,
    witness_cards_left INT DEFAULT 2,
    status TEXT DEFAULT 'lobby',
    verdict TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS court_messages (
    id SERIAL PRIMARY KEY,
    game_id INT REFERENCES court_games(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    round_number INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
