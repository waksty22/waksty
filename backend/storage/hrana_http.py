"""Read-only Turso backup transport using Hrana HTTP v2 streams.

The HTTP protocol keeps a stateful stream alive with a baton. Requests on a
stream are serialized, so the BEGIN, every SELECT, and COMMIT/ROLLBACK share
one server-side transaction without requiring WebSockets.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


class HranaHttpError(RuntimeError):
    """Credential-safe Hrana HTTP/protocol failure."""

    def __init__(
        self, message: str, *, status: int | None = None, code: str | None = None
    ) -> None:
        super().__init__(message[:160])
        self.message = message[:160]
        self.status = status
        self.code = code


def _pipeline_url(database_url: str) -> str:
    parsed = urlsplit(database_url.strip())
    scheme = {"libsql": "https", "wss": "https"}.get(
        parsed.scheme.lower(), parsed.scheme.lower()
    )
    if scheme != "https" or not parsed.hostname:
        raise ValueError("TURSO_DATABASE_URL doit être une URL libsql:// ou HTTPS.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("TURSO_DATABASE_URL contient des composants non autorisés.")
    path = parsed.path.rstrip("/")
    if path.endswith("/v2/pipeline"):
        endpoint_path = path
    elif path.endswith("/v2"):
        endpoint_path = path + "/pipeline"
    else:
        endpoint_path = path + "/v2/pipeline"
    return urlunsplit((scheme, parsed.netloc, endpoint_path, "", ""))



def database_identity(database_url: str) -> str:
    """Return the normalized database host used as an explicit restore identity."""
    parsed = urlsplit(database_url.strip())
    if parsed.scheme.lower() not in {"libsql", "https"} or not parsed.hostname:
        raise ValueError("URL de base Turso invalide pour identifier la cible.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("URL de base Turso contient des composants interdits.")
    return parsed.hostname.rstrip(".").lower()


def _decode_value(value: dict[str, Any]) -> Any:
    kind = value.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "text":
        return str(value["value"])
    if kind == "blob":
        try:
            return base64.b64decode(value["base64"], validate=True)
        except (KeyError, ValueError, binascii.Error) as exc:
            raise HranaHttpError("Réponse Hrana : blob base64 invalide.") from exc
    raise HranaHttpError("Réponse Hrana : type de valeur inconnu.")


class HranaHttpResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.columns = tuple(
            str(column.get("name") or "") for column in payload.get("cols", [])
        )
        self.rows = [
            tuple(_decode_value(value) for value in row)
            for row in payload.get("rows", [])
        ]


class HranaHttpClient:
    """Small synchronous Hrana HTTP v2 client for one database backup."""

    def __init__(
        self,
        database_url: str,
        auth_token: str,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not auth_token:
            raise ValueError("TURSO_AUTH_TOKEN est requis.")
        self._endpoint = _pipeline_url(database_url)
        self._http = http_client or httpx.Client(timeout=timeout)
        self._headers = {
            "Authorization": "Bearer " + auth_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._closed = False

    def transaction(self) -> "HranaHttpTransaction":
        if self._closed:
            raise HranaHttpError("Client Hrana déjà fermé.")
        return HranaHttpTransaction(self)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._http.close()


class HranaHttpTransaction:
    """A single serialized HTTP stream holding one explicit SQL transaction."""

    def __init__(self, client: HranaHttpClient) -> None:
        self._client = client
        self._baton: str | None = None
        self._active = False
        self._closed = False
        self._execute_control("BEGIN")
        if not self._baton:
            raise HranaHttpError("Turso Hrana n'a pas conservé le flux de transaction.")
        self._active = True

    def _pipeline_with_baton(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise HranaHttpError("Transaction Hrana déjà fermée.")
        try:
            response = self._client._http.post(
                self._client._endpoint,
                headers=self._client._headers,
                json={"baton": self._baton, "requests": requests},
            )
        except httpx.HTTPError as exc:
            self._baton = None
            self._active = False
            self._closed = True
            raise HranaHttpError("Échec de transport HTTP vers Turso Hrana.") from exc
        if response.status_code < 200 or response.status_code >= 300:
            self._baton = None
            self._active = False
            self._closed = True
            raise HranaHttpError(
                "Turso Hrana a refusé la requête HTTP.", status=response.status_code
            )
        try:
            payload = response.json()
        except ValueError as exc:
            self._baton = None
            self._active = False
            self._closed = True
            raise HranaHttpError("Réponse JSON Hrana invalide.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            self._baton = None
            self._active = False
            self._closed = True
            raise HranaHttpError("Réponse Hrana incomplète.")
        next_base = payload.get("base_url")
        if next_base:
            self._client._endpoint = _pipeline_url(str(next_base))
        self._baton = payload.get("baton")
        results = payload["results"]
        if len(results) != len(requests):
            self._baton = None
            self._active = False
            self._closed = True
            raise HranaHttpError("Nombre de résultats Hrana incohérent.")
        return results

    @staticmethod
    def _unwrap(result: dict[str, Any], expected_type: str) -> dict[str, Any]:
        if result.get("type") == "error":
            error = result.get("error") or {}
            message = str(error.get("message") or "Erreur SQL Hrana")
            code = error.get("code")
            raise HranaHttpError(
                message, code=str(code)[:80] if code is not None else None
            )
        response = result.get("response") or {}
        if result.get("type") != "ok" or response.get("type") != expected_type:
            raise HranaHttpError("Réponse d'exécution Hrana inattendue.")
        return response

    def _execute_control(self, sql: str) -> None:
        if sql not in {"BEGIN", "COMMIT", "ROLLBACK"}:
            raise PermissionError("Commande de transaction non autorisée.")
        requests: list[dict[str, Any]] = [
            {"type": "execute", "stmt": {"sql": sql}}
        ]
        if sql in {"COMMIT", "ROLLBACK"}:
            requests.append({"type": "close"})
        results = self._pipeline_with_baton(requests)
        if sql in {"COMMIT", "ROLLBACK"} and self._baton is None:
            self._active = False
            self._closed = True
        self._unwrap(results[0], "execute")
        if sql in {"COMMIT", "ROLLBACK"}:
            if self._baton is not None:
                raise HranaHttpError("Turso Hrana n'a pas fermé le flux après COMMIT/ROLLBACK.")
            if len(results) != 2 or results[1].get("type") != "ok":
                raise HranaHttpError("Fermeture du flux Hrana impossible.")
            self._active = False
            self._closed = True

    def execute(self, sql: str) -> HranaHttpResult:
        if (
            not isinstance(sql, str)
            or not re.match(r"(?i)^SELECT\b", sql.lstrip())
            or ";" in sql
        ):
            raise PermissionError("La sauvegarde Turso n'autorise que des requêtes SELECT uniques.")
        results = self._pipeline_with_baton(
            [{"type": "execute", "stmt": {"sql": sql}}]
        )
        if not self._baton:
            self._active = False
            self._closed = True
            raise HranaHttpError("Turso Hrana a fermé le flux pendant l'export.")
        response = self._unwrap(results[0], "execute")
        return HranaHttpResult(response.get("result") or {})


    def execute_write(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> HranaHttpResult:
        """Execute one parameterized statement inside an explicitly opened transaction.

        This method is deliberately separate from execute(), which remains
        SELECT-only for the backup transport. Transaction control SQL and
        multi-statement payloads are never accepted here.
        """
        if not self._active or self._closed:
            raise HranaHttpError("Transaction Hrana inactive.")
        if (
            not isinstance(sql, str)
            or not sql.strip()
            or ";" in sql
            or re.match(r"(?is)^\\s*(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\\b", sql)
        ):
            raise PermissionError("Instruction SQL de restauration interdite.")
        encoded_args = []
        for value in args:
            if value is None:
                encoded_args.append({"type": "null"})
            elif isinstance(value, bool):
                encoded_args.append({"type": "integer", "value": "1" if value else "0"})
            elif isinstance(value, int):
                encoded_args.append({"type": "integer", "value": str(value)})
            elif isinstance(value, float):
                encoded_args.append({"type": "float", "value": value})
            elif isinstance(value, (bytes, bytearray, memoryview)):
                encoded_args.append({
                    "type": "blob",
                    "base64": base64.b64encode(bytes(value)).decode("ascii"),
                })
            elif isinstance(value, str):
                encoded_args.append({"type": "text", "value": value})
            else:
                raise TypeError("Type de paramètre Hrana non pris en charge.")
        requests = [{
            "type": "execute",
            "stmt": {"sql": sql, "args": encoded_args},
        }]
        results = self._pipeline_with_baton(requests)
        if not self._baton:
            self._active = False
            self._closed = True
            raise HranaHttpError("Turso Hrana a fermé le flux pendant la restauration.")
        response = self._unwrap(results[0], "execute")
        return HranaHttpResult(response.get("result") or {})

    def commit(self) -> None:
        if self._active:
            self._execute_control("COMMIT")

    def rollback(self) -> None:
        if self._active:
            self._execute_control("ROLLBACK")


def open_guarded_restore_transaction(
    database_url: str,
    auth_token: str,
    *,
    expected_target_identity: str,
    production_identity: str,
    http_client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> tuple[HranaHttpClient, HranaHttpTransaction]:
    """Open a write transaction only after exact host identity checks.

    The identity values must be the full normalized Turso database hostnames,
    not display labels or user-provided aliases.
    """
    actual = database_identity(database_url)
    expected = expected_target_identity.strip().lower().rstrip(".")
    production = production_identity.strip().lower().rstrip(".")
    if not expected or actual != expected:
        raise PermissionError("La cible Turso ne correspond pas à l'identité attendue.")
    if not production or actual == production:
        raise PermissionError("La restauration vers la base de production est interdite.")
    client = HranaHttpClient(
        database_url, auth_token, http_client=http_client, timeout=timeout
    )
    try:
        transaction = client.transaction()
    except Exception:
        client.close()
        raise
    return client, transaction
