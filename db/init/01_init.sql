-- Runs once on first start of the Postgres container (superuser context).
-- 1) Read-only role used by the SQL Analyst  2) sample 'analytics' database to try the app.

CREATE ROLE bi_readonly LOGIN PASSWORD 'bi_readonly_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE bi_readonly SET default_transaction_read_only = on;
ALTER ROLE bi_readonly SET statement_timeout = '15s';
ALTER ROLE bi_readonly CONNECTION LIMIT 10;

CREATE DATABASE analytics;
\connect analytics

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE TABLE products (
  product_id serial PRIMARY KEY, name text NOT NULL, category text NOT NULL, unit_cost numeric(10,2));
INSERT INTO products(name, category, unit_cost) VALUES
  ('Aurora Laptop','Electronics',700), ('Pulse Headphones','Electronics',60), ('Nimbus Desk','Furniture',150),
  ('Ergo Chair','Furniture',120), ('Zen Notebook','Stationery',2), ('Quill Pen Set','Stationery',8);

CREATE TABLE customers (customer_id serial PRIMARY KEY, name text, region text);
INSERT INTO customers(name, region)
  SELECT 'Customer ' || g, (ARRAY['North','South','East','West'])[1 + g % 4] FROM generate_series(1, 200) g;

CREATE TABLE orders (
  order_id serial PRIMARY KEY, order_date date NOT NULL,
  customer_id int REFERENCES customers, product_id int REFERENCES products,
  quantity int NOT NULL, unit_price numeric(10,2) NOT NULL);
-- ~5000 orders over 2024-2025; laptop orders thin out from May 2025 so "why did sales decrease?" has an answer.
INSERT INTO orders(order_date, customer_id, product_id, quantity, unit_price)
SELECT d, 1 + (g * 7 % 200), 1 + (g % 6), 1 + (g % 5), (ARRAY[999,89,249,199,4,15])[1 + g % 6]
FROM (SELECT g, DATE '2024-01-01' + (g * 37 % 600) AS d FROM generate_series(1, 5000) g) t
WHERE NOT (d >= DATE '2025-05-01' AND g % 6 = 0 AND g % 4 <> 0);

GRANT CONNECT ON DATABASE analytics TO bi_readonly;
GRANT USAGE ON SCHEMA public TO bi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO bi_readonly;
