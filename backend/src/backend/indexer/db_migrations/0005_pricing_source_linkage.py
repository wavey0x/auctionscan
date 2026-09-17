from yoyo import step

from backend.indexer.db_migrations.helpers.schema_v0001 import _ensure_pricing_source_linkage


steps = [step(_ensure_pricing_source_linkage)]
