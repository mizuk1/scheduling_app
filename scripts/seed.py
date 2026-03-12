from sqlmodel import Session

from app.db.init_db import init_db
from app.db.session import engine
from app.seed.seed_data import seed_db


def main() -> None:
    init_db()
    with Session(engine) as session:
        seed_db(session)
        session.commit()
    print("Seed completed.")


if __name__ == "__main__":
    main()
