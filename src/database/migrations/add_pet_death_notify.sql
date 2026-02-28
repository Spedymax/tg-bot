ALTER TABLE pisunchik_data
ADD COLUMN IF NOT EXISTS pet_death_pending_notify BOOLEAN DEFAULT FALSE;
