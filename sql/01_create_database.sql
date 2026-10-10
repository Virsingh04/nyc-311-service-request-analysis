-- Run as a MySQL administrator. Replace the example password before use.
CREATE DATABASE IF NOT EXISTS nyc311_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'nyc311_user'@'127.0.0.1' IDENTIFIED BY 'change_me';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, CREATE VIEW, SHOW VIEW, DROP ON nyc311_analytics.* TO 'nyc311_user'@'127.0.0.1';
FLUSH PRIVILEGES;
