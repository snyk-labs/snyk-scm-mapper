import json

from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, UUID4
from github import Repository

from .repositories import Repo


class Settings(BaseModel):
    cache_dir: Optional[Path]
    conf: Optional[Path]
    targets_dir: Optional[Path]
    tags_dir: Optional[Path]
    snyk_orgs: Dict = dict()
    snyk_orgs_file: Optional[Path]
    default_org: Optional[str]
    default_int: Optional[str]
    default_org_id: Optional[UUID4]
    default_int_id: Optional[UUID4]
    snyk_groups: Optional[List[dict]]
    snyk_token: Optional[UUID4]
    github_token: Optional[str]
    github_orgs: List[str] = list()
    cache_timeout: Optional[float]
    instance: Optional[str]

    forks: bool = False
    force_sync: bool = False

    def __getitem__(self, item):
        return getattr(self, item)

    def __setitem__(self, item, value):
        return setattr(self, item, value)


class SnykWatchList(BaseModel):
    repos: List[Repo] = []

    def match(self, **kwargs):
        data = []

        for repo in self.repos:
            if repo.match(**kwargs):
                data.append(repo)

        return data

    def get_repo(self, id) -> Repo:

        filter_repo = [r for r in self.repos if r.id == id]

        return filter_repo[0]

    def has_repo(self, id) -> bool:

        filter_repo = [r for r in self.repos if r.id == id]

        return bool(len(filter_repo))

    def save(self, cachedir):
        json_repos = [json.loads(r.json(by_alias=False)) for r in self.repos]

        with open(f"{cachedir}/data.json", "w") as the_file:
            json.dump(json_repos, the_file, indent=4)

        with open(f"{cachedir}/sync.json", "w") as the_file:
            state = {"last_sync": datetime.isoformat(datetime.utcnow())}

            json.dump(state, the_file, indent=4)

    def add_repo(self, repo: Repository.Repository):
        tmp_repo = {
            "fork": repo.fork,
            "name": repo.name,
            "owner": repo.owner.login,
            "branch": repo.default_branch,
            "url": repo.html_url,
            "project_base": repo.full_name,
        }

        branches = list()
        branches.append(repo.default_branch)

        if self.has_repo(repo.id):
            existing_repo = self.get_repo(repo.id)

            if existing_repo.is_older(repo.updated_at):

                existing_repo.source = tmp_repo

                existing_repo.url = repo.html_url

                existing_repo.fork = repo.fork

                existing_repo.updated_at = str(repo.updated_at)

        else:
            tmp_target = Repo(
                source=tmp_repo,
                url=repo.html_url,
                fork=repo.fork,
                id=repo.id,
                branches=branches,
                updated_at=str(repo.updated_at),
                full_name=str(repo.full_name),
            )

            self.repos.append(tmp_target)

    def get_proj_tag_updates(self, org_ids: list) -> list:

        has_tags = [r for r in self.repos if r.has_tags()]

        needs_tags = []

        for repo in has_tags:
            group_projects = [p for p in repo.projects if str(p.org_id) in org_ids]
            for project in group_projects:
                missing_tags = project.get_missing_tags(repo.org, repo.tags)
                if len(missing_tags) > 0:
                    missing_tags = [m.dict() for m in missing_tags]
                    fix_project = {
                        "org_id": str(project.org_id),
                        "project_id": str(project.id),
                        "tags": missing_tags,
                    }
                    needs_tags.append(fix_project)

        return needs_tags
