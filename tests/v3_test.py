from os import environ
from pprint import pprint


from api import SnykV3Client

snyk_token = environ["SNYK_TOKEN"]
snyk_org = environ["SNYK_ORG"]


client = SnykV3Client(token=snyk_token)

targets = client.get(f"orgs/{snyk_org}/targets")

pprint(targets)
