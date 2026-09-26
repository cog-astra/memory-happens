import re
import subprocess
from pathlib import Path

from pydantic import Field

from recall_operations import AccessDenied, Evidence, Operation, Outcome, Passage, Value


class History(Value):
    limit: int | None = Field(default=50, gt=0)


class Read(Value):
    evidence: Evidence


class Plugin:
    def __init__(self, source, repo):
        self.source = source
        self.repo = Path(repo).resolve()

    def catalog(self):
        return [Operation('history', 'Read commit descriptions from the configured repository.', History),
                Operation('read', 'Read the commit and patch identified by evidence.', Read)]

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True,
                                text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError('Git command failed.')
        return result.stdout

    def require_commit(self, revision, context):
        context.require(self.repo.as_posix())
        names = self.git('diff-tree', '--root', '-m', '--no-commit-id', '--name-only', '-r', '-z', revision)
        context.require(*[(self.repo / name).resolve().as_posix() for name in names.split('\0') if name])

    def invoke(self, operation, parameters, inputs, context):
        context.require(self.repo.as_posix())
        if not (self.repo / '.git').exists():
            yield Outcome(status='unavailable', code='repository_missing')
            return
        if operation == 'history':
            limit = [f'--max-count={parameters["limit"]}'] if parameters['limit'] is not None else []
            revisions = self.git('rev-list', *limit, 'HEAD').splitlines()
            hidden = False
            for revision in revisions:
                if context.cancelled.is_set():
                    yield Outcome(status='cancelled')
                    return
                try:
                    self.require_commit(revision, context)
                except AccessDenied:
                    hidden = True
                    continue
                header, description = self.git('show', '-s', '--format=%aI%n%B', revision).split('\n', 1)
                yield Passage(text=description,
                              evidence=[Evidence(source=self.source, locator=revision, revision=revision)],
                              context={'commit_authored_at': header})
            if hidden:
                yield Outcome(status='partial', code='policy_filtered',
                              message='Some revisions were excluded by the configured access policy.')
                return
        else:
            evidence = Evidence.model_validate(parameters['evidence'])
            revision = evidence.locator
            if (evidence.source != self.source or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
                    or evidence.revision not in (None, revision)):
                yield Outcome(status='unsupported', code='incompatible_evidence')
                return
            self.require_commit(revision, context)
            patch = self.git('show', '--no-ext-diff', '--no-textconv', '--format=fuller', '--patch', revision)
            yield Passage(text=patch, evidence=[evidence])
        yield Outcome(status='success')
