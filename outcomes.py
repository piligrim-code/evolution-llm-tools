"""Typed outcomes for one reviewed attempt, never an automatic retry instruction."""
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import re

from .container_runner import ContainerError


class ExecutionStatus(StrEnum):
    REFUSED = 'refused'
    INVALID = 'invalid'
    TIMEOUT = 'timeout'
    FAILED = 'failed'
    CLEANUP_UNKNOWN = 'cleanup_unknown'
    INDETERMINATE = 'indeterminate'
    SUCCEEDED = 'succeeded'


class CleanupState(StrEnum):
    NOT_STARTED = 'not_started'
    CONFIRMED = 'confirmed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ExecutionOutcome:
    proposal_id: str | None
    status: ExecutionStatus
    reason: str
    approval_consumed: bool | None
    cleanup: CleanupState
    receipt_saved: bool | None
    result: dict | None = None
    resource: str | None = None

    def to_dict(self):
        return {'schema_version': 1, 'proposal_id': self.proposal_id,
                'status': self.status.value, 'reason': self.reason,
                'approval_consumed': self.approval_consumed, 'cleanup': self.cleanup.value,
                'receipt_saved': self.receipt_saved, 'automatic_retry_allowed': False,
                'result': deepcopy(self.result), 'resource': self.resource}


@dataclass
class _Attempt:
    claim_started: bool = False
    claimed: bool = False
    executor: object | None = None
    returned: bool = False
    receipt_started: bool = False
    receipt_saved: bool = False
    result: dict | None = None
    refusal_reason: str = 'approval_required_or_consumed'

    def cleanup_state(self):
        if self.returned or getattr(self.executor, '_cleanup_confirmed', None) is True:
            return CleanupState.CONFIRMED
        if self.executor is None or getattr(self.executor, '_attempted', None) is False:
            return CleanupState.NOT_STARTED
        return CleanupState.UNKNOWN

    def outcome(self, proposal_id, status, reason, *, resource=None, cleanup=None):
        identifier = proposal_id if isinstance(proposal_id, str) and re.fullmatch(r'[a-f0-9]{32}', proposal_id) else None
        clean = self.cleanup_state() if cleanup is None else cleanup
        if resource is None and clean != CleanupState.NOT_STARTED:
            resource = getattr(self.executor, 'name', None)
        if not isinstance(resource, str) or not re.fullmatch(r'alita-box-[a-f0-9]{32}', resource):
            resource = None
        return ExecutionOutcome(
            identifier, status, reason,
            True if self.claimed else None if self.claim_started else False,
            clean, True if self.receipt_saved else None if self.receipt_started else False,
            deepcopy(self.result), resource)


def _completed_outcome(proposal_id, attempt):
    result = attempt.result
    if (not isinstance(result, dict) or result.get('execution') != 'container'
            or type(result.get('returncode')) is not int):
        return attempt.outcome(proposal_id, ExecutionStatus.INVALID, 'invalid_execution_result')
    if result.get('outcome') == 'timeout':
        return attempt.outcome(proposal_id, ExecutionStatus.TIMEOUT, 'execution_timeout')
    if result['returncode'] != 0 or result.get('outcome') != 'exited':
        return attempt.outcome(proposal_id, ExecutionStatus.FAILED, 'execution_failed')
    if result.get('output_validation', {}).get('status') != 'passed':
        return attempt.outcome(proposal_id, ExecutionStatus.INVALID, 'output_contract_not_satisfied')
    return attempt.outcome(proposal_id, ExecutionStatus.SUCCEEDED, 'validated_execution_completed')


def _exception_outcome(proposal_id, attempt, error):
    if not attempt.claim_started:
        if isinstance(error, PermissionError):
            return attempt.outcome(proposal_id, ExecutionStatus.REFUSED, attempt.refusal_reason)
        if isinstance(error, ValueError):
            return attempt.outcome(proposal_id, ExecutionStatus.INVALID, 'invalid_proposal')
        return attempt.outcome(proposal_id, ExecutionStatus.FAILED, 'review_access_failed')
    if isinstance(error, ContainerError):
        if error.code == 'cleanup_unconfirmed':
            return attempt.outcome(proposal_id, ExecutionStatus.CLEANUP_UNKNOWN, 'container_cleanup_unconfirmed',
                                   resource=error.resource, cleanup=CleanupState.UNKNOWN)
        return attempt.outcome(proposal_id, ExecutionStatus.FAILED, 'container_execution_failed', resource=error.resource)
    reason = ('receipt_persistence_unknown' if attempt.receipt_started else
              'execution_result_unknown' if attempt.claimed else 'approval_claim_unknown')
    return attempt.outcome(proposal_id, ExecutionStatus.INDETERMINATE, reason)
