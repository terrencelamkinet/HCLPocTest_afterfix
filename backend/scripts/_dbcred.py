"""共用 DB 憑證讀取（2026-09-15 SAST：唔准 hardcode credential）。

憑證唯一來源 = backend/.env 嘅 NEXUS_DATABASE_URL（pgbouncer 6432 同一組 role）。
scripts 用 direct 5432（DDL / 多 statement 唔想經 transaction pool）。
"""
import pathlib

_ENV = pathlib.Path(__file__).resolve().parents[1] / ".env"


def env_value(key: str) -> str:
    for line in _ENV.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{key} 唔喺 {_ENV}（唔會 fallback 去 hardcoded credential）")


def _parts():
    u = env_value("NEXUS_DATABASE_URL").split("://", 1)[1]
    creds, hostpart = u.split("@", 1)
    user, pw = creds.split(":", 1)
    _hostport, db = hostpart.split("/", 1)
    return user, pw, db


def dsn_kwargs(port: int = 5432) -> str:
    """libpq keyword DSN（psycopg / psql 用）。"""
    user, pw, db = _parts()
    return f"host=127.0.0.1 port={port} dbname={db} user={user} password={pw}"


def sync_url(port: int = 5432) -> str:
    """SQLAlchemy sync URL（postgresql://）。"""
    user, pw, db = _parts()
    return f"postgresql://{user}:{pw}@127.0.0.1:{port}/{db}"
