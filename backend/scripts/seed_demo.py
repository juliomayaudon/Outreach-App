"""Fills the database with demo data so you can click around before wiring a
real LinkedIn account:  python -m scripts.seed_demo
"""
from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, Campaign, Invitation, LinkedInAccount, User, utcnow  # noqa: E402
from app.security import encrypt_json, hash_password  # noqa: E402

FIRST_NAMES = ["Ana", "Luis", "Maria", "Carlos", "Sofia", "Diego", "Valentina", "Andres",
               "Camila", "Javier", "Paula", "Tomas", "Elena", "Martin", "Lucia"]
LAST_NAMES = ["Perez", "Gomez", "Rodriguez", "Fernandez", "Lopez", "Diaz", "Torres", "Ramos"]
COMPANIES = ["Northbeam", "Acme Cloud", "Formstack", "Vertice", "Loomly", "Rippling",
             "Basecamp", "Brightwheel", "Chargebee", "Dooly"]
TITLES = ["VP Marketing", "Head of Demand Gen", "CMO", "Director of Growth",
          "Marketing Manager", "Head of ABM"]


def main() -> None:
    Base.metadata.create_all(engine)
    random.seed(7)

    with SessionLocal() as db:
        if db.query(User).filter(User.email == "demo@kalungi.com").first():
            print("Demo data already there.")
            return

        admin = User(
            email="demo@kalungi.com",
            name="Demo",
            password_hash=hash_password("demo12345"),
            role="admin",
            timezone="America/Guayaquil",
        )
        db.add(admin)
        db.flush()

        accounts = []
        for label, daily in (("Julio – Kalungi", 20), ("SDR seat – client A", 15)):
            account = LinkedInAccount(
                owner_id=admin.id,
                label=label,
                linkedin_name=label.split("–")[0].strip(),
                cookies_encrypted=encrypt_json({"li_at": "demo", "JSESSIONID": "ajax:demo"}),
                timezone="America/Guayaquil",
                daily_limit=daily,
                weekly_limit=daily * 5,
                status="active",
            )
            db.add(account)
            accounts.append(account)
        db.flush()

        now = utcnow()
        for index, (name, account, days, volume) in enumerate(
            [
                ("SaaS CMOs – Q3", accounts[0], 300, 14),
                ("Demand gen leads – August", accounts[0], 120, 11),
                ("Client A – ICP list", accounts[1], 60, 9),
            ]
        ):
            campaign = Campaign(
                owner_id=admin.id,
                account_id=account.id,
                name=name,
                status="running" if index == 0 else "completed",
                source_type="sheet" if index == 1 else "csv",
                source_name="icp-list.csv",
                created_at=now - timedelta(days=days),
            )
            db.add(campaign)
            db.flush()

            for day_offset in range(days, 0, -1):
                sent_day = now - timedelta(days=day_offset)
                if sent_day.weekday() >= 5:
                    continue
                for _ in range(random.randint(0, volume)):
                    full_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
                    roll = random.random()
                    status = "sent" if roll < 0.88 else ("failed" if roll < 0.94 else "skipped")
                    db.add(
                        Invitation(
                            campaign_id=campaign.id,
                            account_id=account.id,
                            owner_id=admin.id,
                            profile_id="ACoAA" + str(random.randint(10**9, 10**10)),
                            full_name=full_name,
                            company=random.choice(COMPANIES),
                            title=random.choice(TITLES),
                            status=status,
                            sent_at=sent_day if status == "sent" else None,
                            updated_at=sent_day,
                            error_code="" if status == "sent" else random.choice(
                                ["ALREADY_INVITED", "RATE_LIMIT", "BAD_VMID"]
                            ),
                        )
                    )
            if index == 0:
                for _ in range(46):
                    db.add(
                        Invitation(
                            campaign_id=campaign.id,
                            account_id=account.id,
                            owner_id=admin.id,
                            profile_id="ACoAA" + str(random.randint(10**9, 10**10)),
                            full_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                            company=random.choice(COMPANIES),
                            title=random.choice(TITLES),
                            status="pending",
                        )
                    )
        db.commit()
        print("Demo data ready. Sign in with demo@kalungi.com / demo12345")


if __name__ == "__main__":
    main()
