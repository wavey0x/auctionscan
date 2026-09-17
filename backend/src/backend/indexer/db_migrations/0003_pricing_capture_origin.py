from yoyo import step

from backend.indexer.db_migrations.helpers.schema_v0001 import _ensure_pricing_fact_columns


steps = [step(_ensure_pricing_fact_columns)]
