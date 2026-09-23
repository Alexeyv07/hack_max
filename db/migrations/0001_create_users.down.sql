-- 0001_create_users.down.sql
DROP INDEX IF EXISTS ix_users_username;
DROP INDEX IF EXISTS ix_users_max_user_id;
DROP TABLE IF EXISTS users;
