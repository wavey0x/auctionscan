from yoyo import step

from backend.indexer.db_migrations.helpers.schema_v0001 import ensure_current_schema


steps = [step(ensure_current_schema)]
