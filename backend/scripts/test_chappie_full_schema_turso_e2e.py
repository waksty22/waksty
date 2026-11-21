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
def drop(client, objects, table_dependencies):
    """Remove only fixture objects, dropping dependent tables before parents."""
    tables = {name for kind, name in objects if kind == "table"}
    children = {name: set() for name in tables}
    for child, parents in table_dependencies.items():
        if child in tables:
            for parent in parents:
                if parent in tables and parent != child:
                    children[parent].add(child)
                elif parent == child:
                    raise RuntimeError(f"Refusing cleanup: self-referencing table {child}.")
    ordered_tables = []
    visiting, visited = set(), set()
    def visit(table):
        if table in visiting:
            raise RuntimeError("Refusing cleanup: cyclic foreign-key dependencies in fixture.")
        if table in visited:
            return
        visiting.add(table)
        for child in sorted(children[table]):
            visit(child)
        visiting.remove(table)
        visited.add(table)
        ordered_tables.append(table)
    for table in sorted(tables):
        visit(table)
    # Non-table objects are removed first; table order is child-before-parent.
    ordered = [(kind, name) for kind, name in objects if kind != "table"]
    ordered.extend(("table", name) for name in ordered_tables)
    tx = client.transaction()
    try:
        for kind, name in ordered:
            if kind in ("table", "index", "view", "trigger"):
                tx.execute_write(f"DROP {kind.upper()} IF EXISTS {q(name)}")
        tx.commit()
    except Exception:
        tx.rollback()
        raise

