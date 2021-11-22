import json
import yaml
import requests

from retry.api import retry_call
from datetime import datetime
from github import Github, Repository


V3_VERS = "2021-08-20~beta"
USER_AGENT = "pysnyk/snyk_services/snyk_sync"


def jprint(something):
    print(json.dumps(something, indent=2))


def jopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return json.loads(data)


def jwrite(data, filename):
    try:
        with open(filename, "w") as the_file:
            the_file.write(json.dumps(data, indent=2))
            return True
    except:
        return False


def yopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return yaml.safe_load(data)


def newer(cached: str, remote: str) -> bool:
    # 2021-08-25T13:37:43Z

    cache_ts = datetime.strptime(cached, "%Y-%m-%d %H:%M:%S")
    remote_ts = datetime.strptime(remote, "%Y-%m-%d %H:%M:%S")

    # print(cache_ts, remote_ts)

    return bool(remote_ts < cache_ts)


class RateLimit:
    def __init__(self, gh: Github):
        self.core_limit = gh.get_rate_limit().core.limit
        self.search_limit = gh.get_rate_limit().search.limit
        # we want to know how many calls had been made before we created this object
        # calling this a tare
        self.core_tare = gh.get_rate_limit().core.limit - gh.get_rate_limit().core.remaining
        self.search_tare = gh.get_rate_limit().search.limit - gh.get_rate_limit().search.remaining
        self.core_calls = [0]
        self.search_calls = [0]
        self.gh = gh

    def update(self, display: bool = False):
        core_call = self.core_limit - self.core_tare - self.gh.get_rate_limit().core.remaining
        search_call = self.search_limit - self.search_tare - self.gh.get_rate_limit().search.remaining

        self.core_calls.append(core_call)
        self.search_calls.append(search_call)

        if display is True:
            core_diff = self.core_calls[-1] - self.core_calls[-2]
            search_diff = self.search_calls[-1] - self.search_calls[-2]
            print(f"GH RateLimit: Core Calls = {core_diff}")
            print(f"GH RateLimit: Search Calls = {search_diff}")

    def total(self):
        print(f"GH RateLimit: Total Core Calls = {self.core_calls[-1]}")
        print(f"GH RateLimit: Total Search Calls = {self.search_calls[-1]}")


def make_v3_get(endpoint, token):
    V3_API = "https://api.snyk.io/v3"
    USER_AGENT = "pysnyk/snyk_services/target_sync"

    client = requests.Session()
    client.headers.update({"Authorization": f"token {token}"})
    client.headers.update({"User-Agent": USER_AGENT})
    client.headers.update({"Content-Type": "application/vnd.api+json"})
    url = f"{V3_API}/{endpoint}"
    return client.get(url)


def v3_get(endpoint, token, delay=1):
    result = retry_call(make_v3_get, fkwargs={"endpoint": endpoint, "token": token}, tries=3, delay=delay)
    return result


def get_org_targets(org: dict, token: str) -> list:

    print(f"getting {org['id']} / {org['slug']} targets")
    targets_raw = v3_get(f"orgs/{org['id']}/targets?version={V3_VERS}", token)

    targets_resp = targets_raw.json()

    targets = targets_resp["data"]

    return targets


def get_org_projects(org: dict, token: str) -> dict:

    print(f"getting {org['id']} / {org['slug']} projects")

    try:
        first_resp = v3_get(f"orgs/{org['id']}/projects?version={V3_VERS}", token)
    except Exception as e:
        print(f"{org['id']} project lookup failed with {e}")
        orgs_resp = {"data": []}
        return orgs_resp

    orgs_resp = first_resp.json()

    all_pages = list()
    all_pages.extend(orgs_resp["data"])

    while "links" in orgs_resp.keys():
        if "next" in orgs_resp["links"].keys():
            first_resp = v3_get(orgs_resp["links"]["next"], token)
            orgs_resp = first_resp.json()
            if "data" in orgs_resp.keys():
                all_pages.extend(orgs_resp["data"])
        else:
            orgs_resp.pop("links")

    orgs_resp["data"] = all_pages

    return orgs_resp


def search_projects(base_name, origin, client, snyk_token, org_in: dict):

    org = dict()

    org["id"] = org_in["orgId"]
    org["slug"] = org_in.keys()[0]

    query = {"filters": {"origin": origin, "name": base_name}}
    path = f"org/{org_id}/projects"

    return json.loads(client.post(path, query).text)


def to_camel_case(snake_str):
    components = snake_str.split("_")
    # We capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    return components[0] + "".join(x.title() for x in components[1:])
