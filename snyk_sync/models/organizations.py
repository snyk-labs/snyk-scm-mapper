import json
from uuid import UUID
from snyk.client import SnykClient
import os
import logging

from datetime import datetime

from typing import Optional, Dict, List

from pydantic import (
    BaseModel,
    UUID4,
    Field,
    validator,
)

from utils import to_camel_case, jopen, update_client

from .repositories import Project
from api import v1_get_pages


logger = logging.getLogger(__name__)


class Target(BaseModel):
    class Config:
        allow_population_by_field_name = True

    id: UUID4
    org_id: UUID4 = None
    org_slug: str = ""
    name: str = Field(alias="attributes")
    origin: str = Field(alias="attributes")
    remote_url: str = Field(alias="attributes")
    is_private: bool = Field(alias="attributes")
    repo_id: Optional[str] = Field(alias="attributes")

    # , "origin", "remote_url", "is_private", "repo_id"
    @validator("name", "origin", "remote_url", pre=True)
    def validate_strings(cls, value, values, config, field):

        if isinstance(value, str):
            return value

        camel_case_name = to_camel_case(field.name)
        if camel_case_name == "name":
            camel_case_name = "displayName"
        if not isinstance(value, dict):
            raise TypeError(f"{field.name} type must be dict")
        if camel_case_name not in value and camel_case_name != "repoId":
            raise ValueError(f'Not found "{camel_case_name}" in "{field.alias}"')
        if camel_case_name not in value and camel_case_name == "repoId":
            return ""
        return str(value[camel_case_name])

    @validator("is_private", pre=True)
    def validate_private(cls, value):

        if isinstance(value, bool):
            return value

        if not isinstance(value, dict):
            raise TypeError("private type must be dict")
        if "isPrivate" not in value:
            raise ValueError(f'Not found "isPrivate" in "attributes"')

        return bool(value["isPrivate"])

    @validator("repo_id", pre=True)
    def validate_repo_id(cls, value):

        if isinstance(value, str):
            return int(value)
        elif value is None:
            return None

        if not isinstance(value, dict):
            raise TypeError("repoid type must be dict")
        if "repoId" not in value or "id" not in value:
            return None
        else:
            return str(value["id"])


