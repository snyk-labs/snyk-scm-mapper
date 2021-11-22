import json
from uuid import RESERVED_FUTURE, UUID
from tomlkit.items import DateTime
import yaml

from pathlib import Path
from pprint import pprint
from dataclasses import dataclass
from datetime import datetime


from typing import List

from pydantic import BaseModel, FilePath, ValidationError, root_validator, UUID4, Field, create_model, validator

from github import ContentFile


class Source(BaseModel):
    fork: bool
    name: str
    owner: str
    branch: str
    url: str
    project_base: str

    def get_target(self):
        target = {"fork": self.fork, "name": self.name, "owner": self.owner, "branch": self.branch}

        return target


class Tag(BaseModel):
    key: str
    value: str


class Project(BaseModel):
    class Config:
        allow_population_by_field_name = True

    id: UUID4
    name: str = Field(alias="attributes")
    tags: List[Tag] = Field(alias="attributes")
    branch: str = Field(alias="attributes")
    type: str = Field(alias="attributes")
    status: str = Field(alias="attributes")
    org_id: UUID4
    org_slug: str
    origin: str = Field(alias="attributes")
    target: str = Field(alias="relationships")
    target_path: str = Field(alias="attributes")
    repo_name: str = ""
    repo_id: int = None

    @validator("name", "origin", "type", "status", "branch", pre=True)
    def validate_strings(cls, value, values, config, field):

        if isinstance(value, str):
            return value

        the_name = field.name
        if the_name == "branch":
            the_name = "targetReference"
        if not isinstance(value, dict):
            raise TypeError(f"{field.name} type must be dict")

        return str(value[the_name])

    @validator("target_path", pre=True)
    def validate_target_path(cls, value):

        if isinstance(value, str):
            return value

        if not isinstance(value, dict):
            raise TypeError("path type must be dict")

        if ":" in value["name"]:
            project_name: str
            project_name = value["name"]
            target_path = project_name.split(":")[1]
        else:
            target_path = ""

        return target_path

    @validator("tags", pre=True)
    def validate_tags(cls, value):

        tags = list()

        if isinstance(value, list):
            for tag in value:
                tags.append(Tag.parse_obj(tag))
        elif not isinstance(value, dict):
            raise TypeError("Tags type must be dict or List")
        elif "tags" not in value.keys():
            raise TypeError("No Tags in Projec Resp")
        elif not isinstance(value["tags"], list):
            raise TypeError("No Tags in Projec Resp")
        else:
            for tag in value["tags"]:
                tags.append(Tag.parse_obj(tag))

        return tags

    @validator("target", pre=True)
    def validate_target(cls, value):

        if isinstance(value, str):
            return value

        if not isinstance(value, dict):
            raise TypeError("target type must be dict")
        if "target" not in value.keys():
            raise TypeError("No Target in Project Resp")
        if "data" not in value["target"].keys():
            raise TypeError("No Target in Project Resp")

        return value["target"]["data"]["id"]

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

    def get_missing_tags(self, repo_org: str, tags: List[Tag]):
        """
        Returns a list of missing tags from a project. This assumes we only want tags managed on projects that are in the snyk org the parent repo's .snyk.d/import.yaml defines
        Because of how the snyk tag API works, you can have duplicate values for tags (user=foo, user=bar), so we can create duplicate tags key's here, but currently we're not support overwriting or pruning existing tags on a project
        """
        if repo_org != self.org_slug:
            return []

        return [i for i in tags if i not in self.tags]


class Repo(BaseModel):
    url: str
    source: Source
    id: int
    updated_at: str
    import_sha: str = ""
    full_name: str
    projects: List[Project] = []
    tags: List[Tag] = []
    org: str = "default"
    branches: List[str]

    def needs_reimport(self, default_org, snyk_orgs):
        """
        Returns true if there are no projects in associated with the org that has been assigned to this repo
        """
        if self.org == "default":
            org_name = default_org
        else:
            org_name = self.org

        org_id = snyk_orgs[org_name]["orgId"]

        matching = [p for p in self.projects if p.org_id == org_id]

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
            project_attributes = len([x for x, y in kwargs.items() if x in project.__dict__])
            if project.match(**kwargs):
                project_matches += 1

        if project_attributes > 0:
            matches_projects = project_matches > 0
        else:
            matches_projects = True

        return matches == len(valid_keys) and matches_projects

    def parse_import(self, import_yaml: ContentFile):
        r_yaml = yaml.safe_load(import_yaml.decoded_content)

        self.import_sha = import_yaml.sha

        # print(r_url)
        if "orgName" in r_yaml.keys():
            self.org = r_yaml["orgName"]

        if "tags" in r_yaml.keys():
            for k, v in r_yaml["tags"].items():
                tmp_tag = {"key": k, "value": v}
                self.tags.append(Tag.parse_obj(tmp_tag))

    def is_older(self, timestamp) -> bool:

        remote_ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")

        local_ts = datetime.strptime(self.updated_at, "%Y-%m-%d %H:%M:%S")

        return bool(remote_ts > local_ts)
