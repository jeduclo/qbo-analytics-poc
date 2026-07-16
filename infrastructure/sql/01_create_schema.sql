-- Run this first. Creates the qbo schema.
-- Safe to re-run (checks for existence before creating).

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'qbo')
BEGIN
    EXEC('CREATE SCHEMA qbo');
    PRINT 'Schema qbo created.';
END
ELSE
BEGIN
    PRINT 'Schema qbo already exists. Skipping.';
END