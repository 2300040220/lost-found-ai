"""Optional: load demo users and reports so you can try the app immediately.
Run:  python seed_demo.py
Logins created:  owner@demo.com / Demo@1234   and   finder@demo.com / Demo@1234"""
from werkzeug.security import generate_password_hash

from agents.agent_coordinator import coordinator
from app import app
from models import database_models as M

PASSWORD = "Demo@1234"


def user(name, email):
    existing = M.get_user_by_email(email)
    return existing["id"] if existing else M.create_user(name, email, generate_password_hash(PASSWORD))


with app.app_context():
    owner, finder = user("Demo Owner", "owner@demo.com"), user("Demo Finder", "finder@demo.com")
    from datetime import date, timedelta
    d = lambda n: (date.today() - timedelta(days=n)).isoformat()
    coordinator.process_new_report("lost", owner, {
        "item_name": "Black Samsung phone", "category": "Phone", "color": "black", "brand": "Samsung",
        "description": "Black Samsung mobile with a cracked screen and a blue case",
        "date": d(2), "location": "Central library", "contact": "owner@demo.com"})
    coordinator.process_new_report("lost", owner, {
        "item_name": "Brown leather wallet", "category": "Wallet", "color": "brown", "brand": "Fossil",
        "description": "Brown leather wallet with student ID card and some cash",
        "date": d(4), "location": "Bus stand", "contact": "owner@demo.com"})
    res = coordinator.process_new_report("found", finder, {
        "item_name": "Samsung mobile", "category": "Phone", "color": "black", "brand": "Samsung",
        "description": "Found a black Samsung phone with cracked screen near the library",
        "date": d(1), "location": "Library entrance", "contact": "finder@demo.com",
        "secret_details": "lock screen photo of a golden retriever dog"})
    coordinator.process_new_report("found", finder, {
        "item_name": "Red umbrella", "category": "Others", "color": "red", "brand": "",
        "description": "Large red folding umbrella left in the canteen",
        "date": d(1), "location": "Canteen", "contact": "finder@demo.com"})
    print("Demo data loaded. Matches created for the phone:", len(res["matches"]))
