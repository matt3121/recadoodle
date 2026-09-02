from werkzeug.security import check_password_hash

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account, PlatformAccountLink


def test_api_only_and_fresh_database(tmp_path):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "fresh.db"}',
                      'JWT_SECRET': 'test-secret-longer-than-thirty-two-bytes'})
    client = app.test_client()
    assert client.get('/', headers={'Accept': 'text/html'}).is_json
    for route in ('/admin', '/admin/login', '/credits', '/status', '/discovery', '/static/site.css'):
        assert client.get(route).status_code == 404
    assert client.get('/healthz').status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Account)) == 1
        assert db.session.scalar(db.select(db.func.count()).select_from(PlatformAccountLink)) == 0
        assert not check_password_hash(db.session.get(Account, 1).password_hash, 'disabled-system-account')
