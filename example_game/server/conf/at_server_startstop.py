"""
Server startstop hooks

This module contains functions called by Evennia at various
points during its startup, reload and shutdown sequence. It
allows for customizing the server operation as desired.

This module must contain at least these global functions:

at_server_init()
at_server_start()
at_server_stop()
at_server_reload_start()
at_server_reload_stop()
at_server_cold_start()
at_server_cold_stop()

"""


def at_server_init():
    """
    This is called first as the server is starting up, regardless of how.
    """
    pass


def at_server_start():
    """
    This is called every time the server starts up, regardless of
    how it was shut down.
    """
    # evennia_rptracker — recover DB sessions orphaned by a crash/kill,
    # then ensure the idle-check Script is running.
    from evennia_rptracker import ensure_idle_check_running, recover_orphaned_sessions

    recover_orphaned_sessions()
    ensure_idle_check_running()

    # evennia_calendar — start the lottery/RSVP-expiry/reminder maintenance
    # Script. Evennia has no server-start signal the contrib can hook itself,
    # so this call is required (see the contrib's README §"Wire the
    # maintenance script"). Idempotent — safe on every start/reload.
    from evennia_calendar.scheduler import ensure_calendar_script_running

    ensure_calendar_script_running()

    # evennia_xp — start the weekly (Monday 00:00 UTC) batch Script.
    from evennia_xp.scripts import ensure_xp_batch_script_running

    ensure_xp_batch_script_running()


def at_server_stop():
    """
    This is called just before the server is shut down, regardless
    of it is for a reload, reset or shutdown.
    """
    # evennia_rptracker — flush all in-memory session state to the DB
    # before shutdown so no pose counts or sessions are lost.
    from evennia_rptracker import flush_all_sessions

    flush_all_sessions()


def at_server_reload_start():
    """
    This is called only when server starts back up after a reload.
    """
    pass


def at_server_reload_stop():
    """
    This is called only time the server stops before a reload.
    """
    pass


def at_server_cold_start():
    """
    This is called only when the server starts "cold", i.e. after a
    shutdown or a reset.
    """
    pass


def at_server_cold_stop():
    """
    This is called only when the server goes down due to a shutdown or
    reset.
    """
    pass
