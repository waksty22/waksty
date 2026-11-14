#!/usr/bin/env python3
"""Full Chappie schema backup/restore E2E. Writes only to approved empty test Turso."""
from __future__ import annotations
import os, secrets, sqlite3, sys, tempfile, zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path[:0] = [str(BACKEND), str(ROOT)]
from scripts.backup_turso import create_backup_archive
from storage.hrana_backup import HranaTransactionConnection, HranaRestoreConnection
from storage.hrana_http import HranaHttpClient, database_identity, open_guarded_restore_transaction
from storage.logical_backup import restore_encrypted_logical_backup, verify_encrypted_logical_backup

EXPECTED = "chappie-test-isolated-chapoue.aws-eu-west-1.turso.io"
def need(ok, message):
    if not ok: raise RuntimeError(message)
def q(s):
    return '"' + s.replace('"', '""') + '"'
def drop(client, objects):
    tx = client.transaction()
    try:
        for kind, name in reversed(objects):
            if kind in ("table","index","view","trigger"):
                tx.execute_write(f"DROP {kind.upper()} IF EXISTS {q(name)}")
        tx.commit()
    except Exception:
        tx.rollback()
        raise

def main():
    url=os.environ.get("CHAPPIE_TEST_TURSO_DATABASE_URL","").strip()
    token=os.environ.get("CHAPPIE_TEST_TURSO_AUTH_TOKEN","").strip()
    prod=os.environ.get("CHAPPIE_PRODUCTION_TURSO_DATABASE_URL","").strip()
    need(bool(url and token and prod),"Missing isolated test credentials or production identity.")
    target, production = database_identity(url), database_identity(prod)
    need(target == EXPECTED and target != production,"Refusing non-approved or production target.")

    with tempfile.TemporaryDirectory(prefix="chappie-full-schema-") as tmp:
        source_path=Path(tmp)/"source.sqlite3"
        os.environ["CHAPPIE_STORAGE_BACKEND"]="sqlite"
        for k in ("TURSO_DATABASE_URL","TURSO_AUTH_TOKEN","CHAPPIE_TEST_TURSO_DATABASE_URL",
                  "CHAPPIE_TEST_TURSO_AUTH_TOKEN","CHAPPIE_PRODUCTION_TURSO_DATABASE_URL",
                  "CHAPPIE_ALLOW_TURSO_MIGRATION","CHAPPIE_TURSO_CUTOVER_READY",
                  "CHAPPIE_TURSO_FRESH_START","CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA"):
            os.environ.pop(k,None)
        import server
        server.DB_PATH=source_path
        server.STORAGE_MIGRATION_PENDING_CUTOVER=False
        server.init_db()
        from tests.test_chappie_schema_logical_backup_restore import _seed_chappie_state
        src=sqlite3.connect(source_path)
        src.execute("PRAGMA foreign_keys=ON")
        _seed_chappie_state(src)
        src.row_factory=sqlite3.Row
        objs=src.execute("""SELECT type,name,sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','index','view','trigger')
            ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'view' THEN 2 ELSE 3 END,name""").fetchall()
        tables=[r["name"] for r in objs if r["type"]=="table"]
        need(len(tables)>=35,"Real Chappie schema has fewer than 35 tables.")
        names=[(r["type"],r["name"]) for r in objs]
        cols={}
        rows={}
        for t in tables:
            cols[t]=[r["name"] for r in src.execute(f"PRAGMA table_xinfo({q(t)})") if r["hidden"]==0]
            rows[t]=[tuple(r) for r in src.execute(f"SELECT {','.join(q(c) for c in cols[t])} FROM {q(t)}")]
        total=sum(map(len,rows.values()))
        need(total>20 and sum(bool(v) for v in rows.values())>=15,"Representative records missing across Chappie tables.")

        client=HranaHttpClient(url,token,timeout=60)
        created=False
        try:
            pre=client.transaction()
            try:
                existing=pre.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','index','view','trigger')").rows
                need(not existing,"Refusing to write: isolated Turso database is not empty.")
                pre.commit()
            except Exception:
                pre.rollback(); raise
            created=True
            tx=client.transaction()
            try:
                # Defer FK checks: Chappie tables can reference rows inserted later.
                tx.execute("PRAGMA defer_foreign_keys=ON")
                for r in objs:
                    if r["type"]=="table":
                        need(bool(r["sql"]),"Missing table DDL.")
                        tx.execute_write(r["sql"])
                for t in tables:
                    if not rows[t]: continue
                    sql=f"INSERT INTO {q(t)} ({','.join(q(c) for c in cols[t])}) VALUES ({','.join('?' for _ in cols[t])})"
                    for row in rows[t]: tx.execute_write(sql,row)
                for r in objs:
                    if r["type"]!="table" and r["sql"]: tx.execute_write(r["sql"])
                tx.commit()
            except Exception:
                tx.rollback(); raise

            with tempfile.TemporaryDirectory(prefix="chappie-full-restore-") as work:
                root=Path(work); archive=root/"full.zip"; key=secrets.token_urlsafe(48)
                btx=client.transaction()
                try:
                    report=create_backup_archive(HranaTransactionConnection(btx),archive,key,manage_snapshot=False)
                    btx.commit()
                except Exception:
                    btx.rollback(); raise
                need(report["encrypted"] and report["verified_after_packaging"],"Encrypted archive verification failed.")
                need(report["table_count"]==len(tables) and report["total_rows"]==total,"Backup counts mismatch.")
                with zipfile.ZipFile(archive) as z:
                    need(set(z.namelist())=={"chappie-turso.json.enc","chappie-turso.json.enc.sha256"},"Unexpected archive members.")
                    z.extractall(root/"unpacked")
                enc=root/"unpacked"/"chappie-turso.json.enc"
                need(verify_encrypted_logical_backup(enc,key).get("valid") is True,"Independent archive verification failed.")
                drop(client,names); created=False
                rc,rtx=open_guarded_restore_transaction(url,token,expected_target_identity=EXPECTED,production_identity=production)
                try:
                    restored=restore_encrypted_logical_backup(HranaRestoreConnection(rtx),enc,key,
                        target_identity=target,expected_target_identity=EXPECTED,production_identity=production)
                    need(restored["restored"] and restored["table_count"]==len(tables) and restored["total_rows"]==total,"Restore summary mismatch.")
                    check=HranaRestoreConnection(rtx)
                    for t in tables:
                        actual=sorted((tuple(r) for r in check.execute(f"SELECT {','.join(q(c) for c in cols[t])} FROM {q(t)}").fetchall()),key=repr)
                        expected=sorted(rows[t],key=repr)
                        need(actual==expected,f"Restored rows differ in {t}.")
                    need(not check.execute("PRAGMA foreign_key_check").fetchall(),"Foreign-key check failed.")
                    rtx.commit(); created=True
                except Exception:
                    rtx.rollback(); raise
                finally: rc.close()
                print(f"FULL_SCHEMA_E2E_SUCCESS target={target} tables={restored['table_count']} rows={restored['total_rows']} encrypted=true archive_verified=true seeded_tables={sum(bool(v) for v in rows.values())} artifact_sha256={restored['artifact_sha256']} foreign_keys=ok")
        finally:
            if created: drop(client,names)
            client.close()
            src.close()
if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"FULL_SCHEMA_E2E_FAILED {type(exc).__name__}: {exc!r}",file=sys.stderr)
        raise SystemExit(1)
