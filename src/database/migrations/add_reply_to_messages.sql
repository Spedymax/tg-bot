-- Add reply-thread linkage to messages so analytics / the self-improve loop can see
-- which message each one replies to (prevents false "double-reply" findings).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_message_id BIGINT;

CREATE INDEX IF NOT EXISTS messages_reply_to_idx
    ON messages (reply_to_message_id);
