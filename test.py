from pathlib import Path


foo = Path('cached',file_okay=False,dir_okay=True)

print(foo.is_dir(), foo.exists())

if not foo.exists():
    print(f"{foo.name} is not a directory")
else:
    print('its here')

foo.mkdir()

if not foo.exists():
    print('its not here')
else:
    print('its here')