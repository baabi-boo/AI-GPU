# Old-code negative controls

The reports and controls in this directory preserve the failed old-code
observations; they are not passing runs. Two original unittest logs are stored
as `.log.gz` files because their raw progress output contains trailing spaces.
Decompression restores every original byte. `compressed-originals.json` binds
both original and compressed identities. No log content was reformatted.
