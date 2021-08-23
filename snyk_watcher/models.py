import json
import yaml
from pprint import pprint
from dataclasses import dataclass
from typing import Optional

from typing import List, Optional, TypedDict, Tuple, Dict

from pydantic import BaseModel, FilePath, ValidationError, root_validator, UUID4, Field

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
    __root__: Dict[str,Org]
    
    def __iter__(self):
        return iter(self.__root__)

    def __getitem__(self, item):
        return self.__root__[item]
    
    @root_validator
    def remap_names(cls, values):
        for k in values['__root__']:
            values['__root__'][k].name = k
        return values

class Source(BaseModel):
    fork: bool
    name: str
    owner: str
    branch: str
    url: str
    project_base: str

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
        valid_keys = { x:y for x,y in kwargs.items() if x in self.__dict__}
        matches = 0
        for key, value in valid_keys.items():
            if key in self.__dict__:
                if getattr(self, key) == value:
                    #print(key, value)
                    matches += 1
        #print(matches)
        return matches > 0


class Repo(BaseModel):
    source: Source
    projects: List[Project] = []

    def match(self, **kwargs):
        valid_keys = { x:y for x,y in kwargs.items() if x in self.source.__dict__}
        #print(valid_keys)
        matches = 0
        for key, value in valid_keys.items():
            if key in self.source.__dict__:
                if getattr(self.source, key) == value:
                    #print(key, value)
                    matches += 1
        
        project_matches = 0
        project_attributes = 0

        for project in self.projects:
            project_attributes = len([ x for x,y in kwargs.items() if x in project.__dict__])
            if project.match(**kwargs):
                project_matches += 1
        
        if project_attributes > 0:
            matches_projects = project_matches > 0
        else:
            matches_projects = True


        return matches == len(valid_keys) and matches_projects 


class SnykWatchList(BaseModel):
    repos: List[Repo] = []
    
    def match(self, **kwargs):
        data = []
        
        for repo in self.repos:
            if repo.match(**kwargs):
                data.append(repo)

        return data
    
    def save(self, file):
        json_repos = [json.loads(r.json()) for r in self.repos]

        with open(file, "w") as the_file:
            json.dump(json_repos,the_file, indent=4)