
import os
import snyk
import json
from github import Github, Repository

from models import SnykWatchList, Repo, Project
from utils import yopen


def search_projects(base_name, origin, client, org_id):
    query = {"filters":{"origin":origin,"name":base_name}}
    path = f'org/{org_id}/projects'

    return json.loads(client.post(path,query).text)

repos = []

repo = {
    "source" : {
                'fork' : False,
                'name' : 'org-project-import',
                'owner' : 'snyk-playground',
                'branch' : 'main',
                'url' : 'https://github.com/snyk-playground/org-project-import'
                },
    "orgs" : [
        {
        'org': 'orgname',

    }
    ]
}

SNYK_TOKEN = os.environ["SNYK_TOKEN"]
SNYK_GROUP = os.environ['SNYK_GROUP']
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

gh = Github(GITHUB_TOKEN)

snyktoken = os.environ["SNYK_TOKEN"]
client = snyk.SnykClient(snyktoken)

conf = yopen('tests/examples/config.yaml')


# org:snyk-playground

watchlist = SnykWatchList()

for org in conf['github_orgs']:
    gh_repos = gh.search_repositories('org:snyk-playground')
    for the_repo in gh_repos:
        # i know there is a better way to do this
        tmp_repo = {
                'fork' : the_repo.fork,
                'name' : the_repo.name,
                'owner' : the_repo.owner.name,
                'branch' : the_repo.default_branch,
                'url' : the_repo.html_url,
                'project_base' : the_repo.full_name,
                }
        tmp_target = Repo(source=tmp_repo)
        watchlist.repos.append(tmp_target)

#print(projects.repos)

rrr = ['snyk-playground/nightmare']


# remove the phantom orgs that are really the groups
org_ids = [ o for o in client.organizations.all() if hasattr(o.group,'id') ]
# remove orgs that don't match the snykgroup
org_ids = [ o.id for o in org_ids if o.group.id == SNYK_GROUP ]


for r in watchlist.repos:
    for snyk_org in org_ids:
        #print(r.source.project_base)
        p_resp = search_projects(r.source.project_base, 'github-enterprise', client, snyk_org)
        for p in p_resp['projects']:
            p['org_id'] = p_resp['org']['id']
            p['org_name'] = p_resp['org']['name']
            r.projects.append(Project.parse_obj(p))
        #print(r)


#print("print(watchlist.search(project_base='snyk-playground/nightmare',type='pip'))")
#print(json.dumps(json.loads(watchlist.search(project_base="snyk-playground/nightmare",type='pip')[0].json()), indent=2))


# snykctl api -m post --data '{"filters":{"origin":"github-enterprise","name":"snyk-playground/angrydome"}}' org/ie-playground/projects | jq

watchlist.save(file='output.json')