class Org(BaseModel):
    id: UUID4
    integrations: Dict[str, UUID4] = dict()
    projects: List[Project] = list()
    targets: List[Target] = list()
    name: str
    slug: str
    group_id: UUID4
    group_name: str
    origins: List[str] = list()
    last_updated: datetime = datetime.isoformat(datetime.utcnow())
    #       "name": "myDefaultOrg",
    #  "id": "689ce7f9-7943-4a71-b704-2ba575f01089",
    #  "slug": "my-default-org",
    #  "url": "https://api.snyk.io/org/default-org",
    #  "created": "2021-06-07T00:00:00.000Z"

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

    def refresh_targets(self, client: SnykClient, origin: str = None, exclude_empty: bool = True, limit: int = 100):
        """
        Retrieves all the targets from this org object, using the provided client
        Optionally matches on 'origin'
        """

        params = {"origin": origin, "limit": limit, "excludeEmpty": exclude_empty}

        path = f"orgs/{self.id}/targets"

        targets = client.get_v3_pages(path, params)

        for target in targets:
            new_target = Target.parse_obj(target)
            new_target.org_id = self.id
            new_target.org_slug = self.slug
            self.add_target(new_target)

    def refresh_projects(self, client: SnykClient, origin: str = None, target: UUID4 = None, limit: int = 100):
        """
        Retrieves all the projects from this org object, using the provided client
        Optionally matches on 'origin' and/or target
        """
        params = {"targetId": target, "origin": origin, "limit": limit}

        path = f"orgs/{self.id}/projects"

        projects = client.get_v3_pages(path, params)

        for project in projects:
            project["org_id"] = self.id
            project["org_slug"] = self.slug

            new_project = Project.parse_obj(project)

            project_target = self.get_target_info(new_project.target)

            if project_target:
                new_project.repo_name = project_target.name
                new_project.repo_id = project_target.repo_id

            self.add_project(new_project)

    def refresh_origins(self):
        target_origins = [o.origin for o in self.targets]

        project_origins = [p.origin for p in self.projects]

        self.origins = set(target_origins + project_origins)

    def refresh_integrations(self, client: SnykClient):
        resp = client.get(f"org/{self.id}/integrations")

        integrations: dict = resp.json()

        self.integrations = integrations

    def refresh(
        self,
        v1client: SnykClient,
        v3client: SnykClient,
        origin: str = None,
        target: UUID4 = None,
    ):
        self.refresh_targets(v3client, origin)
        self.refresh_projects(v3client, origin, target)
        self.refresh_origins()
        self.refresh_integrations(v1client)
        self.last_updated = datetime.isoformat(datetime.utcnow())

    def get_target_info(self, id: UUID) -> Target:

        found_target = [t for t in self.targets if str(t.id) == str(id)]

        if len(found_target) == 1:
            target = found_target[0]
        else:
            target = None
        return target

    def get_metadata(self) -> dict:

        the_dict = {
            "id": str(self.id),
            "name": str(self.name),
            "slug": str(self.slug),
            "group_id": str(self.group_id),
            "group_name": str(self.group_name),
            "last_updated": str(self.last_updated),
        }

        return the_dict

    def save(self, path):
        if os.path.isdir(f"{path}/targets") is not True:
            os.mkdir(f"{path}/targets")

        if os.path.isdir(f"{path}/projects") is not True:
            os.mkdir(f"{path}/projects")

        with open(f"{path}/integrations.json", "w") as the_file:
            json.dump(self.integrations, the_file, indent=4)

        with open(f"{path}/metadata.json", "w") as the_file:
            json.dump(self.get_metadata(), the_file, indent=4)

        for target in self.targets:
            with open(f"{path}/targets/{target.id}.json", "w") as the_file:
                json.dump(json.loads(target.json()), the_file, indent=4)

        for project in self.projects:
            with open(f"{path}/projects/{project.id}.json", "w") as the_file:
                json.dump(json.loads(project.json()), the_file, indent=4)

        pass

    def add_project(self, project: Project):

        add_project = True

        for idx, item in enumerate(self.projects):
            if project.id == item.id:
                add_project = False
                self.projects[idx] = project

        if add_project:
            self.projects.append(project)

    def add_target(self, target: Target):

        add_target = True

        for idx, item in enumerate(self.targets):
            if target.id == item.id:
                add_target = False
                self.targets[idx] = target

        if add_target:
            self.targets.append(target)

    def load(self, path):
        if os.path.isdir(f"{path}/targets") is not True:
            raise Exception(f"{path}/targets does not exist")

        if os.path.isdir(f"{path}/projects") is not True:
            raise Exception(f"{path}/projects does not exist")

        if os.path.isfile(f"{path}/integrations.json") is not True:
            raise Exception(f"{path}/integrations.json does not exist")

        self.integrations = jopen(f"{path}/integrations.json")

        for target_file in os.listdir(f"{path}/targets"):
            if os.path.isfile(f"{path}/targets/{target_file}") and target_file.endswith(".json"):

                new_target = Target.parse_file(f"{path}/targets/{target_file}")

                self.add_target(new_target)

        for project_file in os.listdir(f"{path}/projects"):
            if os.path.isfile(f"{path}/projects/{project_file}") and project_file.endswith(".json"):

                new_project = Project.parse_file(f"{path}/projects/{project_file}")

                self.add_project(new_project)

    def find_targets_by_repo(self, name, id) -> List[Target]:

        targets_by_id = [t for t in self.targets if t.repo_id == id]

        targets_by_name = [t for t in self.targets if str(t.name).lower() == str(name).lower()]

        if len(targets_by_name) == 0 and len(targets_by_id) == 0:
            return list()
        else:
            for target in targets_by_name:
                if target.id not in [t.id for t in targets_by_id]:
                    targets_by_id.append(target)

            return targets_by_id

    def find_projects_by_target(self, id) -> List[Project]:

        projects = [p for p in self.projects if str(p.target).lower() == str(id).lower()]

        return projects

    def find_projects_by_repo(self, name, id) -> List[Project]:

        found_projects = list()

        targets = self.find_targets_by_repo(name, id)

        if len(targets) > 0:
            for target in targets:
                found_projects.extend(self.find_projects_by_target(target.id))

            return found_projects
        else:
            return list()


