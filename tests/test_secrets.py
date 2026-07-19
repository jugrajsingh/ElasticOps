from backend.services import secrets as secrets_mod


def test_encrypt_decrypt_round_trips():
    token = secrets_mod.encrypt("hunter2")
    assert token != "hunter2"
    assert secrets_mod.decrypt(token) == "hunter2"


def test_empty_password_is_passthrough():
    assert secrets_mod.encrypt("") == ""
    assert secrets_mod.decrypt("") == ""


def test_jwt_secret_uses_configured_override():
    # conftest sets AUTH__JWT_SECRET=test-jwt-secret-with-at-least-32-bytes!
    assert secrets_mod.get_jwt_secret() == "test-jwt-secret-with-at-least-32-bytes!"


def test_create_token_uses_runtime_secret():
    import jwt

    from backend.auth import create_access_token

    token = create_access_token({"sub": "a@b.com"})
    decoded = jwt.decode(token, "test-jwt-secret-with-at-least-32-bytes!", algorithms=["HS256"])
    assert decoded["sub"] == "a@b.com"
