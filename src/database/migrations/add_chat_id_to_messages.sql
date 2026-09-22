-- Isolate Telegram message history by chat.
--
-- Existing rows predate multi-chat storage and came from the original/main group,
-- so the only honest backfill available is the main chat id.
BEGIN;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS chat_id BIGINT;

UPDATE messages
SET chat_id = -1001294162183
WHERE chat_id IS NULL;

ALTER TABLE messages ALTER COLUMN chat_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS messages_chat_timestamp_idx
    ON messages (chat_id, timestamp DESC);

CREATE UNIQUE INDEX IF NOT EXISTS messages_chat_message_id_uidx
    ON messages (chat_id, message_id)
    WHERE message_id IS NOT NULL;

COMMIT;
