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

    def get_missing_tags(self, tags: list):
        """
        Returns a list of missing tags from a project. This assumes we only want tags managed on projects that are in the snyk org the parent repo's .snyk.d/import.yaml defines
        Because of how the snyk tag API works, you can have duplicate values for tags (user=foo, user=bar), so we can create duplicate tags key's here, but currently we're not support overwriting or pruning existing tags on a project
        """

        tag_list = [m.dict() for m in self.tags]

        missing = [i for i in tags if i not in tag_list]

        return missing


class Branch(BaseModel):
    name: str = "main"
    org_slug: str
    org_id: str
    integrations: dict
    projects: List[Project] = list()
    tags: list

    def project_count(self):
        return len(self.projects)

    def tag_count(self):
        return len(self.tags)


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
    branches: List
    fork: bool = False
    topics: List[str] = list()

    def get_reimport(self, default_org, snyk_orgs: dict) -> List[Branch]:
        """
        Returns a list branches and their associated projects that can be used for reimport
        """

        todo = self.parse_branches(default_org, snyk_orgs)

        for i, br in enumerate(todo):

            todo[i].projects = [p for p in self.projects if str(p.org_id) == br.org_id and p.branch == br.name]

        return todo

    def parse_branches(self, default_org: str, snyk_orgs: dict) -> List[Branch]:

        if self.org in snyk_orgs.keys():
            org_name = self.org
        else:
            org_name = default_org

        str_branches = [b for b in self.branches if isinstance(b, str)]

        todo = list()

        for b in str_branches:

            branch = Branch(
                name=b,
                org_slug=org_name,
                org_id=snyk_orgs[org_name]["orgId"],
                integrations=snyk_orgs[org_name]["integrations"],
                tags=[m.dict() for m in self.tags],
            )

            todo.append(branch)

        overrides = [b for b in self.branches if isinstance(b, dict)]

        for override in overrides:
            for k, v in override.items():
                ovr_branch = Branch(
                    name=k,
                    org_slug=org_name,
                    org_id=snyk_orgs[org_name]["orgId"],
                    integrations=snyk_orgs[org_name]["integrations"],
                    tags=[m.dict() for m in self.tags],
                )

                # if we have any other values, we will update that also
                if isinstance(v, dict):

                    if "orgName" in v.keys():
                        if v["orgName"] in snyk_orgs.keys():
                            org_name = v["orgName"]
                        else:
                            org_name = default_org

                        ovr_branch.org_slug = org_name
                        ovr_branch.org_id = snyk_orgs[org_name]["orgId"]
                        ovr_branch.integrations = snyk_orgs[org_name]["integrations"]

                    if "tags" in v.keys():
                        ovr_branch.tags = list()
                        for k, t in v["tags"].items():
                            tmp_tag = {"key": k, "value": t}
                            ovr_branch.tags.append(tmp_tag)

                todo.append(ovr_branch)

        return todo

    def needs_reimport(self, default_org, snyk_orgs: dict) -> bool:

        # we can just break here and state we need to reimport because we have no projects
        if len(self.projects) == 0:
            return True

        reimports = self.get_reimport(default_org, snyk_orgs)

        # we want to check that we have projects under every branch
        # as soon as we find a branch without projects, we know we need to import that branch
        for branch in reimports:
            if branch.project_count() == 0:
                return True

        return False

    def has_tags(self):
        return len(self.tags) > 0

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

    def parse_import(self, import_yaml: ContentFile.ContentFile, instance: str = None):
        r_yaml = dict()
        r_yaml.update(yaml.safe_load(import_yaml.decoded_content))

        if "instance" in r_yaml.keys():

            if instance in r_yaml["instance"].keys():

                override = r_yaml["instance"].pop(instance)

                # this drops the repo into the default org of the calling instance
                if "orgName" not in override.keys():
                    override["orgName"] = "default"

                r_yaml.update(override)

        self.import_sha = import_yaml.sha

        # print(r_url)
        if "orgName" in r_yaml.keys():
            self.org = r_yaml["orgName"]

        if "tags" in r_yaml.keys():
            for k, v in r_yaml["tags"].items():
                tmp_tag = {"key": k, "value": v}
                self.tags.append(Tag.parse_obj(tmp_tag))

        if "branches" in r_yaml.keys():
            self.branches = r_yaml["branches"]

    def is_older(self, timestamp) -> bool:

        remote_ts = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")

        local_ts = datetime.strptime(str(self.updated_at), "%Y-%m-%d %H:%M:%S")

        return bool(remote_ts > local_ts)
