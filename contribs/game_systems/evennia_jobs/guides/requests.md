---
key: requests
title: Asking staff for help
category: Community & help
order: 20
aliases: [jobs]
summary: Requests, bug reports and private reports to staff, structured forms, and following up on them.
---
When you need staff, open a ticket. There are three kinds, so each reaches the right people in the right way.

- `+request <title>=<details>` asks for something: a question, a proposal, approval for an idea.
- `+bug <title>=<details>` reports something broken. Say what you did, what you expected and what happened instead.
- `+issue <title>=<details>` reports a problem with another player, such as harassment or anything that needs moderation.
- `+request/forms` lists the forms your game offers for structured proposals.

Leave out `=<details>` to write the details in an editor instead. The website has a form for each kind too.

## Following up

`+request` on its own lists your tickets of every kind that aren't closed yet, and `+request <id>` shows one with staff's replies. `+request/comment <id>=<text>` adds to it. The website's tickets page shows the same.

Staff can keep internal notes on a ticket that you won't see. Everything they write *to* you shows on the ticket.

## Forms

Some proposals need the same answers every time, so your game may set up a **form** for them: a list of questions that staff review together. `+request/form <form>=<title>` starts one. Then answer each question with `+request/answer <question>=<answer>`, or `+request/edit <question>` for a longer answer in the editor. Your answers are saved as you go, so you can stop and come back with `+request/resume`. `+request/preview` shows everything before `+request/submit` sends it. The website's tickets page links the same forms.

Some questions are acknowledgements, such as agreeing that your work may be reused. They need a yes before you can submit.

Staff approve the form, decline it, or ask for changes, and each decision comes with their reason. If they ask for changes, `+request/revise <id>` starts a new revision with your earlier answers filled in. You'll need to give any acknowledgements again. While a revision is waiting, you can take it back with `+request/withdraw <id>.<revision> # <reason>`, and revise it later if you like.

:::insight[Every revision stays on the record]
A new revision never overwrites an old one. The ticket keeps every version you sent, each decision and its reason, and any withdrawal, so you and staff can always see what was agreed and when.
:::

## Private reports

Every ticket is between you and staff. Only you and staff can read it.

:::insight[Only staff know who reported]
An issue report names someone, so its author is hidden from everyone but staff. Other players never see who filed it, which makes it safer to speak up.
:::

## Visiting as a guest

Guests can send plain requests and comment on them, but can't use forms.

## "Ask about this page"

Guide pages have an **Ask about this page** link at the bottom when your game supports it. It opens a request with the page already named, so you only have to write your question.
