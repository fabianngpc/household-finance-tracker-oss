import bcrypt

from app.database import SessionLocal


DEFAULT_CATEGORIES = [
    {"name": "Food & Dining",  "color": "#F97316", "icon": "UtensilsCrossed"},
    {"name": "Groceries",      "color": "#22C55E", "icon": "ShoppingCart"},
    {"name": "Transport",      "color": "#3B82F6", "icon": "Car"},
    {"name": "Housing/Rent",   "color": "#8B5CF6", "icon": "Home"},
    {"name": "Utilities",      "color": "#06B6D4", "icon": "Zap"},
    {"name": "Shopping",       "color": "#EC4899", "icon": "ShoppingBag"},
    {"name": "Health",         "color": "#EF4444", "icon": "HeartPulse"},
    {"name": "Entertainment",  "color": "#F59E0B", "icon": "Tv2"},
    {"name": "Travel",         "color": "#14B8A6", "icon": "Plane"},
    {"name": "Other",          "color": "#6B7280", "icon": "Tag", "is_protected": True},
]


def seed_categories_for_user(db, user_id: int) -> None:
    from app.models.category import Category
    for cat_data in DEFAULT_CATEGORIES:
        cat = Category(
            user_id=user_id,
            name=cat_data["name"],
            color=cat_data["color"],
            icon=cat_data["icon"],
            is_protected=1 if cat_data.get("is_protected") else 0,
        )
        db.add(cat)
    db.commit()


def seed_users(db) -> None:
    from app.models.user import User

    users_to_seed = [
        {"username": "alice",  "display_name": "Alice"},
        {"username": "partner", "display_name": "Bob"},
    ]
    for user_data in users_to_seed:
        existing = db.query(User).filter_by(username=user_data["username"]).first()
        if existing:
            continue
        password_hash = bcrypt.hashpw(b"changeme", bcrypt.gensalt()).decode()
        user = User(
            username=user_data["username"],
            display_name=user_data["display_name"],
            password_hash=password_hash,
        )
        db.add(user)
        db.flush()  # get user.id before commit
        seed_categories_for_user(db, user.id)
    db.commit()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_users(db)
        print("Seeded users and categories.")
    finally:
        db.close()
