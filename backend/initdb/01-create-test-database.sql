-- Creates the throwaway database the schema tests run against.
--
-- Runs once, when the db container initialises an empty data volume. If you
-- added this after the volume already existed, it will not have run:
--     docker compose down -v && docker compose up -d db
--
-- A separate database rather than reusing tube_router. The constraint tests
-- roll their transactions back, so sharing would be safe today — but from
-- Phase 2 the development database holds a seeded network, and one future
-- test that commits by accident would quietly corrupt it. Six lines of SQL
-- removes that entire class of accident.

CREATE DATABASE tube_router_test;
