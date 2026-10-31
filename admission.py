"""Evidence-gated admission: held-out cases decide, generation never sees them.

A candidate (spec, scripts, policy) is admitted for a corpus-v2 task only if one
identical candidate passed every example and every held-out case, as shown by
finished, approved receipts. Every scoring of held-out receipts is recorded in an
append-only ledger before its outcome is returned, because looking at held-out
results is itself a use of them. The number of distinct candidates per task is
budgeted. Results expose only how many held-out cases passed, never which, so a
repair step cannot learn from them. Nothing here generates, approves or executes.
"""
from contextlib import closing, contextmanager
import sqlite3

from .contracts import json_object
from .evaluation import _case_score
from .evaluation_corpus import task_spec
from .evaluation_corpus_v2 import CORPUS_VERSION, corpus_digest, get_case, get_task
from .execution_policy import reject_linked_path
from .review import DOCUMENT_LIMIT, _digest, _json, _proposal_id

APPLICATION_ID = 0x54574144
DEFAULT_CANDIDATE_LIMIT = 3


class AdmissionError(ValueError):
    pass


def prepare_admission_case(task_id, case_id, scripts, policy, reviews):
    """Create one pending corpus-v2 proposal; inspection and approval stay separate."""
    task, case = get_case(task_id, case_id)
    identifier = reviews.create(task_spec(task), scripts, case['args'], policy,
                                output_contract={'kind': 'json-object-equals', 'expected': case['expected']})
    return {'task_id': task_id, 'case_id': case_id, 'split': case['split'], 'proposal_id': identifier,
            'corpus_sha256': corpus_digest(), 'state': 'pending', 'execution_authorized': False}


