-- Title optional: parsers may leave only body when headline cannot be extracted.
ALTER TABLE events ALTER COLUMN title DROP NOT NULL;
