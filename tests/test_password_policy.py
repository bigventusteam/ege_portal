"""
Parola politikası — en az 12 karakter, en çok 72 BAYT (bcrypt sınırı,
bkz. app/security.py::validate_password_policy). `POST /api/v1/auth/
register` üzerinden (pydantic validator, app/routers/auth.py::
RegisterRequest) ve `scripts/personel_olustur.py` üzerinden uygulanır.
"""
from app.security import PasswordPolicyError, validate_password_policy


def test_kisa_parola_kayitta_422_doner(client):
    resp = client.post(
        "/api/v1/auth/register", json={"customer_name": "X", "email": "kisa@example.com", "password": "kisa1234567"}
    )
    assert resp.status_code == 422


def test_tam_12_karakter_kabul_edilir(client):
    resp = client.post(
        "/api/v1/auth/register", json={"customer_name": "X", "email": "tam12@example.com", "password": "123456789012"}
    )
    assert resp.status_code == 201


def test_72_bayttan_uzun_parola_422_doner(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"customer_name": "X", "email": "cokuzun@example.com", "password": "a" * 100},
    )
    assert resp.status_code == 422


def test_tam_72_bayt_kabul_edilir(client):
    resp = client.post(
        "/api/v1/auth/register", json={"customer_name": "X", "email": "tam72@example.com", "password": "a" * 72}
    )
    assert resp.status_code == 201


def test_validate_password_policy_dogrudan():
    validate_password_policy("a" * 12)  # alt sınır — hata atmaz
    validate_password_policy("a" * 72)  # üst sınır — hata atmaz
    try:
        validate_password_policy("a" * 11)
        assert False, "kısa parola reddedilmeliydi"
    except PasswordPolicyError:
        pass
    try:
        validate_password_policy("a" * 73)
        assert False, "uzun parola reddedilmeliydi"
    except PasswordPolicyError:
        pass
