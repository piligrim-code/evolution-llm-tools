"""Immutable local versions, separate from both review receipts and the legacy registry."""
from contextlib import closing, contextmanager
import re
import sqlite3

from .container_runner import ContainerPolicy
from .contracts import json_object
from .execution_policy import normalized_tool_name, reject_linked_path
from .output_contracts import validate_output
from .review import DOCUMENT_LIMIT, _digest, _document, _json, _proposal_id

APPLICATION_ID = 0x54574331


class CatalogError(ValueError):
    pass


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise CatalogError('explicit_full_version_required')
    return value


class VersionCatalog:
    def __init__(self, path='.mcp/versions.sqlite3', *, read_only=False):
        if type(read_only) is not bool:
            raise CatalogError('read_only_must_be_boolean')
        self.path, self.read_only = reject_linked_path(path), read_only
        if read_only:
            if not self.path.is_file():
                raise CatalogError('catalog_not_found')
            with self._connection() as db:
                self._check_schema(db)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            app = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            occupied = db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone()
            if app == 0 and version == 0 and occupied is None:
                db.execute('''CREATE TABLE versions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL, version TEXT NOT NULL,
                    record TEXT NOT NULL, record_digest TEXT NOT NULL,
                    UNIQUE(name, version))''')
                db.execute('''CREATE TRIGGER versions_no_update BEFORE UPDATE ON versions
                    BEGIN SELECT RAISE(ABORT, 'catalog_versions_are_immutable'); END''')
                db.execute('''CREATE TRIGGER versions_no_delete BEFORE DELETE ON versions
                    BEGIN SELECT RAISE(ABORT, 'catalog_versions_are_immutable'); END''')
                db.execute('PRAGMA application_id=' + str(APPLICATION_ID))
                db.execute('PRAGMA user_version=1')
            self._check_schema(db)

    @staticmethod
    def _check_schema(db):
        if (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                or db.execute('PRAGMA user_version').fetchone()[0] != 1):
            raise CatalogError('not_a_supported_version_catalog')
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
        if not {'versions', 'versions_no_update', 'versions_no_delete'} <= names:
            raise CatalogError('catalog_schema_incomplete')

    @contextmanager
    def _connection(self):
        for suffix in ('', '-journal', '-wal', '-shm'):
            reject_linked_path(str(self.path) + suffix)
        target = self.path.as_uri() + '?mode=ro' if self.read_only else self.path
        with closing(sqlite3.connect(target, uri=self.read_only, timeout=5, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA query_only=ON' if self.read_only else 'PRAGMA synchronous=FULL')
            yield db

    @contextmanager
    def _transaction(self):
        if self.read_only:
            raise PermissionError('catalog_is_read_only')
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _load(self, db, name, version):
        row = db.execute('SELECT * FROM versions WHERE name=? AND version=?', (name, version)).fetchone()
        if row is None:
            raise CatalogError('version_not_found')
        record = json_object(row['record'], limit=DOCUMENT_LIMIT)
        if _digest(_json(record)) != row['record_digest']:
            raise CatalogError('version_record_changed')
        if (set(record) != {'format', 'proposal_id', 'document', 'result'}
                or record['format'] != 'toolwright-version-v1'):
            raise CatalogError('invalid_version_record')
        _proposal_id(record['proposal_id'])
        doc = record['document']
        if (not isinstance(doc, dict) or doc.get('version') != 2 or not isinstance(doc.get('spec'), dict)
                or doc['spec'].get('name') != name or not isinstance(record['result'], dict)
                or _digest(_json(doc)) != version):
            raise CatalogError('version_document_changed')
        return {'name': name, 'version': version, 'sequence': row['sequence'], 'record': record}

    def promote(self, reviews, proposal_id, *, confirm=False):
        if confirm is not True:
            raise PermissionError('explicit_promotion_confirmation_required')
        snapshot = reviews.validated_snapshot(proposal_id)
        name = normalized_tool_name(snapshot['document']['spec']['name'])
        version = _version(snapshot['digest'])
        # Keep the first validated provenance. Re-promoting identical content is
        # idempotent and cannot overwrite it with another proposal's receipt.
        record = {'format': 'toolwright-version-v1', 'proposal_id': snapshot['id'],
                  'document': snapshot['document'], 'result': snapshot['result']}
        encoded = _json(record)
        with self._transaction() as db:
            if db.execute('SELECT 1 FROM versions WHERE name=? AND version=?', (name, version)).fetchone():
                existing = self._load(db, name, version)
                return {'promoted': False, 'name': name, 'version': version, 'sequence': existing['sequence']}
            cursor = db.execute('INSERT INTO versions(name,version,record,record_digest) VALUES(?,?,?,?)',
                                (name, version, encoded, _digest(encoded)))
            return {'promoted': True, 'name': name, 'version': version, 'sequence': cursor.lastrowid}

    def inspect(self, name, version):
        name, version = normalized_tool_name(name), _version(version)
        with self._connection() as db:
            return {**self._load(db, name, version), 'integrity_checked': True, 'execution_authorized': False}

    def list(self, *, name=None, limit=20, before=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CatalogError('invalid_list_limit')
        if before is not None and (type(before) is not int or not 1 <= before <= 2**63 - 1):
            raise CatalogError('invalid_list_cursor')
        clauses, args = [], []
        if name is not None:
            clauses.append('name=?')
            args.append(normalized_tool_name(name))
        with self._connection() as db:
            db.execute('BEGIN')
            if before is not None:
                if db.execute('SELECT 1 FROM versions WHERE sequence=?', (before,)).fetchone() is None:
                    raise CatalogError('list_cursor_not_found')
                clauses.append('sequence<?')
                args.append(before)
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            rows = db.execute('SELECT name,version,sequence FROM versions' + where +
                              ' ORDER BY sequence DESC LIMIT ?', (*args, limit + 1)).fetchall()
            items = []
            for row in rows[:limit]:
                if normalized_tool_name(row['name']) != row['name']:
                    raise CatalogError('invalid_version_name')
                _version(row['version'])
                items.append(dict(row))
            return {'versions': items, 'count': len(items),
                    'next_cursor': items[-1]['sequence'] if len(rows) > limit else None,
                    'content_included': False, 'integrity_checked': False}

    def prepare(self, name, version, reviews, *, args=None, output_contract=None):
        """Copy a selected version into a fresh PENDING proposal; never execute."""
        if (args is None) != (output_contract is None):
            raise CatalogError('new_arguments_require_new_output_contract')
        selected = self.inspect(name, version)
        doc, result = selected['record']['document'], selected['record']['result']
        try:
            policy = ContainerPolicy(doc['policy']['image'], doc['policy']['timeout'])
            current = _document(doc['spec'], doc['scripts'], doc['args'], policy,
                                output_contract=doc['output_contract'])
        except (KeyError, TypeError):
            raise CatalogError('invalid_version_document') from None
        if _json(current) != _json(doc):
            raise CatalogError('version_policy_or_contract_changed')
        validation = validate_output(doc['output_contract'], result)
        if ('error' in result or validation['status'] != 'passed'
                or result.get('output_validation') != validation):
            raise CatalogError('version_receipt_not_validated')
        identifier = reviews.create(doc['spec'], doc['scripts'], doc['args'] if args is None else args, policy,
                                    output_contract=doc['output_contract'] if output_contract is None else output_contract)
        return {'id': identifier, 'state': 'pending', 'source_name': selected['name'],
                'source_version': selected['version']}
