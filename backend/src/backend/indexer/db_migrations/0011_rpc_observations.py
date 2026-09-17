from yoyo import step

from backend.indexer.observations import OBSERVATION_SCHEMA


def apply(conn):
    for statement in OBSERVATION_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)


steps = [step(apply)]
