import re
import subprocess
from pathlib import Path

from pydantic import Field

from recall_operations import AccessDenied, Evidence, Operation, Outcome, Passage, Value


class History(Value):
    limit: int | None = Field(default=50, gt=0)


class Read(Value):
    evidence: Evidence


ACCESS = ('repository', 'changed_paths')


class Plugin:
    def __init__(self, source, repo, *, access):
        """access='repository' checks policy for the repository as a whole; 'changed_paths' also
        for every path a commit changed, for policies that distinguish paths inside it."""
        if access not in ACCESS:
            raise ValueError(f'access must be one of {ACCESS}')
        self.source = source
        self.repo = Path(repo).resolve()
        self.access = access

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
            total = int(self.git('rev-list', '--count', 'HEAD'))
            if self.access == 'repository':
                fields = self.git('log', '-z', '--format=%H%x00%aI%x00%B', *limit, 'HEAD').split('\0')
                # git show ends each description with one more newline than git log -z; keep the texts equal.
                commits = [(fields[i], fields[i + 1], fields[i + 2] + '\n') for i in range(0, len(fields) - 2, 3)]
            else:
                commits = [(revision, None, None) for revision in self.git('rev-list', *limit, 'HEAD').splitlines()]
            hidden = 0
            for revision, moment, description in commits:
                if context.cancelled.is_set():
                    yield Outcome(status='cancelled')
                    return
                if self.access == 'changed_paths':
                    try:
                        self.require_commit(revision, context)
                    except AccessDenied:
                        hidden += 1
                        continue
                    moment, description = self.git('show', '-s', '--format=%aI%n%B', revision).split('\n', 1)
                yield Passage(text=description,
                              evidence=[Evidence(source=self.source, locator=revision, revision=revision)],
                              context={'event_time': moment})
            scope = (f'all {total} commits on HEAD' if len(commits) == total
                     else f'{len(commits)} most recent of {total} commits on HEAD')
            if hidden:
                yield Outcome(status='partial', code='policy_filtered',
                              message=f'{scope}; {hidden} excluded by the configured access policy.')
            else:
                yield Outcome(status='success', message=scope + '.')
            return
        else:
            evidence = Evidence.model_validate(parameters['evidence'])
            revision = evidence.locator
            if (evidence.source != self.source or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
                    or evidence.revision not in (None, revision)):
                yield Outcome(status='unsupported', code='incompatible_evidence')
                return
            if self.access == 'changed_paths':
                self.require_commit(revision, context)
            patch =self.git('show', '--no-ext-diff', '--no-textconv', '--format=fuller', '--patch', revision)
            yield Passage(text=patch, evidence=[evidence])
        yield Outcome(status='success')
