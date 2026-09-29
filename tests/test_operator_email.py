"""Regression: the same email must be allowed across different operators,
but only one platform-owner row per email is allowed."""
import os
import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from sqlalchemy.exc import IntegrityError
from app import create_app
from app.extensions import db
from app.models import User, UserRole, Operator, OperatorStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _make_operator(slug: str) -> Operator:
    t = Operator(slug=slug, name=slug.title(), primary_domain=f"{slug}.example.com",
               status=OperatorStatus.ACTIVE)
    db.session.add(t)
    db.session.commit()
    return t


def test_same_email_allowed_across_operators():
    app = _app()
    with app.app_context():
        adyar = _make_operator("adyar")
        winn = _make_operator("winnspace")

        u1 = User(operator_id=adyar.id, email="john@gmail.com",
                  full_name="John A", role=UserRole.INDIVIDUAL, is_active=True)
        u1.set_password("pw")
        db.session.add(u1)
        db.session.commit()

        u2 = User(operator_id=winn.id, email="john@gmail.com",
                  full_name="John W", role=UserRole.INDIVIDUAL, is_active=True)
        u2.set_password("pw")
        db.session.add(u2)
        db.session.commit()

        rows = User.query.filter_by(email="john@gmail.com") \
                          .execution_options(skip_operator_filter=True).all()
        assert len(rows) == 2
        assert {r.operator_id for r in rows} == {adyar.id, winn.id}


def test_same_email_same_operator_rejected():
    app = _app()
    with app.app_context():
        adyar = _make_operator("adyar")
        u1 = User(operator_id=adyar.id, email="dup@example.com",
                  full_name="One", role=UserRole.INDIVIDUAL, is_active=True)
        u1.set_password("pw")
        db.session.add(u1)
        db.session.commit()

        u2 = User(operator_id=adyar.id, email="dup@example.com",
                  full_name="Two", role=UserRole.INDIVIDUAL, is_active=True)
        u2.set_password("pw")
        db.session.add(u2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_platform_owner_email_globally_unique():
    app = _app()
    with app.app_context():
        po1 = User(email="platform@coworkhub.io", full_name="PO1",
                   role=UserRole.PLATFORM_OWNER, is_active=True)
        po1.set_password("pw")
        db.session.add(po1)
        db.session.commit()

        po2 = User(email="platform@coworkhub.io", full_name="PO2",
                   role=UserRole.PLATFORM_OWNER, is_active=True)
        po2.set_password("pw")
        db.session.add(po2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
