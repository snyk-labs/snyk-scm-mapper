import json
from logging import exception, raiseExceptions
import yaml
import requests


from typer import Context

from retry.api import retry_call
from datetime import datetime
from github import Github, Repository
from pathlib import Path

from uuid import UUID

from os import environ

from models.sync import Settings


V3_VERS = "2021-08-20~beta"
USER_AGENT = "pysnyk/snyk_services/snyk_sync"


def jprint(something):
    print(json.dumps(something, indent=2))


def jopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return json.loads(data)


def jwrite(data, filename, minimize: bool = False):
    try:
        with open(filename, "w") as the_file:
            if minimize:
                the_file.write(json.dumps(data, separators=(",", ":")))
            else:
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


def default_settings(name: str, value: str, default: str, context: Context) -> Settings:
    """
    We want a self / auto configuring experience for Snyk Sync, but also allow for options to be passed from ENV, CLI, OR a config file.
    CLI overrides ENV, and typer handles that for us. But we want CLI and ENV to override the config file, so we need to load that value
    Also we have a lot of relativistic values, ie the tags directory is in the root of the folder containing the config file
    So if tag_dir isn't set by CLI or ENV, it ends up here. Then if it's not set in the conf file, we want to return the directory of the
    conf file + /tags
    """

    # Since we've removed the typer check for the conf file, we have to ensure it exists here

    if context.invoked_subcommand == "autoconf":
        if name == "conf":
            if Path(value).exists is False:
                new_conf = {"schema": 2}
                Path(value).write_text(yaml.safe_dump(new_conf))
            elif Path(value).is_dir():
                raise Exception(f"Snyk Sync config file: {value} is a directory, it needs to be yaml file")

    settings = context.params

    # we're likely never called, but just in case,
    # if there is already a value and it's not the
    # default value it wins, it was set by CLI or ENV
    if value != default:
        return value

    if "conf" in settings.keys():
        conf_file = Path(settings["conf"])
    else:
        conf_file = Path("snyk-sync.yaml")

    if conf_file.exists():
        auto_conf = False
    else:
        auto_conf = True

    if not auto_conf:
        s = yopen(conf_file)
    else:
        s = {}

    s: dict

    # here we return whatever we find in the conf file
    if name in s.keys():
        return s[name]

    # everything below here is dynamic handling of values

    if name == "snyk_orgs_file":
        if "orgs_file" in s.keys():
            return s["orgs_file"]
        else:
            return gen_path(conf_file, "snyk-orgs.yaml")

    # pretty much we want to break here and not do magic in the case of autoconf
    if auto_conf:
        return value

    # our directories are always 'dirname'_dir
    if "_dir" in name:
        dirname = name.split("_")[0]

        the_dir_path = gen_path(conf_file, dirname)

        if not auto_conf:
            ensure_dir(the_dir_path)

        return the_dir_path

    if name == "snyk_token":

        token_env_name = s["snyk"]["groups"][0]["token_env_name"]

        if token_env_name in environ.keys():
            token = environ[token_env_name]
        else:
            raise Exception(f"Environment Variable {token_env_name} for {name}is not set properly and required")

        return token

    if name == "github_token":

        token_env_name = s["github_token_env_name"]

        if token_env_name in environ.keys():
            token = environ[token_env_name]
        else:
            raise Exception(f"Environment Variable {token_env_name} for {name}is not set properly and required")

        return token

    if name == "default_org":
        return s["default"]["orgName"]

    if name == "default_int":
        return s["default"]["integrationName"]

    return default


def gen_path(parent_file: Path, child: str):
    the_path_string = f"{parent_file.parent}/{child}"

    return Path(the_path_string)


def ensure_dir(directory: Path) -> bool:
    if not directory.exists():
        try:
            directory.mkdir()
            return True
        except Exception as e:
            raise Exception(f"Error attempting to create {directory}: {e}")
    elif directory.is_file():
        raise Exception(f"Expected {directory} to be a directory, but is a file")
    else:
        # the directory exists and is OK
        return True
