"""
Connection screen

This is the text to show the user when they first connect to the game (before
they log in).

To change the login screen in this module, do one of the following:

- Define a function `connection_screen()`, taking no arguments. This will be
  called first and must return the full string to act as the connection screen.
  This can be used to produce more dynamic screens.
- Alternatively, define a string variable in the outermost scope of this module
  with the connection string that should be displayed. If more than one such
  variable is given, Evennia will pick one of them at random.

The commands available to the user when the connection screen is shown
are defined in evennia.default_cmds.UnloggedinCmdSet. The parsing and display
of the screen is done by the unlogged-in "look" command.

----

This screen is split in two on purpose. The `connect`/`create` block is UI - it
tells someone which keys to press and has to stay accurate. WELCOME is prose,
and prose in this game belongs to whoever runs it, so it ships as a placeholder
with a note about what it should convey. Replace it; nothing reads its content.

Deliberately absent: any contact address. A demo screen is the easiest place to
leave a real email or handle by accident, and the feedback channel this sandbox
actually wants is `+bug` and `+request` in-game, which need no address at all.
"""

from django.conf import settings
from evennia import utils

# [Placeholder] Two or three lines of welcome. Should convey: this is a public
# sandbox for trying out a set of Evennia contribs, not a running game; anyone
# may make an account; the world resets to a default state periodically, so
# nothing built here is permanent; and `+sandbox` in-game is the starting
# point for the tour.
WELCOME = (
    "[Placeholder] A short welcome. Convey: public demo sandbox, not a live "
    "game; accounts are open to anyone; the world resets; type +sandbox once "
    "you are in."
)

CONNECTION_SCREEN = """
|b==============================================================|n
 Welcome to |g{servername}|n, version {version}!

 {welcome}

 If you have an existing account, connect to it by typing:
      |wconnect <username> <password>|n
 If you need to create an account, type (without the <>'s):
      |wcreate <username> <password>|n

 If you have spaces in your username, enclose it in quotes.
 Enter |whelp|n for more info. |wlook|n will re-show this screen.

 Once you are in, |w+sandbox|n explains where everything is.
|b==============================================================|n""".format(
    servername=settings.SERVERNAME,
    version=utils.get_evennia_version("short"),
    welcome=WELCOME,
)
