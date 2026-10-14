import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"),
                       "UPLOAD_FOLDER": str(tmp_path / "uploads")})


@pytest.fixture
def client(app):
    return app.test_client()