class Orgs(BaseModel):
    orgs: List[Org] = list()
    cache: str = ""
    groups: List[dict] = list()

    def refresh_orgs(self, v1client: SnykClient, v3client: SnykClient, origin: str = None, selected_orgs: list = []):
        for group in self.groups:
            group_id = group["id"]
            group_token = group["snyk_token"]

            v1client = update_client(v1client, group_token)

            try:
                new_orgs = v1_get_pages(f"group/{group_id}/orgs", v1client, "orgs")
            except:
                print(f"Unable to load orgs from: {group['name']} with token stored at: {group['token_env_name']}")

            for org in new_orgs["orgs"]:
                if len(selected_orgs) == 0 or org["id"] in selected_orgs:
                    org["group_id"] = new_orgs["id"]
                    org["group_name"] = new_orgs["name"]
                    self.add_org(Org.parse_obj(org))

        for org in self.orgs:
            logger.debug(f"Refreshing Org: {org.name}")

            snyk_token = self.get_token_for_org(org)

            v1client = update_client(v1client, snyk_token)
            v3client = update_client(v3client, snyk_token)

            org.refresh(v1client, v3client, origin)

        pass

    def add_org(self, org: Org):

        add_org = True

        for idx, item in enumerate(self.orgs):
            if org.id == item.id:
                add_org = False
                self.orgs[idx].name = org.name
                self.orgs[idx].slug = org.slug
                self.orgs[idx].group_name = org.group_name
                self.orgs[idx].group_id = org.group_id
                self.orgs[idx].last_updated = org.last_updated

        if add_org:
            self.orgs.append(org)

    def summary(self):
        print(f"Groups: {len(self.groups)}")
        print(f"Orgs: {len(self.orgs)}")

        all_projects = list()
        all_targets = list()

        for org in self.orgs:
            all_projects.append(len(org.projects))
            all_targets.append(len(org.targets))

        print(f"All Projects: {sum(all_projects)}")
        print(f"All Targets: {sum(all_targets)}")

    def save(self):
        if os.path.isdir(f"{self.cache}/org") is not True:
            os.mkdir(f"{self.cache}/org")

        for org in self.orgs:
            if os.path.isdir(f"{self.cache}/org/{org.slug}") is not True:
                os.mkdir(f"{self.cache}/org/{org.slug}")

            org.save(f"{self.cache}/org/{org.slug}")

    def load(self):
        if os.path.isdir(f"{self.cache}/org") is not True:
            raise Exception(f"{self.cache}/org does not exist")

        load_orgs = list()

        for dir in os.listdir(f"{self.cache}/org"):
            if os.path.isdir(f"{self.cache}/org/{dir}"):
                load_orgs.append(f"{self.cache}/org/{dir}")

        for org_path in load_orgs:
            if os.path.isfile(f"{org_path}/metadata.json") is not True:
                raise Exception(f"{org_path}/metadata.json does not exist")

            new_org = Org.parse_file(f"{org_path}/metadata.json")

            new_org.load(org_path)

            self.add_org(new_org)

    def find_projects_by_repo(self, name, id) -> List[Project]:

        found_projects = list()

        for org in self.orgs:
            found_projects.extend(org.find_projects_by_repo(name, id))

        return found_projects

    def get_token_for_org(self, org: Org) -> str:

        group = [g for g in self.groups if str(g["id"]) == str(org.group_id)]

        snyk_token = group[0]["snyk_token"]

        return snyk_token

    def get_token_for_group(self, group: str) -> str:

        group = [g for g in self.groups if g["name"] == group]

        snyk_token = group[0]["snyk_token"]

        return snyk_token

    def get_orgs_by_group(self, group: dict) -> List[Org]:

        g_id = group["id"]

        orgs = [o for o in self.orgs if str(o.group_id) == str(g_id)]

        return orgs
