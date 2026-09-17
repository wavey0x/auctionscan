from yoyo import step


LOGO_COLUMNS = ("logo_url", "logo_source", "logo_checked_at")


def drop_token_logo_projection_columns(conn) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(tokens)").fetchall()
    }
    for column in LOGO_COLUMNS:
        if column in columns:
            conn.execute(f"ALTER TABLE tokens DROP COLUMN {column}")


steps = [step(drop_token_logo_projection_columns)]
