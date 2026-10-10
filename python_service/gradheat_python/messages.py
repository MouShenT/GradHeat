from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from gradheat.material_store import encode
from gradheat_workbench.models import InputModel

PROCESSOR_VERSION = 'gradheat-python-v1'
TASK_TYPES = ('collect.official', 'collect.social.win-primary', 'collect.autonomous.win-primary', 'extract.documents', 'verify.information', 'analyse.long')
TERMINAL = ('completed', 'paused_human', 'failed', 'cancelled')


class Command(InputModel):
    schema_version: Literal[1]
    message_id: UUID
    task_id: UUID
    type: Literal['collect.official', 'collect.social.win-primary', 'collect.autonomous.win-primary', 'extract.documents', 'verify.information', 'analyse.long']
    input_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    processor_version: str = Field(min_length=1, max_length=80)
    scope: dict[str, Any]
    trace_id: UUID
    attempt: int = Field(ge=1, le=100)
    created_at: AwareDatetime
    deadline_at: AwareDatetime

    @model_validator(mode='after')
    def bounded_public_scope(self):
        if self.deadline_at <= self.created_at:
            raise ValueError('Task deadline must follow creation')
        if len(encode(self.scope).encode()) > 32_000:
            raise ValueError('Scope exceeds command budget')
        forbidden = {'cookie', 'cookies', 'authorization', 'password', 'headers', 'token', 'signature', 'private_log', 'har'}
        def check(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).lower() in forbidden:
                        raise ValueError('Private session material is forbidden in task messages')
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(self.scope)
        return self

    @property
    def execution_key(self):
        identity = {'task_id': str(self.task_id), 'input_version': self.input_version,
            'processor_version': self.processor_version, 'attempt': self.attempt}
        return hashlib.sha256(encode(identity).encode()).hexdigest()

    @property
    def input_sha(self):
        return hashlib.sha256(encode({'type': self.type, 'scope': self.scope}).encode()).hexdigest()


def decode_command(raw):
    if len(raw) > 64_000:
        raise ValueError('AMQP command exceeds budget')
    # Reject duplicate JSON keys; a Java/Python parser must not see different scopes.
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate command JSON key')
            result[key] = value
        return result
    return Command.model_validate(json.loads(raw, object_pairs_hook=pairs))


def event(command, status, sequence, result_id=None, result_sha=None, error_code=None):
    return dict(schema_version=1, message_id=str(uuid4()), task_id=str(command.task_id), type='task.status',
        status=status, sequence=sequence, attempt=command.attempt, input_version=command.input_version,
        processor_version=command.processor_version,
        result_id=result_id, result_sha=result_sha, error_code=error_code,
        created_at=datetime.now(timezone.utc).isoformat())