class AdmissionLedger:
    def __init__(self, path='.mcp/admissions.sqlite3', *, candidate_limit=DEFAULT_CANDIDATE_LIMIT):
        if type(candidate_limit) is not int or not 1 <= candidate_limit <= 20:
            raise AdmissionError('invalid_candidate_limit')
        self.path, self.candidate_limit = reject_linked_path(path), candidate_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            app = db.execute('PRAGMA application_id').fetchone()[0]
            occupied = db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone()
            if app == 0 and occupied is None:
                db.execute('''CREATE TABLE attempts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    corpus_sha256 TEXT NOT NULL, task_id TEXT NOT NULL, candidate_sha256 TEXT NOT NULL,
                    admitted INTEGER NOT NULL, record TEXT NOT NULL, record_digest TEXT NOT NULL,
                    UNIQUE(corpus_sha256, task_id, candidate_sha256))''')
                for operation in ('UPDATE', 'DELETE'):
                    db.execute(f'''CREATE TRIGGER attempts_no_{operation.lower()} BEFORE {operation} ON attempts
                        BEGIN SELECT RAISE(ABORT, 'admission_attempts_are_immutable'); END''')
                db.execute('PRAGMA application_id=' + str(APPLICATION_ID))
                db.execute('PRAGMA user_version=1')
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','trigger')")}
            if (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                    or not {'attempts', 'attempts_no_update', 'attempts_no_delete'} <= names):
                raise AdmissionError('not_an_admission_ledger')

    @contextmanager
    def _transaction(self):
        for suffix in ('', '-journal', '-wal', '-shm'):
            reject_linked_path(str(self.path) + suffix)
        with closing(sqlite3.connect(self.path, timeout=5, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _summary(record, sequence, *, recorded):
        held = record['held_out']
        return {'task_id': record['task_id'], 'corpus_version': CORPUS_VERSION,
                'admitted': record['admitted'], 'attempt': sequence, 'newly_recorded': recorded,
                'examples': record['examples'],
                'held_out_passed': sum(status == 'correct' for status in held.values()),
                'held_out_total': len(held), 'candidate_sha256': record['candidate_sha256'],
                'held_out_details_included': False, 'execution_authorized': False}

    def evaluate(self, reviews, task_id, assignments, *, expected_corpus_sha256):
        """Score receipts for every case of one task and record the attempt once."""
        if expected_corpus_sha256 != corpus_digest():
            raise AdmissionError('admission_corpus_mismatch')
        task = get_task(task_id)
        if task['kind'] != 'tool':
            raise AdmissionError('admission_requires_tool_task')
        if type(assignments) is not list or len(assignments) != len(task['cases']):
            raise AdmissionError('admission_requires_every_case')
        selected = {}
        for entry in assignments:
            if type(entry) is not dict or set(entry) != {'case_id', 'proposal_id'}:
                raise AdmissionError('invalid_admission_assignment')
            get_case(task_id, entry['case_id'])
            identifier = _proposal_id(entry['proposal_id'])
            if entry['case_id'] in selected or identifier in selected.values():
                raise AdmissionError('duplicate_admission_assignment')
            selected[entry['case_id']] = identifier
        with reviews._connection() as review_db:
            review_db.execute('BEGIN')
            rows = [_case_score(review_db, reviews, task, case, selected[case['id']]) for case in task['cases']]
        identities = {row['candidate_sha256'] for row in rows}
        if None in identities or len(identities) != 1:
            # Unbound or mixed receipts are refused before any held-out outcome is recorded.
            raise AdmissionError('admission_requires_one_bound_candidate')
        if any(row['status'] in ('not_run', 'indeterminate') for row in rows):
            # Incomplete evidence must not consume the held-out budget.
            raise AdmissionError('admission_requires_finished_receipts')
        candidate = identities.pop()
        examples = {row['case_id']: row['status'] for row in rows if row['split'] == 'example'}
        held_out = {row['case_id']: row['status'] for row in rows if row['split'] == 'held-out'}
        admitted = all(status == 'correct' for status in [*examples.values(), *held_out.values()])
        record = {'format': 'toolwright-admission-v1', 'corpus_version': CORPUS_VERSION,
                  'corpus_sha256': corpus_digest(), 'task_id': task_id, 'candidate_sha256': candidate,
                  'admitted': admitted, 'examples': examples, 'held_out': held_out,
                  'proposals': selected, 'promotion_case_id': task['cases'][0]['id']}
        with self._transaction() as db:
            existing = db.execute('SELECT sequence, record, record_digest FROM attempts '
                                  'WHERE corpus_sha256=? AND task_id=? AND candidate_sha256=?',
                                  (corpus_digest(), task_id, candidate)).fetchone()
            if existing is not None:
                # Re-scoring the same candidate returns its first decision and uses no budget.
                return self._summary(self._checked(existing), existing['sequence'], recorded=False)
            used = db.execute('SELECT COUNT(*) FROM attempts WHERE corpus_sha256=? AND task_id=?',
                              (corpus_digest(), task_id)).fetchone()[0]
            if used >= self.candidate_limit:
                raise PermissionError('held_out_candidate_budget_exhausted')
            encoded = _json(record)
            cursor = db.execute('INSERT INTO attempts(corpus_sha256,task_id,candidate_sha256,admitted,record,'
                                'record_digest) VALUES(?,?,?,?,?,?)',
                                (corpus_digest(), task_id, candidate, int(admitted), encoded, _digest(encoded)))
            return self._summary(record, cursor.lastrowid, recorded=True)

    @staticmethod
    def _checked(row):
        record = json_object(row['record'], limit=DOCUMENT_LIMIT)
        if _digest(_json(record)) != row['record_digest'] or record.get('format') != 'toolwright-admission-v1':
            raise AdmissionError('admission_record_changed')
        return record

    def budget(self, task_id):
        get_task(task_id)
        with self._transaction() as db:
            used = db.execute('SELECT COUNT(*) FROM attempts WHERE corpus_sha256=? AND task_id=?',
                              (corpus_digest(), task_id)).fetchone()[0]
        return {'task_id': task_id, 'corpus_version': CORPUS_VERSION, 'candidates_used': used,
                'candidate_limit': self.candidate_limit}

    def inspect(self, attempt, *, include_held_out=False):
        """Audit view for a human. Held-out details are opt-in and must not feed repair."""
        if type(attempt) is not int or attempt < 1 or type(include_held_out) is not bool:
            raise AdmissionError('invalid_admission_inspection')
        with self._transaction() as db:
            row = db.execute('SELECT sequence, record, record_digest FROM attempts WHERE sequence=?',
                             (attempt,)).fetchone()
        if row is None:
            raise AdmissionError('admission_attempt_not_found')
        record = self._checked(row)
        summary = self._summary(record, row['sequence'], recorded=False)
        if include_held_out:
            summary.update(held_out=record['held_out'], held_out_details_included=True)
        return summary

    def promote(self, catalog, reviews, attempt, *, confirm=False):
        """Promote an admitted candidate via its first example receipt, never a held-out one."""
        if confirm is not True:
            raise PermissionError('explicit_promotion_confirmation_required')
        if type(attempt) is not int or attempt < 1:
            raise AdmissionError('invalid_admission_attempt')
        with self._transaction() as db:
            row = db.execute('SELECT sequence, record, record_digest FROM attempts WHERE sequence=?',
                             (attempt,)).fetchone()
        if row is None:
            raise AdmissionError('admission_attempt_not_found')
        record = self._checked(row)
        if record['admitted'] is not True:
            raise PermissionError('candidate_not_admitted')
        if record['corpus_sha256'] != corpus_digest():
            raise AdmissionError('admission_corpus_mismatch')
        case_id = record['promotion_case_id']
        if get_case(record['task_id'], case_id)[1]['split'] != 'example':
            raise AdmissionError('promotion_requires_example_case')
        return {**catalog.promote(reviews, record['proposals'][case_id], confirm=True),
                'admission_attempt': attempt, 'task_id': record['task_id']}
