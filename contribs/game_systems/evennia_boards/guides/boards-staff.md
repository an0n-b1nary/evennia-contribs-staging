---
key: boards-staff
title: "Staff: bulletin boards"
audience: staff
category: Staff
summary: Creating boards, read-only announcements, archiving and reviewing XP flags.
---
## What it's for

Staff provide public places to post and keep their records usable. Players' commands are on [[boards]]. Posting to read-only boards, editing others' posts and archiving use `BOARDS_STAFF_LOCK`, Builder by default. Creating boards requires separate Django admin access.

## Tasks and commands

- **Creating a board:** in the Django admin, add a Board with a unique name, description, display order and OOC or IC type. Set read-only for staff announcements. Changing order changes its number in `+bb`; names make clearer references when numbers move.
- **Read-only announcements:** `+bb/post <board>=<title>` opens the editor for staff even on a read-only board; `/reply <board>/<post>` works there for staff too. Read-only controls who writes, not who reads.
- **Archiving:** `+bb/archive <board>/<post>` removes an old post from ordinary listings without deleting its stored record. Post numbers are per board and gaps are intentional. There is no matching in-game unarchive command.
- **Corrections:** `+bb/edit <board>/<post>` allows staff to edit another author's post and preserves a version. Use it for an agreed correction, not to erase the earlier record.
- **XP flags:** with the IC-post XP integration and sweep configured, suspicious bursts of posts are marked `xp_flagged` and excluded from awards. Review the reason and posts in the admin; clear the flag on legitimate posts after review.

## What's safe to change

Board names, descriptions and ordering are admin settings. Choose IC versus OOC deliberately: it affects XP eligibility with the integration enabled. Preserve post numbers and version history. Archive posts instead of deleting boards or rewriting post records; deleting a board also deletes its posts. Clear an XP flag only after checking why it was set.

## Privacy

Boards are public communication, including read-only boards. They are not a staff notes store. Keep reports about suspected XP abuse in staff channels rather than adding an accusation to the public post.

## Review jobs

`BOARDS_ANTIGAMING_REPORTER` can send sweep findings to a staff-review reporter such as Jobs. With no reporter, findings are logged instead. Answer the review ticket and separately clear any legitimate post's XP flag; closing a ticket alone does not change the post.
