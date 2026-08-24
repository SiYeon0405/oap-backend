from app.services.admin_read_service import AdminReadService


def main() -> int:
    cutoff = AdminReadService().refresh_aggregates()
    print(cutoff.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
