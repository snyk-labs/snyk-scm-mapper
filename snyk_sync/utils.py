import json
import yaml

from datetime import datetime
from github import Github, Repository


def jprint(something):
    print(json.dumps(something, indent=2))


def jopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return json.loads(data)


def yopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return yaml.safe_load(data)


def search_projects(base_name, origin, client, org_id):
    query = {"filters": {"origin": origin, "name": base_name}}
    path = f"org/{org_id}/projects"

    return json.loads(client.post(path, query).text)

def newer(cached: str, remote: str) -> bool:
    #2021-08-25T13:37:43Z

    cache_ts = datetime.strptime(cached, "%Y-%m-%d %H:%M:%S")
    remote_ts = datetime.strptime(remote, "%Y-%m-%d %H:%M:%S")

    #print(cache_ts, remote_ts)

    return bool(remote_ts < cache_ts)



class RateLimit:
    def __init__ (self, gh: Github):
        self.core_limit = gh.get_rate_limit().core.limit
        self.search_limit = gh.get_rate_limit().search.limit
        # we want to know how many calls had been made before we created this object
        # calling this a tare 
        self.core_tare = gh.get_rate_limit().core.limit - gh.get_rate_limit().core.remaining
        self.search_tare = gh.get_rate_limit().search.limit - gh.get_rate_limit().search.remaining
        self.core_calls = [0]
        self.search_calls = [0]
        self.gh = gh
    
    def update (self, display: bool = False):
        core_call = self.core_limit - self.core_tare - self.gh.get_rate_limit().core.remaining
        search_call = self.search_limit - self.search_tare - self.gh.get_rate_limit().search.remaining

        self.core_calls.append(core_call)
        self.search_calls.append(search_call)

        if display:
            core_diff = self.core_calls[-1] - self.core_calls[-2]
            search_diff = self.search_calls[-1] - self.search_calls[-2]
            print(f'GH RateLimit: Core Calls = {core_diff}')
            print(f'GH RateLimit: Search Calls = {search_diff}')


    def total (self):
        print(f'GH RateLimit: Total Core Calls = {self.core_calls[-1]}')
        print(f'GH RateLimit: Total Search Calls = {self.search_calls[-1]}')