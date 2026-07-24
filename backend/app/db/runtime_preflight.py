from app.db.database import assert_configured_worker_database_role


def main() -> None:
    """Fail before worker processes start when their database role can bypass tenant RLS."""

    assert_configured_worker_database_role()


if __name__ == "__main__":
    main()