def assert_empty(client):
    """Confirm cleanup left no user-owned schema objects in the isolated database."""
    tx = client.transaction()
    try:
        remaining = tx.execute(
            "SELECT type,name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "AND type IN ('table','index','view','trigger')"
        ).rows
        tx.commit()
    except Exception:
        tx.rollback()
        raise
    need(not remaining, "Isolated Turso cleanup left schema objects: " + repr(remaining[:10]))

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
        print("E2E_STAGE local_seed_start", flush=True)
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
        table_dependencies = {
            table: {
                str(fk[2]) for fk in src.execute(f"PRAGMA foreign_key_list({q(table)})")
                if fk[2]
            }
            for table in tables
        }
        cols={}
        rows={}
        for t in tables:
            cols[t]=[r["name"] for r in src.execute(f"PRAGMA table_xinfo({q(t)})") if r["hidden"]==0]
            rows[t]=[tuple(r) for r in src.execute(f"SELECT {','.join(q(c) for c in cols[t])} FROM {q(t)}")]
        total=sum(map(len,rows.values()))
        print(f"E2E_STAGE local_seed_complete tables={len(tables)} rows={total}", flush=True)
        need(total>20 and sum(bool(v) for v in rows.values())>=15,"Representative records missing across Chappie tables.")

        client=HranaHttpClient(url,token,timeout=60)
        created=False
        try:
            pre=client.transaction()
            try:
                existing=pre.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','index','view','trigger')").rows
                expected_objects={(kind,name) for kind,name in names}
                existing_objects=[(str(row[0]),str(row[1])) for row in existing]
                unexpected=[item for item in existing_objects if item not in expected_objects]
                need(not unexpected,
                     "Refusing cleanup: isolated Turso contains objects outside this exact Chappie fixture: "
                     + repr(unexpected[:10]))
                pre.commit()
                if existing_objects:
                    print(f"E2E_STAGE stale_fixture_cleanup objects={len(existing_objects)}", flush=True)
                    drop(client, existing_objects, table_dependencies)
                    assert_empty(client)
                    print("E2E_STAGE stale_fixture_cleanup_complete", flush=True)
            except Exception:
                pre.rollback(); raise
            created=True
            print("E2E_STAGE turso_seed_start", flush=True)
            tx=client.transaction()
            try:
                # Defer FK checks: Chappie tables can reference rows inserted later.
                tx.execute_write("PRAGMA defer_foreign_keys=ON")
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
                # Force a sequence value well above the largest seeded row.
                # The encrypted export must preserve sqlite_sequence, not just
                # the current records, or the next Chappie memory ID can collide.
                tx.execute_write(
                    "UPDATE sqlite_sequence SET seq=? WHERE name=?",
                    (9000, "memories_v19"),
                )
                sequence_rows = tx.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='memories_v19'"
                ).rows
                need(
                    sequence_rows and int(sequence_rows[0][0]) == 9000,
                    "Could not establish the remote AUTOINCREMENT fixture.",
                )
                tx.commit()
                print("E2E_STAGE turso_seed_commit_ok sequence=9000", flush=True)
            except Exception:
                tx.rollback(); raise

            with tempfile.TemporaryDirectory(prefix="chappie-full-restore-") as work:
                root=Path(work); archive=root/"full.zip"; key=secrets.token_urlsafe(48)
                btx=client.transaction()
                try:
                    report=create_backup_archive(HranaTransactionConnection(btx),archive,key,manage_snapshot=False)
                    btx.commit()
                    print("E2E_STAGE backup_commit_ok", flush=True)
                except Exception:
                    btx.rollback(); raise
                need(report["encrypted"] and report["verified_after_packaging"],"Encrypted archive verification failed.")
                need(report["table_count"]==len(tables) and report["total_rows"]==total,"Backup counts mismatch.")
                with zipfile.ZipFile(archive) as z:
                    need(set(z.namelist())=={"chappie-turso.json.enc","chappie-turso.json.enc.sha256"},"Unexpected archive members.")
                    z.extractall(root/"unpacked")
                enc=root/"unpacked"/"chappie-turso.json.enc"
                need(verify_encrypted_logical_backup(enc,key).get("valid") is True,"Independent archive verification failed.")

                # A valid restore must refuse a populated database without
                # changing even one row. Exercise that guard on real Turso.
                guard_client, guard_tx = open_guarded_restore_transaction(
                    url, token, expected_target_identity=EXPECTED,
                    production_identity=production,
                )
                try:
                    guard_connection = HranaRestoreConnection(guard_tx)
                    try:
                        restore_encrypted_logical_backup(
                            guard_connection, enc, key,
                            target_identity=target,
                            expected_target_identity=EXPECTED,
                            production_identity=production,
                        )
                    except PermissionError as exc:
                        need(
                            "n'est pas vide" in str(exc).lower(),
                            "Populated-target restore failed for an unexpected reason.",
                        )
                        guard_tx.rollback()
                        print("E2E_STAGE populated_target_refusal_verified", flush=True)
                    else:
                        guard_tx.rollback()
                        raise RuntimeError("Restore unexpectedly accepted a populated Turso target.")
                except Exception:
                    if guard_tx._active:
                        guard_tx.rollback()
                    raise
                finally:
                    guard_client.close()

                # Reopen again and prove the rejected operation preserved data.
                client.close()
                client = HranaHttpClient(url, token, timeout=60)
                preserve_tx = client.transaction()
                try:
                    preserve_check = HranaRestoreConnection(preserve_tx)
                    for t in tables:
                        count = preserve_check.execute(
                            f"SELECT COUNT(*) FROM {q(t)}"
                        ).fetchone()[0]
                        need(
                            count == len(rows[t]),
                            f"Populated-target refusal changed row count in {t}.",
                        )
                    preserve_tx.commit()
                    print(
                        f"E2E_STAGE populated_target_preserved tables={len(tables)} rows={total}",
                        flush=True,
                    )
                except Exception:
                    preserve_tx.rollback()
                    raise

                print("E2E_STAGE backup_verified_drop_start", flush=True)
                drop(client,names,table_dependencies); created=False
                print("E2E_STAGE drop_complete_restore_start", flush=True)
                rc,rtx=open_guarded_restore_transaction(url,token,expected_target_identity=EXPECTED,production_identity=production)
                try:
                    restored=restore_encrypted_logical_backup(HranaRestoreConnection(rtx),enc,key,
                        target_identity=target,expected_target_identity=EXPECTED,production_identity=production)
                    print("E2E_STAGE restore_function_complete", flush=True)
                    need(restored["restored"] and restored["table_count"]==len(tables) and restored["total_rows"]==total,"Restore summary mismatch.")
                    check=HranaRestoreConnection(rtx)
                    for t in tables:
                        actual=sorted((tuple(r) for r in check.execute(f"SELECT {','.join(q(c) for c in cols[t])} FROM {q(t)}").fetchall()),key=repr)
                        expected=sorted(rows[t],key=repr)
                        need(actual==expected,f"Restored rows differ in {t}.")
                    # Verify that restoring the encrypted backup preserved
                    # the remote AUTOINCREMENT high-water mark, even though the
                    # largest currently stored row ID is much smaller.
                    check.execute(
                        """INSERT INTO memories_v19
                           (user_id,category,content,importance,source_type,
                            confidence,tags,access_count,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        ("creator", "e2e", "remote-sequence-probe", 1, "taught",
                         0.8, "[]", 0, "2026-11-20T00:00:00Z",
                         "2026-11-20T00:00:00Z"),
                    )
                    sequence_probe = check.execute(
                        "SELECT id FROM memories_v19 WHERE user_id=? AND content=?",
                        ("creator", "remote-sequence-probe"),
                    ).rows
                    need(
                        sequence_probe and int(sequence_probe[0][0]) == 9001,
                        "Restored Turso AUTOINCREMENT sequence was not preserved.",
                    )
                    check.execute(
                        "DELETE FROM memories_v19 WHERE user_id=? AND content=?",
                        ("creator", "remote-sequence-probe"),
                    )
                    need(not check.execute("PRAGMA foreign_key_check").fetchall(),"Foreign-key check failed.")
                    rtx.commit(); created=True
                except Exception:
                    rtx.rollback(); raise
                finally: rc.close()

                # Prove durability across a genuinely new HTTP client and Hrana stream.
                client.close()
                client = HranaHttpClient(url, token, timeout=60)
                reconnect_tx = client.transaction()
                try:
                    reconnect_check = HranaRestoreConnection(reconnect_tx)
                    for t in tables:
                        actual_rows = sorted(
                            (tuple(row) for row in reconnect_check.execute(
                                f"SELECT {','.join(q(c) for c in cols[t])} FROM {q(t)}"
                            ).fetchall()),
                            key=repr,
                        )
                        need(
                            actual_rows == sorted(rows[t], key=repr),
                            f"Data not durable after remote reconnect in {t}.",
                        )
                    sequence_after_reconnect = reconnect_check.execute(
                        "SELECT seq FROM sqlite_sequence WHERE name='memories_v19'"
                    ).rows
                    need(
                        sequence_after_reconnect
                        and int(sequence_after_reconnect[0][0]) == 9001,
                        "AUTOINCREMENT sequence was not durable after remote reconnect.",
                    )
                    need(
                        not reconnect_check.execute("PRAGMA foreign_key_check").fetchall(),
                        "Foreign-key check failed after remote reconnect.",
                    )
                    reconnect_tx.commit()
                    print(
                        f"E2E_STAGE remote_reconnect_verified tables={len(tables)} rows={total} autoincrement=9001",
                        flush=True,
                    )
                except Exception:
                    reconnect_tx.rollback()
                    raise


                # Exercise the actual production libsql adapter against the
                # isolated remote database, not only the Hrana backup client.
                from storage.connection_factory import StorageSettings, open_storage_connection
                probe = "chappie_libsql_adapter_probe_" + secrets.token_hex(6)
                names.append(("table", probe))
                table_dependencies[probe] = set()
                adapter_settings = StorageSettings(
                    backend="turso",
                    turso_database_url=url,
                    turso_auth_token=token,
                )
                adapter = open_storage_connection(adapter_settings)
                try:
                    adapter.execute(
                        f"CREATE TABLE {q(probe)} "
                        "(id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)"
                    )
                    adapter.commit()
                    inserted = adapter.execute(
                        f"INSERT INTO {q(probe)}(value) VALUES (?)",
                        ("native-libsql-adapter",),
                    )
                    need(inserted.rowcount == 1, "Native libsql adapter INSERT rowcount mismatch.")
                    need(inserted.lastrowid == 1, "Native libsql adapter lastrowid mismatch.")
                    adapter.commit()
                    adapter.execute(
                        f"INSERT INTO {q(probe)}(value) VALUES (?)",
                        ("must-rollback",),
                    )
                    adapter.rollback()
                finally:
                    adapter.close()

                # A fresh native libsql connection must observe the committed
                # row and not the rolled-back row.
                adapter = open_storage_connection(adapter_settings)
                try:
                    probe_rows = adapter.execute(
                        f"SELECT id, value FROM {q(probe)} ORDER BY id"
                    ).fetchall()
                    need(
                        [(row["id"], row["value"]) for row in probe_rows]
                        == [(1, "native-libsql-adapter")],
                        "Native libsql adapter reconnect/rollback contract failed.",
                    )
                    adapter.execute(f"DROP TABLE {q(probe)}")
                    adapter.commit()
                    print(
                        "E2E_STAGE native_libsql_adapter_remote_verified "
                        "rowcount=true lastrowid=true rollback=true reconnect=true",
                        flush=True,
                    )
                finally:
                    adapter.close()

                success_message = (f"FULL_SCHEMA_E2E_SUCCESS target={target} tables={restored['table_count']} rows={restored['total_rows']} encrypted=true archive_verified=true seeded_tables={sum(bool(v) for v in rows.values())} remote_reconnect_verified=true artifact_sha256={restored['artifact_sha256']} foreign_keys=ok")
        finally:
            try:
                if created:
                    drop(client, names, table_dependencies)
                    assert_empty(client)
                    print("E2E_STAGE final_cleanup_verified", flush=True)
            finally:
                client.close()
                src.close()
        print(success_message, flush=True)
if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"FULL_SCHEMA_E2E_FAILED {type(exc).__name__}: {exc!r}",file=sys.stderr)
        raise SystemExit(1)
