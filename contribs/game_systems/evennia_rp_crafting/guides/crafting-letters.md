---
key: crafting-letters
title: Books, journals and letters
category: Making & trading
requires: RP_CRAFTING_REVEALED
aliases: [books, journals, letters]
order: 32
summary: Reading crafted books, writing in journals, copying, addressing letters, and sealing them with a signet.
---
A crafter who makes books can make them with fixed pages, blank journals for anyone to write in, and letters. Anyone can read them.

- `read <item>` reads the page you were on, and `read <item>=<page>` a chosen page.
- `read/contents <item>` lists the page titles.
- `+journal/write <journal>=<text>` writes a new page in a journal you carry.
- `+letter/address <letter>=<name>` addresses a letter, and `+letter/seal <letter>=<signet>` seals it.

## Reading

A book remembers the page you got to, so `read <book>` picks up where you left off. Looking at the contents doesn't move your place. You can read a book you carry or one in the room with you.

## Making a book

Start a readable draft, then add pages with `+craft/page [title]=<text>`, or set all the text at once with `+craft/text`. Each page past the first adds a little to the cost. Once it's made, a book's pages never change.

## Journals

A journal is a blank book with a number of pages, chosen when it's made: `+craft/journal <pages>`. Set a page title with `+journal/title <journal>/<page>=<title>`. Title and text changes preserve the other field and append a revision. Whoever carries it can write in it for free, with `+journal/write`, and `+journal/revise <journal>/<page>=<text>` changes a page you wrote.

If you give a journal away, its new owner can add pages but can't change yours. If it comes back to you, you can revise your own pages again. Every page shows who wrote it, under an OOC label.

:::insight[Revisions are history, not erasure]
`+journal/history <journal>/<page>` shows every earlier version of a page. Revising a page changes what it says now, never what it said before, so nobody can quietly rewrite what was written in a journal.
:::

## Copies

A crafter who can make books can copy one they can read: `+craft/copy <book>=<craft>/<name>`. A copy costs the same as any book, and keeps the text and each page's real writer as they were when it was copied. Later changes to the original don't touch it. The copy's hallmark names who copied it, as well as who wrote the text.

## Letters and seals

Any readable can be a letter. Its **addressee** is in-character description, such as "To the Keeper". It doesn't stop anyone else reading it.

A **signet** is a wearable bearing a seal design, made by crafts your game allows. To seal a letter, carry it and a signet, and `+letter/seal <letter>=<signet>`. You don't need a workshop to use a signet someone else made.

The first person to read a page of a sealed letter breaks the seal, and is told so. Looking at the contents doesn't open it. Sealing freezes the letter for good: its addressee and any journal pages can't change, even after it's opened. You can seal it again, but it then shows that it's been opened and resealed.

:::insight[A seal is a story, not a lock]
A seal shows whether a letter has been opened, which is what a seal does in a story. It doesn't keep anyone out, and a design can be copied or stolen in character, so it never proves out of character who sent the letter.
:::

## Lore in books

If your game has lore, a book may cite lore entries, so that reading the page that cites one teaches it. Reading the contents teaches nothing.
