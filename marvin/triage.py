from datetime import datetime
from datetime import timezone
from typing import Any

from gidgethub.aiohttp import GitHubAPI

from marvin import gh_util
from marvin import team
from marvin.command_router import CommandRouter
from marvin.gh_util import set_issue_status

command_router = CommandRouter()

AWAITING_REVIEWER_TIMEOUT_SECONDS = 60 * 60 * 24 * 3  # three days
AWAITING_MERGER_TIMEOUT_SECONDS = 60 * 60 * 24 * 3  # three days


async def timeout_awaiting_reviewer(
    gh: GitHubAPI, token: str, repository_name: str
) -> None:
    print("Timing out awaiting_reviewer PRs")
    search_results = gh_util.search_issues(
        gh,
        token,
        query_parameters=[
            f"repo:{repository_name}",
            "is:open",
            "is:pr",
            "label:awaiting_reviewer",
            "label:marvin",
            "sort:updated-asc",  # stale first
        ],
    )
    async for issue in search_results:
        last_updated = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%S%z")
        age = datetime.now(timezone.utc) - last_updated
        if age.total_seconds() < AWAITING_REVIEWER_TIMEOUT_SECONDS:
            break

        print(
            f"awaiting_reviewer -> needs_reviewer: #{issue['number']} ({issue['title']})"
        )
        await set_issue_status(issue, "needs_reviewer", gh, token)


async def timeout_awaiting_merger(
    gh: GitHubAPI, token: str, repository_name: str
) -> None:
    print("Timing out awaiting_merger PRs")
    search_results = gh_util.search_issues(
        gh,
        token,
        query_parameters=[
            f"repo:{repository_name}",
            "is:open",
            "is:pr",
            "label:awaiting_merger",
            "label:marvin",
            "sort:updated-asc",  # stale first
        ],
    )
    async for issue in search_results:
        last_updated = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%S%z")
        age = datetime.now(timezone.utc) - last_updated
        if age.total_seconds() < AWAITING_MERGER_TIMEOUT_SECONDS:
            break

        print(f"awaiting_merger -> needs_merger: #{issue['number']} ({issue['title']})")
        await set_issue_status(issue, "needs_merger", gh, token)


async def assign_mergers(gh: GitHubAPI, token: str, repository_name: str) -> None:
    print("Assigning mergers to needs_merger PRs")
    search_results = gh_util.search_issues(
        gh,
        token,
        query_parameters=[
            f"repo:{repository_name}",
            "is:open",
            "is:pr",
            "label:needs_merger",
            "label:marvin",
            "sort:created-asc",  # oldest first
        ],
    )
    async for issue in search_results:
        reviewer = await team.get_reviewer(
            gh, token, issue, merge_permission_needed=True
        )
        if reviewer is not None:
            print(f"Requesting review (merge) from {reviewer} for #{issue['number']}.")
            await gh_util.request_review(
                issue["pull_request"]["url"], reviewer, gh, token
            )
            await set_issue_status(issue, "awaiting_merger", gh, token)
        else:
            print(f"No reviewer with merge permission found for #{issue['number']}.")


async def assign_reviewers(gh: GitHubAPI, token: str, repository_name: str) -> None:
    print("Assigning reviewers to needs_reviewer PRs")
    search_results = gh_util.search_issues(
        gh,
        token,
        query_parameters=[
            f"repo:{repository_name}",
            "is:open",
            "is:pr",
            "label:needs_reviewer",
            "label:marvin",
            "sort:created-asc",  # oldest first
        ],
    )
    async for issue in search_results:
        reviewer = await team.get_reviewer(
            gh, token, issue, merge_permission_needed=False
        )
        if reviewer is not None:
            print(f"Requesting review from {reviewer} for #{issue['number']}.")
            await gh_util.request_review(
                issue["pull_request"]["url"], reviewer, gh, token
            )
            await set_issue_status(issue, "awaiting_reviewer", gh, token)
        else:
            print(f"No reviewer found for #{issue['number']}.")


@command_router.register_command("/marvin triage")
async def run_triage(gh: GitHubAPI, token: str, **kwargs: Any) -> None:
    repositories = await gh_util.get_installation_repositories(gh, token)
    for repository in repositories:
        repository_name = repository["full_name"]
        print(f"Running triage on {repository_name}")
        await timeout_awaiting_reviewer(gh, token, repository_name)
        await timeout_awaiting_merger(gh, token, repository_name)
        await assign_mergers(gh, token, repository_name)
        await assign_reviewers(gh, token, repository_name)
