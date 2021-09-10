import json
from uuid import RESERVED_FUTURE, UUID
from tomlkit.items import DateTime
import yaml

from pathlib import Path
from pprint import pprint
from dataclasses import dataclass
from datetime import datetime

from github import Github, Repository

from typing import Optional, List, Optional, TypedDict, Tuple, Dict

from pydantic import BaseModel, FilePath, ValidationError, root_validator, UUID4, Field, create_model

from utils import newer

class Org(BaseModel):
    orgId: UUID4
    integrations: Dict[str, UUID4]
    name: Optional[str]

    def id(self):
        return self.orgId

    def has(self, item):
        return item in self.integrations

    def int_id(self, item):
        try:
            return self.integrations[item]
        except KeyError as e:
            print(f"{item} is not a know integration for this Snyk Org ({self.name})")
            print(f"Known integrations are: {self.int_list()}")
            print(f"Please update your snyk-orgs.yaml if {item} does exist")

    def int_list(self):
        return list(self.integrations.keys())


class Orgs(BaseModel):
    __root__: Dict[str, Org]

    def __iter__(self):
        return iter(self.__root__)

    def __getitem__(self, item):
        return self.__root__[item]

    @root_validator
    def remap_names(cls, values):
        for k in values["__root__"]:
            values["__root__"][k].name = k
        return values


class Source(BaseModel):
    fork: bool
    name: str
    owner: str
    branch: str
    url: str
    project_base: str

    def get_target(self):
        target = {
                "fork": self.fork,
                "name": self.name,
                "owner": self.owner,
                "branch": self.branch
            }

        return target


class Tag(BaseModel):
    key: str
    value: str

class Project(BaseModel):
    id: UUID4
    name: str
    last_tested_date: str = Field(alias="lastTestedDate")
    tags: List[Tag] = []
    branch: str
    type: str
    read_only: bool = Field(alias="readOnly")
    test_frequency: str = Field(alias="testFrequency")
    is_monitored: bool = Field(alias="isMonitored")
    org_id: UUID4
    org_name: str

    def match(self, **kwargs):
        valid_keys = {x: y for x, y in kwargs.items() if x in self.__dict__}
        matches = 0
        for key, value in valid_keys.items():
            if key in self.__dict__:
                if getattr(self, key) == value:
                    # print(key, value)
                    matches += 1
        # print(matches)
        return matches > 0
    
    def get_missing_tags(self, repo_org, tags):

        # bomb out early and say there's no need for tags if this project is an orphan
        if repo_org != self.org_name:
            return []

        return [ i for i in tags if i not in self.tags ]
            


class Repo(BaseModel):
    url: str
    source: Source
    id: int
    updated_at: str
    import_sha: str = ''
    projects: List[Project] = []
    tags: List[Tag] = []
    org: str = 'default'

    def needs_reimport(self, default_org):
        """
        Returns true if there are no projects in associated with the org that has been assigned to this repo
        """
        if self.org == 'default':
            org_name = default_org
        else:
            org_name = self.org


        matching = [p for p in self.projects if p.org_name == org_name]

        return len(matching) == 0

    def has_tags(self):
        return len(self.tags) > 0
    
    def fork(self):
        return self.source.fork
    
    def get_project(self, id) -> Project:

        filter_repo = [r for r in self.projects if r.id == id]

        return filter_repo[0]

    def has_project(self, id) -> bool:

        filter_repo = [r for r in self.projects if r.id == id]
        
        return bool(len(filter_repo))

    def add_project(self, project: Project):

        if self.has_project(project.id):
            for idx, item in enumerate(self.projects):
                if project.id == item.id:
                    self.projects[idx] = project

        else:
            self.projects.append(project)


    def match(self, **kwargs):
        valid_keys = {x: y for x, y in kwargs.items() if x in self.source.__dict__}
        # print(valid_keys)
        matches = 0
        for key, value in valid_keys.items():
            if key in self.source.__dict__:
                if getattr(self.source, key) == value:
                    # print(key, value)
                    matches += 1

        project_matches = 0
        project_attributes = 0

        for project in self.projects:
            project_attributes = len(
                [x for x, y in kwargs.items() if x in project.__dict__]
            )
            if project.match(**kwargs):
                project_matches += 1

        if project_attributes > 0:
            matches_projects = project_matches > 0
        else:
            matches_projects = True

        return matches == len(valid_keys) and matches_projects

class Settings(BaseModel):
    cache_dir: Optional[Path]
    conf: Optional[Path]
    targets_file: Optional[Path]
    snyk_orgs: Optional[Dict]
    snyk_orgs_file: Optional[Path]
    default_org: Optional[str]
    default_int: Optional[str]
    default_org_id: Optional[UUID4]
    default_int_id: Optional[UUID4]
    snyk_group: Optional[UUID4]
    snyk_token: Optional[UUID4]
    github_token: Optional[str]
    github_orgs: Optional[List[str]]
    cache_timeout: Optional[float]
    forks: bool = False

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
        json_repos = [json.loads(r.json(by_alias=True)) for r in self.repos]

        with open(f"{cachedir}/data.json", "w") as the_file:
            json.dump(json_repos, the_file, indent=4)

        with open(f"{cachedir}/sync.json", "w") as the_file:
            state = {"last_sync": datetime.isoformat(datetime.utcnow())}

            json.dump(state, the_file, indent=4)



class RateLimit(BaseModel):
    core: dict
    search: dict

