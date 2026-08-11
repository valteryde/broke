"""Maintenance scripts, importable as ``scripts.*``.

This file is what makes that true. Without it the directory is only a namespace
portion, and a namespace portion loses to any regular ``scripts`` package installed in
site-packages — which is how ``python scripts/migrate.py`` came to die on
``No module named 'scripts.migrate_001_ticket_active'`` on a machine that happened to
have one. Migrations that cannot be imported are migrations that never run, and the
symptom shows up much later as a column the application expects and the database has
never heard of.
"""
