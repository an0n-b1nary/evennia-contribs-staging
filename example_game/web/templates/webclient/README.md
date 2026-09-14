Replace Evennia's webclient django template with your own here.

The game overrides `webclient/webclient.html` to add a route back to the site
while extending Evennia's stock base shell. The original files are in
`evennia/web/templates/webclient/`; a local template with the same relative
name takes precedence after reload.
