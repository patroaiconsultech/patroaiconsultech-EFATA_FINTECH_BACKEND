from __future__ import annotations

import inspect

import tests.conftest as fixture_module


def test_postgres_reset_preserves_migrated_schema_contract():
    source = inspect.getsource(fixture_module.reset_database)
    assert 'engine.dialect.name == "postgresql"' in source
    assert "_truncate_postgres_test_data()" in source

    truncate_source = inspect.getsource(
        fixture_module._truncate_postgres_test_data
    )
    assert "TRUNCATE TABLE" in truncate_source
    assert "RESTART IDENTITY CASCADE" in truncate_source
    assert "drop_all" not in truncate_source


def test_seed_uses_explicit_fk_safe_flush_boundaries():
    source = inspect.getsource(fixture_module.seed)
    assert "db.add_all(orgs)" in source
    assert "db.add_all(users)" in source
    assert "db.add_all(tenants)" in source
    assert "db.add_all(memberships)" in source
    assert source.count("db.flush()") >= 3
