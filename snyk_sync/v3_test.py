from os import environ
from pprint import pprint

from api import SnykV3Client, v1_get_pages
from utils import yopen

from models.organizations import Orgs, Org, Target

from snyk import SnykClient

import logging

import json

logging.basicConfig(level="DEBUG")

snyk_token = environ["SNYK_TOKEN"]
snyk_org = environ["SNYK_ORG"]

V3_VERS = "2021-08-20~beta"

v3 = SnykV3Client(token=snyk_token, tries=2, delay=1)

v1 = SnykClient(token=snyk_token, tries=2, delay=1)


# conf = yopen("conf/snyk-sync.yaml")


# target = {
#     "id": "a75a88f5-92d0-4100-ad05-56c5bc4798db",
#     "attributes": {"displayName": "snyk/goof", "origin": "github", "remoteUrl": "", "isPrivate": False},
# }

# # , "36863d40-ba29-491f-af63-7a1a7d79e411"]

# groups = ["dcf9cae3-2f54-4ad2-98af-e70b844657f3", "36863d40-ba29-491f-af63-7a1a7d79e411"]

# all_orgs = Orgs(cache="conf/cache", groups=groups)

# all_orgs.summary()

# select_orgs = ["39ddc762-b1b9-41ce-ab42-defbe4575bd6"]

# all_orgs.refresh_orgs(v1, v3, origin="github", selected_orgs=select_orgs)

# all_orgs.summary()

# all_orgs.save()

# new_orgs = Orgs(cache="conf/cache", groups=groups)

# new_orgs.load()

# new_orgs.summary()

# print(new_orgs.find_projects_by_repo("mrzarquon/goof", "1"))

params = {"limit": 100, "excludeEmpty": True}

all_targets = v3.get_all_pages("orgs/7a1e8ed0-a28b-4fab-a153-e6281ca72e81/targets", params)

print(len(all_targets))
