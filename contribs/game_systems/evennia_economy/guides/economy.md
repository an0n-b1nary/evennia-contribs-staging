---
key: economy
title: Money and trade
category: Making & trading
requires: RP_ECONOMY_REVEALED
aliases: [trading, money]
order: 10
summary: Your purse and weekly income, trading and gifts, stalls and shops, and finding things to buy.
---
Every character has a purse. Money comes in every week on its own, and you spend it by trading with other characters or buying from their stalls and shops. Your game names its own currency; these examples use coins.

- `+balance` shows your purse, and how close it is to the cap on weekly income.
- `+offer <character>=<what you give> for <what you want>` proposes a trade, and `+accept <number>` takes one.
- `give <things> to <character>` hands something over straight away.
- `+market [search]` finds stalls across the game, and `+browse` shows the stalls where you're standing.
- `+buy <listing>` buys from a stall or shop in the room you're in.

## Weekly income

Each week, every character's purse gets a share of money. It's paid while you're away as well as while you play, and it doesn't depend on how much you roleplayed. A new character also gets a starting sum once.

Income slows as your purse nears its cap, and stops at the cap. The cap only limits weekly income: trades, gifts and anything staff give you can take you past it. Some things you own, such as a stall, raise the cap while you hold them.

:::insight[Nothing you hold decays]
Money you've earned stays yours however long you're away. The cap slows income for full purses instead of taking anything back, so nobody has to log in to protect what they have.
:::

## Trading

An offer can swap money, items and anything else your game lets you trade, in any mix: `+offer Mara=40 coins for #12`, or a carried item by name. Leave out `for <what you want>` to offer a gift. You both need to be in the same room, and the offer lapses if either of you leaves, or after a while if nobody accepts it. `+offer` lists your open offers, and either of you can call one off with `+offer/cancel <number>`.

Nothing is set aside while an offer waits. When it's accepted, the game checks again that both of you still have what you promised, then moves everything together.

:::insight[Both sides or neither]
A trade moves everything at once or nothing at all, so nobody is left holding half of a deal. If one side can't pay when the offer is accepted, nothing moves.
:::

The two of you see the details. Everyone else in the room sees only that you completed a trade, and either of you can add `/secret` to `+offer` or `+accept` to leave out even that.

`give` works for items, money and other assets alike, and it never uses up one of your open offers. You can't trade or give anything to another character of your own.

## Stalls

A market room has a limited number of stalls. `+stall/claim <name>` takes one, and `+stall/name` and `+stall/desc` describe it. `+stall/list <item>=<price>` puts something up for sale. Listing moves it out of your hands into the stall, so it can't be sold twice or lost while it waits. `+stall/unlist <listing>` takes it back, and `+stall/close` closes the stall and returns everything still on it.

You don't need to be there for a sale. Buyers come to the stall's room, and the money goes straight to your purse. Your game may charge small fees for stalls, listings, sales or trades, and a sale's fee comes out of what it earns. A stall left untouched for a long while is mentioned to staff, but it's never closed for you.

## Shops

If your game has property, staff can approve a place you own as a shop. Its entrance then holds a storefront that works like a stall: `+shop/list`, `+shop/unlist`, `+shop/name` and `+shop/desc`, and `+shop/close` and `+shop/reopen`. Only the owner can stock it.

## Finding things to buy

`+market` searches every open stall in the game by name, description and what's for sale. It leaves out stalls in places hidden from you. To buy, go to the stall's room, `+browse` to see the listings and `+buy <listing>`.

Some games also run a seller for basic goods. Where there is one, `+browse/system` and `+buy/system <goods>=<amount>` buy from it. It charges more than the goods' usual price, and it never buys anything back.

## When it's paused or hidden

Staff can pause the economy. While it's paused, no money or other assets change hands, but you can still give items. Before a game opens its economy, `give` hands over items only, and the money side doesn't show.

## What staff see

Staff can read the record of every exchange. If something you send another player soon comes back to a different character on your account, or an item you drop is picked up by one, staff are asked to look. A flag never blocks a trade, takes anything away or tells anyone on its own.
