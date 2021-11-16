import argparse
import time
import yaml


from github import Github
from os import environ


def parse_command_line_args():
    parser = argparse.ArgumentParser(description="Quick script to run sync's API calls and see impact on github")
    parser.add_argument("--conf-yaml", help="Path to config yaml to use", required=True)
    parser.add_argument("--per-page", help="results per page to use", required=True)

    return parser.parse_args()


args = parse_command_line_args()
conf_yaml = args.conf_yaml
per_page = int(args.per_page)

with open(conf_yaml, "r") as the_file:
    conf_file = yaml.safe_load(the_file.read())

github_token = environ["GITHUB_TOKEN"]

gh = Github(github_token, per_page=per_page)


core_limit = gh.get_rate_limit().core.limit
search_limit = gh.get_rate_limit().search.limit

core_start = int(gh.get_rate_limit().core.remaining)
search_start = int(gh.get_rate_limit().search.remaining)


def rate_limit(gh: Github):
    global core_start
    global search_start

    core_left = int(gh.get_rate_limit().core.remaining)
    search_left = int(gh.get_rate_limit().search.remaining)

    core_used = core_start - core_left
    search_used = search_start - search_left

    core_start = core_left
    search_start = search_left

    print(f"\t\tCore Cost: {core_used}\tSearch Cost: {search_used}")


print(f"Core Limit: {core_limit}\nSearch Limit: {search_limit}")
print(f"Results per page: {per_page}")
print("These are API calls: all repos for each org in config")
for org in conf_file["github_orgs"]:
    print(f"\tGetting GH Org for {org}")
    gh_org = gh.get_organization(org)
    rate_limit(gh)
    print(f"\tGetting all repos for {org}")
    gh_repos = gh_org.get_repos(type="all", sort="updated", direction="desc")
    rate_limit(gh)
    print(f"\tTotal repos for {org}: {gh_repos.totalCount}")
    rate_limit(gh)

import_yamls = []
print("\nAPI calls for searching for import.yaml")
for org in conf_file["github_orgs"]:
    search = f"org:{org} path:.snyk.d filename:import language:yaml"
    print(f"\tPerforming import.yaml search across {org}")
    import_repos = gh.search_code(query=search)
    rate_limit(gh)
    print(f"\tTotal repos for {org} with a import.yaml hit: {import_repos.totalCount}")
    rate_limit(gh)
    print(f"\tFiltering the list of import.yaml matches for {org}")
    import_repos = [y for y in import_repos if y.name == "import.yaml"]
    rate_limit(gh)
    import_yamls.extend(import_repos)
